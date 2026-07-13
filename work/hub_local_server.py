#!/usr/bin/env python3
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HUB_FILE = ROOT / "outputs" / "本地分析平台.html"


class HubHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path not in {"/", "/index.html", "/本地分析平台.html"}:
            self.send_error(404)
            return

        try:
            content = HUB_FILE.read_bytes()
        except OSError as exc:
            self.send_error(500, f"无法读取统一首页：{exc}")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8791"))
    server = ThreadingHTTPServer(("127.0.0.1", port), HubHandler)
    print(f"本地分析平台统一入口：http://127.0.0.1:{port}/", flush=True)
    server.serve_forever()
