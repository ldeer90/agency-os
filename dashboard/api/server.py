#!/usr/bin/env python3
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from urllib.parse import parse_qs, urlparse

from .data import dashboard_payload
from .sync_ops import SyncValidationError, command_state, handle_post_payload, sync_payload


class DashboardHandler(BaseHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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
        if parsed.path == "/api/syncs":
            self.respond(sync_payload())
            return
        if parsed.path.startswith("/api/syncs/commands/"):
            command_id = parsed.path.rsplit("/", 1)[-1]
            try:
                self.respond(command_state(command_id))
            except SyncValidationError as exc:
                self.respond({"error": str(exc)}, status=404)
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

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/syncs/commands":
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise SyncValidationError("Request body must be a JSON object")
            self.respond(handle_post_payload(payload), status=202)
        except SyncValidationError as exc:
            self.respond({"error": str(exc)}, status=400)
        except json.JSONDecodeError:
            self.respond({"error": "Request body must be valid JSON"}, status=400)
        except Exception as exc:
            self.respond({"error": "Could not queue sync command.", "reason": type(exc).__name__}, status=500)

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
    port = int(os.environ.get("DASHBOARD_API_PORT", "8787"))
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    print(f"Agency Health Dashboard API listening on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
