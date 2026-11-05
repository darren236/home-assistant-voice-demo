import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import wave

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.error import Error
from wyoming.info import Describe, Info
from wyoming.asr import Transcribe, Transcript
from wyoming.tts import Synthesize, SynthesizeVoice


async def health(port):
    async with AsyncTcpClient("127.0.0.1", port) as client:
        await client.write_event(Describe().event())
        event = await asyncio.wait_for(client.read_event(), 4)
        if event is None or not Info.is_type(event.type):
            raise RuntimeError("Speech service did not describe itself")
    print("Speech service ready")


async def say(args):
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    complete = False
    try:
        async with AsyncTcpClient("127.0.0.1", args.port) as client:
            voice = SynthesizeVoice(name="Bedside " + args.route.title()) if args.route else None
            await client.write_event(Synthesize(text=args.text, voice=voice).event())
            with wave.open(str(partial), "wb") as wav:
                wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                started, count = False, 0
                while True:
                    event = await asyncio.wait_for(client.read_event(), 120)
                    if event is None:
                        raise RuntimeError("Speech connection closed before audio-stop")
                    if Error.is_type(event.type):
                        raise RuntimeError(Error.from_event(event).text)
                    if AudioStart.is_type(event.type):
                        start = AudioStart.from_event(event)
                        wav.setparams((start.channels, start.width, start.rate, 0, "NONE", "not compressed"))
                        started = True
                    elif AudioChunk.is_type(event.type):
                        if not started:
                            raise RuntimeError("Audio arrived before its format")
                        data = AudioChunk.from_event(event).audio
                        count += len(data)
                        wav.writeframesraw(data)
                    elif AudioStop.is_type(event.type):
                        if not started or not count:
                            raise RuntimeError("Speech service returned no audio")
                        complete = True
                        break
        partial.replace(output)
        print(json.dumps({"audio": str(output), "complete": complete}))
    finally:
        partial.unlink(missing_ok=True)


async def transcribe(args):
    import numpy as np
    import soxr
    with wave.open(str(args.input), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise ValueError("Expected PCM16 WAV")
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(-1, wav.getnchannels()).mean(axis=1)
        if wav.getframerate() != 16000:
            samples = soxr.resample(samples, wav.getframerate(), 16000)
    pcm = np.clip(samples, -32768, 32767).astype("<i2").tobytes()
    async with AsyncTcpClient("127.0.0.1", args.whisper_port) as client:
        await client.write_event(Transcribe(language="en").event())
        await client.write_event(AudioStart(rate=16000, width=2, channels=1).event())
        for offset in range(0, len(pcm), 3200):
            await client.write_event(AudioChunk(rate=16000, width=2, channels=1, audio=pcm[offset:offset + 3200]).event())
        await client.write_event(AudioStop().event())
        while True:
            event = await asyncio.wait_for(client.read_event(), 120)
            if event is None:
                raise RuntimeError("Recognition connection closed without a transcript")
            if Error.is_type(event.type):
                raise RuntimeError(Error.from_event(event).text)
            if Transcript.is_type(event.type):
                print(json.dumps({"transcript": Transcript.from_event(event).text}))
                return


def main():
    parser = argparse.ArgumentParser(description="Local CPU speech for Home Assistant")
    parser.add_argument("--data", type=Path, default=Path(os.getenv("BEDSIDE_DATA", ".local")))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare", help="Download revision-pinned public models and runtime")
    server = commands.add_parser("serve", help="Start a Wyoming speech service")
    server.add_argument("--port", type=int, default=10600)
    server.add_argument("--preset", default="Ava", choices=["Ava", "Bella", "Adam", "Nathan"])
    server.add_argument("--threads", type=int, default=3)
    server.add_argument("--route", choices=["phone", "server"], default=os.getenv("BEDSIDE_ROUTE", "server"))
    check = commands.add_parser("health")
    check.add_argument("--port", type=int, default=10600)
    speech = commands.add_parser("say", help="Write a completed Wyoming reply to a WAV")
    speech.add_argument("text")
    speech.add_argument("--output", type=Path, required=True)
    speech.add_argument("--port", type=int, default=10600)
    speech.add_argument("--route", choices=["phone", "server"])
    asr = commands.add_parser("transcribe", help="Transcribe a PCM16 WAV with Wyoming Whisper")
    asr.add_argument("--input", type=Path, required=True)
    asr.add_argument("--whisper-port", type=int, default=10601)
    commands.add_parser("quantize", help="Create a separate INT8 phone bundle with an FP32 codec")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.command == "prepare":
        from .assets import prepare
        prepare(args.data)
    elif args.command == "serve":
        from .engine import Engine
        from .server import serve
        asyncio.run(serve(Engine(args.data, args.preset, args.threads), args.data, args.route, args.port))
    elif args.command == "quantize":
        from .quantize import quantize
        quantize(args.data)
    elif args.command == "health":
        asyncio.run(health(args.port))
    elif args.command == "say":
        asyncio.run(say(args))
    elif args.command == "transcribe":
        asyncio.run(transcribe(args))


if __name__ == "__main__":
    main()
