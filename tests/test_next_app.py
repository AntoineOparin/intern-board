"""The Svelte build is served at /next/ next to the old frontend at / (docs/svelte-migration.md)."""

import asyncio
import unittest

from board.main import app


def get(path: str) -> tuple[int, dict[str, str], str]:
    """A GET straight through the ASGI app. No lifespan runs, so the database isn't touched."""
    sent: list[dict] = []
    requested = False

    async def receive():
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()  # the client never disconnects; middleware waits on this

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": b"", "headers": [(b"host", b"testserver")],
             "client": ("127.0.0.1", 1), "server": ("testserver", 80), "root_path": ""}
    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = {k.decode(): v.decode() for k, v in start["headers"]}
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], headers, body.decode(errors="replace")


class NextAppTest(unittest.TestCase):
    def test_new_frontend_is_served_at_next(self):
        status, headers, body = get("/next/")
        self.assertEqual(status, 200)
        self.assertIn('<div id="app">', body)
        self.assertEqual(headers["cache-control"], "no-cache")

    def test_next_without_slash_redirects(self):
        status, headers, _ = get("/next")
        self.assertEqual(status, 307)
        self.assertEqual(headers["location"], "/next/")

    def test_old_frontend_still_at_root(self):
        status, _, body = get("/")
        self.assertEqual(status, 200)
        self.assertIn('<script src="app.js"></script>', body)


if __name__ == "__main__":
    unittest.main()
