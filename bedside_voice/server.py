"""Wyoming synthesis, phone-first routing, completed-audio caching and safe fallback."""
import asyncio
from contextlib import aclosing
import hashlib
import json
import logging
import time

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.info import Attribution, Describe, Info, TtsProgram, TtsVoice
from wyoming.server import AsyncEventHandler, AsyncTcpServer
from wyoming.tts import Synthesize

from . import phone
from .engine import RATE, TAIL
from .text import normalize_for_speech

LOG = logging.getLogger(__name__)
VOICES = ("Bedside Server", "Bedside Phone")


class Router:
    def __init__(self, engine, root, route="server"):
        self.engine, self.root, self.default_route = engine, root, route
        self.lock = asyncio.Lock()
        config = root / "phone.json"
        self.phone = json.loads(config.read_text()) if config.exists() else None
        if self.phone and engine.voice != self.phone.get("preset", "Ava"):
            raise ValueError("Phone and server presets differ; provision matching Ava prompt codes")
        self.cache = root / "cache"
        self.cache.mkdir(parents=True, exist_ok=True)

    async def stream(self, text, route):
        # Serialize the shared model/codec state for the entire reply.
        async with self.lock:
            ids = self.engine.tokenizer.encode(text)
            profile = {"format": 1, "voice": self.engine.voice,
                       "phone": self.phone["fingerprint"] if self.phone else None, "text": text}
            key = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
            path = self.cache / (key + ".pcm")
            if route == "phone" and self.phone:
                if path.exists():
                    LOG.info("route=cache")
                    with path.open("rb") as cached:
                        while data := cached.read(8192):
                            yield data
                    return
                if len(ids) <= 75:
                    sent, complete = False, bytearray()
                    try:
                        async with aclosing(phone.stream(self.phone, ids)) as chunks:
                            async for data in chunks:
                                if data:
                                    sent = True
                                    complete.extend(data)
                                    yield data
                        if not sent:
                            raise RuntimeError("Phone produced no PCM")
                        complete.extend(TAIL)
                        yield TAIL
                        temporary = path.with_suffix(".partial")
                        try:
                            temporary.write_bytes(complete)
                            temporary.replace(path)
                        except OSError:
                            LOG.warning("Could not cache completed phone reply", exc_info=True)
                            temporary.unlink(missing_ok=True)
                        LOG.info("route=phone")
                        return
                    except Exception:
                        if sent:
                            # Restarting an answer here would repeat words the listener heard.
                            raise
                        LOG.warning("Phone unavailable before PCM; route=server")
            async with aclosing(self.engine.stream(text)) as chunks:
                async for data in chunks:
                    yield data
            yield TAIL
            LOG.info("route=server")


class Handler(AsyncEventHandler):
    def __init__(self, reader, writer, router):
        super().__init__(reader, writer)
        self.router = router

    async def handle_event(self, event):
        if Describe.is_type(event.type):
            attribution = Attribution(name="OpenMOSS MOSS-TTS-Nano", url="https://github.com/OpenMOSS/MOSS-TTS-Nano")
            voices = VOICES if self.router.phone else VOICES[:1]
            await self.write_event(Info(tts=[TtsProgram(name="bedside_moss", attribution=attribution,
                installed=True, version="1", description="Local CPU speech with a built-in MOSS voice",
                voices=[TtsVoice(name=name, attribution=attribution, installed=True, version="1", languages=["en"],
                                 description="Public MOSS preset: " + self.router.engine.voice)
                        for name in voices])]).event())
        elif Synthesize.is_type(event.type):
            request = Synthesize.from_event(event)
            name = request.voice.name if request.voice else None
            text = normalize_for_speech(request.text.strip())
            if not 0 < len(text) <= 800 or name not in (*VOICES, None):
                await self.write_event(Error(text="Invalid text length or voice", code="invalid_request").event())
                return True
            route = ("phone" if name == VOICES[1] else "server") if name else self.router.default_route
            started, began, count = False, time.monotonic(), 0
            try:
                async with aclosing(self.router.stream(text, route)) as chunks:
                    async for pcm in chunks:
                        if not started:
                            LOG.info("first_pcm_ms=%d", round((time.monotonic() - began) * 1000))
                            await self.write_event(AudioStart(rate=RATE, width=2, channels=1).event())
                            started = True
                        count += len(pcm)
                        await self.write_event(AudioChunk(rate=RATE, width=2, channels=1, audio=pcm).event())
                await self.write_event(AudioStop().event())
                LOG.info("audio_seconds=%.2f total_ms=%d", count / RATE / 2, round((time.monotonic() - began) * 1000))
            except Exception:
                LOG.exception("Synthesis failed")
                await self.write_event(Error(text="Synthesis failed", code="synthesis_failed").event())
        return True


async def serve(engine, root, route, port):
    router = Router(engine, root, route)
    LOG.info("Ready: tcp://127.0.0.1:%d, preset=%s", port, engine.voice)
    await AsyncTcpServer("127.0.0.1", port).run(lambda r, w: Handler(r, w, router))
