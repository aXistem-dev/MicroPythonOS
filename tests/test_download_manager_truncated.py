"""
test_download_manager_truncated.py - a connection that ends before Content-Length
bytes arrived is resumed with a Range request, or fails; it is never a success.
"""

import unittest
import os
import sys

# Import the module under test
sys.path.insert(0, '../internal_filesystem/lib')
from mpos.net.download_manager import DownloadManager
from mpos.testing.mocks import MockDownloadManager


class TestTruncatedDownload(unittest.TestCase):
    """A server that closes the connection before Content-Length bytes arrived must not
    produce a "successful" download: an app installed from it would be missing files."""

    def _run(self, body, content_length, range_status=None, range_body=b""):
        import asyncio
        import sys

        requests = []

        class _Content:
            def __init__(self, data):
                self.data = data

            async def read(self, n):
                out, self.data = self.data[:n], self.data[n:]
                return out

        class _Response:
            def __init__(self, status, headers, data):
                self.status = status
                self.headers = headers
                self.content = _Content(data)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class _Session:
            def get(self, url, headers=None, **kw):
                requests.append(dict(headers or {}))
                if "Range" in (headers or {}):
                    return _Response(range_status or 200, {}, range_body)
                return _Response(200, {"Content-Length": str(content_length)}, body)

            async def close(self):
                pass

        class _FakeAiohttp:
            pass

        fake = _FakeAiohttp()
        fake.ClientSession = _Session
        old = sys.modules.get("aiohttp")
        sys.modules["aiohttp"] = fake
        got = []

        async def _cb(chunk):
            got.append(chunk)

        try:
            async def _go():
                return await DownloadManager._download_url_async("http://host/app.mpk",
                                                                  chunk_callback=_cb)
            try:
                result = asyncio.run(_go())
            except Exception as e:
                result = e
        finally:
            if old is None:
                del sys.modules["aiohttp"]
            else:
                sys.modules["aiohttp"] = old
        return result, b"".join(got), requests

    def test_short_body_without_resume_support_is_an_error(self):
        result, data, requests = self._run(b"abcd", 10)
        self.assertTrue(isinstance(result, Exception), result)
        self.assertEqual(requests[-1].get("Range"), "bytes=4-")

    def test_short_body_is_resumed_with_a_range_request(self):
        result, data, requests = self._run(b"abcd", 10, range_status=206, range_body=b"efghij")
        self.assertEqual(result, True)
        self.assertEqual(data, b"abcdefghij")

    def test_complete_body_is_success(self):
        result, data, requests = self._run(b"abcdefghij", 10)
        self.assertEqual(result, True)
        self.assertEqual(len(requests), 1)


if __name__ == "__main__":
    unittest.main()
