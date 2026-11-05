"""Authenticated loopback phone stream; adb/SSH forwarding supplies the transport."""
import asyncio
import json

import numpy as np
import soxr


async def request(config, method, path, body=None):
    reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", config["port"]), 1)
    payload = json.dumps(body).encode() if body is not None else b""
    writer.write((f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n"
                  f"Authorization: Bearer {config['token']}\r\nContent-Length: {len(payload)}\r\n"
                  "Content-Type: application/json\r\nConnection: close\r\n\r\n").encode() + payload)
    try:
        await asyncio.wait_for(writer.drain(), 5)
        status = await asyncio.wait_for(reader.readline(), 5)
        if b" 200 " not in status:
            raise RuntimeError("Phone rejected the request")
        headers = {}
        for _ in range(30):
            line = await asyncio.wait_for(reader.readline(), 5)
            if line == b"\r\n":
                return reader, writer, headers
            name, value = line.decode().split(":", 1)
            headers[name.lower()] = value.strip()
        raise RuntimeError("Invalid phone response headers")
    except BaseException:
        writer.close()
        await writer.wait_closed()
        raise


async def health(config):
    reader, writer, headers = await request(config, "GET", "/health")
    try:
        length = int(headers["content-length"])
        if not 0 < length <= 4096:
            raise RuntimeError("Invalid phone health response")
        return json.loads(await asyncio.wait_for(reader.readexactly(length), 5))
    finally:
        writer.close()
        await writer.wait_closed()


async def stream(config, ids):
    reader, writer, headers = await request(config, "POST", "/synthesize", {"token_ids": ids, "seed": 7411})
    try:
        if headers.get("x-bedside-model") != config["fingerprint"] or headers.get("x-audio-rate") != "48000":
            raise RuntimeError("Phone model mismatch; provision this model bundle again")
        resample = soxr.ResampleStream(48000, 24000, 1, dtype="float32", quality="HQ")
        while True:
            line = await asyncio.wait_for(reader.readline(), 5)
            if not line:
                raise RuntimeError("Phone disconnected before completing speech")
            size = int(line.strip(), 16)
            if size == 0:
                if await asyncio.wait_for(reader.readexactly(2), 5) != b"\r\n":
                    raise RuntimeError("Invalid final phone chunk")
                break
            if not 0 < size <= 1_000_000 or size % 2:
                raise RuntimeError("Invalid PCM chunk size")
            pcm = await asyncio.wait_for(reader.readexactly(size), 5)
            if await asyncio.wait_for(reader.readexactly(2), 5) != b"\r\n":
                raise RuntimeError("Invalid chunk boundary")
            samples = resample.resample_chunk(np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32767)
            if len(samples):
                yield (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
        samples = resample.resample_chunk(np.empty(0, dtype=np.float32), last=True)
        if len(samples):
            yield (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    finally:
        writer.close()
        await writer.wait_closed()
