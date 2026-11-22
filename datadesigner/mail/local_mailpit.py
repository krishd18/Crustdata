"""Local Mailpit stand-in for environments without Docker/Mailpit: SMTP on :1025 (aiosmtpd) + the subset of
Mailpit's HTTP API used by Data Designer (GET /api/v1/search?query=message-id:<id>, /api/v1/messages,
DELETE /api/v1/messages) on :8025. Messages persist in a SQLite file so counts survive kills.
Run: python -m datadesigner.mail.local_mailpit [--smtp 1025 --http 8025 --db data/mailpit.sqlite]"""
from __future__ import annotations

import argparse
import email
import json
import sqlite3
import threading
import time
from email import policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from aiosmtpd.controller import Controller


class Store:
    def __init__(self, path: str):
        self.c = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.c.execute("CREATE TABLE IF NOT EXISTS m(id INTEGER PRIMARY KEY, message_id TEXT, subject TEXT, rcpt TEXT, raw BLOB, at REAL)")
        self.lock = threading.Lock()

    def add(self, raw: bytes, rcpts: list[str]) -> None:
        msg = email.message_from_bytes(raw, policy=policy.default)
        with self.lock:
            self.c.execute("INSERT INTO m(message_id,subject,rcpt,raw,at) VALUES(?,?,?,?,?)",
                           ((msg["Message-ID"] or "").strip().strip("<>"), msg["Subject"] or "", ",".join(rcpts), raw, time.time()))

    def search(self, mid: str) -> list[dict]:
        with self.lock:
            rows = self.c.execute("SELECT id,message_id,subject,rcpt FROM m WHERE message_id=?", (mid.strip("<>"),)).fetchall()
        return [{"ID": str(r[0]), "MessageID": r[1], "Subject": r[2], "To": r[3]} for r in rows]

    def all(self) -> list[dict]:
        with self.lock:
            rows = self.c.execute("SELECT id,message_id,subject,rcpt FROM m ORDER BY id").fetchall()
        return [{"ID": str(r[0]), "MessageID": r[1], "Subject": r[2], "To": r[3]} for r in rows]

    def clear(self) -> None:
        with self.lock:
            self.c.execute("DELETE FROM m")


class Handler:
    def __init__(self, store: Store):
        self.store = store

    async def handle_DATA(self, server, session, envelope):  # noqa: N802
        self.store.add(envelope.original_content or envelope.content, list(envelope.rcpt_tos))
        return "250 Message accepted for delivery"


def http_handler(store: Store):
    class H(BaseHTTPRequestHandler):
        def _send(self, obj, code=200):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            if u.path == "/api/v1/search":
                q = parse_qs(u.query).get("query", [""])[0]
                msgs = store.search(q.split(":", 1)[1]) if q.startswith("message-id:") else []
                return self._send({"messages_count": len(msgs), "messages": msgs})
            if u.path == "/api/v1/messages":
                msgs = store.all()
                return self._send({"messages_count": len(msgs), "total": len(msgs), "messages": msgs})
            self._send({"error": "not found"}, 404)

        def do_DELETE(self):  # noqa: N802
            store.clear()
            self._send({"ok": True})

        def log_message(self, *a):
            pass
    return H


def serve(smtp_port: int = 1025, http_port: int = 8025, db: str = "data/mailpit.sqlite"):
    import pathlib
    pathlib.Path(db).parent.mkdir(parents=True, exist_ok=True)
    store = Store(db)
    ctl = Controller(Handler(store), hostname="127.0.0.1", port=smtp_port)
    ctl.start()
    httpd = ThreadingHTTPServer(("127.0.0.1", http_port), http_handler(store))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return ctl, httpd


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--smtp", type=int, default=1025)
    ap.add_argument("--http", type=int, default=8025)
    ap.add_argument("--db", default="data/mailpit.sqlite")
    a = ap.parse_args()
    serve(a.smtp, a.http, a.db)
    print(f"local mailpit: smtp 127.0.0.1:{a.smtp} · api http://127.0.0.1:{a.http}", flush=True)
    while True:
        time.sleep(3600)
