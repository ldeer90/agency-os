#!/usr/bin/env python3
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs, urlparse

from .data import dashboard_payload


class DashboardHandler(BaseHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.respond({"status": "ok"})
            return
        if parsed.path != "/api/dashboard":
            self.send_response(404)
            self.end_headers()
            return
        try:
            params = parse_qs(parsed.query)
            self.respond(dashboard_payload(force_refresh=params.get("refresh", ["0"])[0] == "1"))
        except Exception as exc:
            self.respond(
                {"error": "Live BigQuery dashboard query failed.", "reason": type(exc).__name__},
                status=503,
            )

    def respond(self, payload: dict, *, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8787), DashboardHandler)
    print("Agency Health Dashboard API listening on http://127.0.0.1:8787")
    server.serve_forever()


if __name__ == "__main__":
    main()
