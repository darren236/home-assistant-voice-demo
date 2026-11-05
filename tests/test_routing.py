"""Exercise the audible failure boundary without models, a phone or Home Assistant."""
from contextlib import aclosing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bedside_voice.engine import TAIL
from bedside_voice.server import Router


class FakeEngine:
    voice = "Ava"
    class tokenizer:
        @staticmethod
        def encode(text):
            return list(range(len(text.split())))

    async def stream(self, text):
        yield b"server"


async def collect(router, text="A reply."):
    async with aclosing(router.stream(text, "phone")) as stream:
        return [chunk async for chunk in stream]


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "phone.json").write_text(json.dumps({"fingerprint": "test", "token": "test", "port": 0}))
        self.router = Router(FakeEngine(), self.root)

    def tearDown(self):
        self.temp.cleanup()

    async def test_failure_before_pcm_uses_server(self):
        async def failed(*args):
            raise OSError("offline")
            yield
        with patch("bedside_voice.server.phone.stream", failed):
            self.assertEqual(await collect(self.router), [b"server", TAIL])
        self.assertEqual(list(self.router.cache.iterdir()), [])

    async def test_partial_answer_is_not_restarted_or_cached(self):
        async def failed(*args):
            yield b"first word"
            raise OSError("lost connection")
        chunks = []
        with patch("bedside_voice.server.phone.stream", failed):
            with self.assertRaises(OSError):
                async for chunk in self.router.stream("A reply.", "phone"):
                    chunks.append(chunk)
        self.assertEqual(chunks, [b"first word"])
        self.assertEqual(list(self.router.cache.iterdir()), [])

    async def test_completed_phone_audio_is_reused_without_contacting_phone(self):
        async def rendered(*args):
            yield b"phone"
        with patch("bedside_voice.server.phone.stream", rendered):
            self.assertEqual(await collect(self.router), [b"phone", TAIL])
        with patch("bedside_voice.server.phone.stream", side_effect=AssertionError("cache should bypass phone")):
            self.assertEqual(b"".join(await collect(self.router)), b"phone" + TAIL)

    async def test_long_reply_uses_server(self):
        with patch("bedside_voice.server.phone.stream", side_effect=AssertionError("too long for phone")):
            self.assertEqual(await collect(self.router, "word " * 76), [b"server", TAIL])


if __name__ == "__main__":
    unittest.main()
