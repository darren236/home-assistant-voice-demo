"""Check the actual HTTP/PCM contract, including truncated phone responses."""
import asyncio
from contextlib import aclosing
import unittest

from bedside_voice.phone import stream


class PhoneProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def render(self, fingerprint="test", finish=True):
        async def handle(reader, writer):
            try:
                headers = await reader.readuntil(b"\r\n\r\n")
                self.assertIn(b"Authorization: Bearer private-test-token", headers)
                length = int(next(line.split(b":", 1)[1] for line in headers.split(b"\r\n")
                                  if line.lower().startswith(b"content-length:")))
                await reader.readexactly(length)
                writer.write(("HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n"
                              f"X-Bedside-Model: {fingerprint}\r\nX-Audio-Rate: 48000\r\n\r\n").encode())
                pcm = b"\x00\x08" * 48000
                writer.write(f"{len(pcm):x}\r\n".encode() + pcm + b"\r\n")
                if finish:
                    writer.write(b"0\r\n\r\n")
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        config = {"port": server.sockets[0].getsockname()[1], "token": "private-test-token", "fingerprint": "test"}
        return server, config

    async def test_completed_native_pcm_is_resampled_to_24khz(self):
        server, config = await self.render()
        async with server, aclosing(stream(config, [1, 2])) as chunks:
            output = b"".join([chunk async for chunk in chunks])
        self.assertEqual(len(output), 24000 * 2)

    async def test_wrong_model_is_rejected_before_audio(self):
        server, config = await self.render(fingerprint="different-model")
        async with server, aclosing(stream(config, [1])) as chunks:
            with self.assertRaisesRegex(RuntimeError, "model mismatch"):
                await anext(chunks)

    async def test_missing_completion_reports_error_after_partial_pcm(self):
        server, config = await self.render(finish=False)
        output = []
        async with server, aclosing(stream(config, [1])) as chunks:
            with self.assertRaisesRegex(RuntimeError, "before completing"):
                async for chunk in chunks:
                    output.append(chunk)
        self.assertTrue(output)


if __name__ == "__main__":
    unittest.main()
