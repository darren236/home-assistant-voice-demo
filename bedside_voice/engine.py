"""Warm FP32 CPU model, incremental codec, and streaming 24 kHz mono output."""
import asyncio
import threading
from pathlib import Path

import numpy as np
import sentencepiece as spm
import soxr

from .assets import load_upstream

RATE = 24000
TAIL = b"\0" * (int(RATE * .6) * 2)


class Engine:
    def __init__(self, root: Path, voice="Ava", threads=3):
        upstream = load_upstream(root)

        class StreamingRuntime(upstream.OrtCpuRuntime):
            def _create_sessions(self):
                tts, codec = self.tts_meta_path.parent, self.codec_meta_path.parent
                return {
                    "prefill": self._session(tts / self.tts_meta["files"]["prefill"]),
                    "decode": self._session(tts / self.tts_meta["files"]["decode_step"]),
                    "local_fixed_sampled_frame": self._session(tts / self.tts_meta["files"]["local_fixed_sampled_frame"]),
                    "codec_decode_step": self._session(codec / self.codec_meta["files"]["decode_step"]),
                }

        self.runtime = StreamingRuntime(root / "models", thread_count=threads, max_new_frames=375,
                                        sample_mode="fixed")
        self.tokenizer = spm.SentencePieceProcessor(model_file=str(self.runtime.resolve_manifest_relative_path(
            self.runtime.manifest["model_files"]["tokenizer_model"])))
        self.voice = voice
        self.prompt = next(row["prompt_audio_codes"] for row in self.runtime.list_builtin_voices() if row["voice"] == voice)

    def split(self, text):
        """Keep words together and give each generation at most 75 text tokens."""
        parts, part = [], ""
        for word in text.split():
            candidate = (part + " " + word).strip()
            if len(self.tokenizer.encode(candidate)) > 75:
                if not part or len(self.tokenizer.encode(word)) > 75:
                    raise ValueError("A single word exceeds the model's token budget")
                parts.append(part)
                part = word
            else:
                part = candidate
        if part:
            parts.append(part)
        return parts

    async def stream(self, text):
        loop = asyncio.get_running_loop()
        events = asyncio.Queue()
        cancelled = threading.Event()

        def generate():
            try:
                decoder = self.runtime.codec_streaming_session
                resample = soxr.ResampleStream(48000, RATE, 1, dtype="float32", quality="HQ")

                def emit(samples):
                    if cancelled.is_set():
                        raise InterruptedError("Client disconnected")
                    if len(samples):
                        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
                        loop.call_soon_threadsafe(events.put_nowait, pcm)

                parts = self.split(text)
                for index, part in enumerate(parts):
                    decoder.reset()
                    pending, first = [], True

                    def decode(force=False):
                        nonlocal first
                        if not pending or (not force and len(pending) < (1 if first else 2)):
                            return
                        decoded = decoder.run_frames(pending[:])
                        pending.clear()
                        if decoded is not None:
                            samples, length = decoded
                            emit(resample.resample_chunk(np.asarray(samples[0, :, :length].mean(axis=0), dtype=np.float32)))
                            first = False

                    def on_frame(_frames, _step, frame):
                        if cancelled.is_set():
                            raise InterruptedError("Client disconnected")
                        pending.append(frame)
                        decode()

                    try:
                        rows = self.runtime.build_voice_clone_request_rows(self.prompt, self.tokenizer.encode(part))
                        frames = self.runtime.generate_audio_frames(rows, on_frame=on_frame)
                        if not frames or len(frames) >= 375:
                            raise RuntimeError("Synthesis was empty or reached its frame limit")
                        decode(force=True)
                    finally:
                        decoder.reset()
                    if index < len(parts) - 1:
                        emit(np.zeros(int(RATE * .24), dtype=np.float32))
                emit(resample.resample_chunk(np.empty(0, dtype=np.float32), last=True))
            except Exception as error:
                loop.call_soon_threadsafe(events.put_nowait, error)
            finally:
                loop.call_soon_threadsafe(events.put_nowait, None)

        worker = asyncio.create_task(asyncio.to_thread(generate))
        try:
            while (event := await events.get()) is not None:
                if isinstance(event, Exception):
                    raise event
                yield event
        finally:
            cancelled.set()
            await worker
