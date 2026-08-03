#!/usr/bin/env python3
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote


DEFAULT_HUB_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>本地分析平台</title>
  <style>
    *{box-sizing:border-box}
    body{margin:0;background:#eef2f5;color:#172033;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;line-height:1.5}
    header{background:#172232;color:#fff;padding:24px}
    header h1{font-size:24px;margin:0 0 6px}
    header p{color:#c7d1df;margin:0;font-size:14px}
    main{max-width:1120px;margin:0 auto;padding:24px}
    .notice{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;border-radius:12px;padding:12px 14px;margin-bottom:18px}
    .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
    .card{display:block;background:#fff;border:1px solid #d8dee8;border-radius:14px;padding:20px;text-decoration:none;color:#172033;box-shadow:0 10px 24px rgba(20,30,45,.08)}
    .card:hover{border-color:#2d7d9a;transform:translateY(-1px)}
    .card h2{font-size:20px;margin:0 0 8px}
    .card p{margin:0;color:#66758a;font-size:14px}
    .url{margin-top:14px;color:#2d7d9a;font-size:13px;word-break:break-all}
    .footer{margin-top:18px;color:#66758a;font-size:13px}
    @media(max-width:760px){.grid{grid-template-columns:1fr}header,main{padding:18px}}
    :root{--glass:rgba(255,255,255,.10);--glass2:rgba(255,255,255,.06);--neon:#70e7ff;--violet:#bd7cff;--text:#edf7ff;--muted:#a9bad2}
    body{min-height:100vh;background:
      radial-gradient(circle at 18% 12%,rgba(112,231,255,.36),transparent 30%),
      radial-gradient(circle at 82% 18%,rgba(189,124,255,.30),transparent 30%),
      linear-gradient(135deg,#0b1328,#15244a 58%,#080d1c);color:var(--text);overflow-x:hidden}
    body:before{content:"";position:fixed;inset:0;pointer-events:none;background:
      linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),
      linear-gradient(90deg,rgba(255,255,255,.028) 1px,transparent 1px);background-size:42px 42px;mask-image:radial-gradient(circle at 50% 20%,#000,transparent 75%)}
    header{margin:22px auto 0;max-width:1120px;border:1px solid rgba(255,255,255,.18);border-radius:28px;background:linear-gradient(135deg,rgba(255,255,255,.13),rgba(255,255,255,.055));backdrop-filter:blur(22px);box-shadow:0 28px 80px rgba(0,0,0,.25)}
    header h1{font-size:30px;letter-spacing:.03em}header p,.footer,.card p{color:var(--muted)}
    main{position:relative}
    .notice{background:rgba(255,255,255,.08);border:1px solid rgba(112,231,255,.22);color:#dff8ff;border-radius:18px;backdrop-filter:blur(16px)}
    .card{background:linear-gradient(145deg,var(--glass),var(--glass2));border:1px solid rgba(255,255,255,.18);border-radius:24px;color:var(--text);box-shadow:0 24px 70px rgba(0,0,0,.22);backdrop-filter:blur(20px);transition:.2s ease}
    .card:hover{border-color:rgba(112,231,255,.58);transform:translateY(-4px);box-shadow:0 28px 88px rgba(42,188,255,.18)}
    .card h2{font-size:23px}.url{color:#9cf2ff}
  </style>
</head>
<body>
  <header>
    <h1>本地分析平台</h1>
    <p>这里是总入口。点击下面任一模块，会直接进入对应平台，不再内嵌显示，避免白屏或页面错位。</p>
  </header>
  <main>
    <div class="notice">如果某个模块打不开，等 30 秒后刷新一次；后台守护会自动检查并拉起服务。</div>
    <div class="grid">
      <a class="card" href="http://127.0.0.1:8789/">
        <h2>征信分析</h2>
        <p>个人/企业征信、PDF/图片识别、报告下载。</p>
        <div class="url">http://127.0.0.1:8789/</div>
      </a>
      <a class="card" href="http://127.0.0.1:8790/flow">
        <h2>流水统计</h2>
        <p>银行流水、微信/支付宝、PDF/Excel/图片识别和统计。</p>
        <div class="url">http://127.0.0.1:8790/flow</div>
      </a>
      <a class="card" href="http://127.0.0.1:8793/financial">
        <h2>财务报表分析</h2>
        <p>PDF/Excel 财报识别，结合行业和经营情况分析。</p>
        <div class="url">http://127.0.0.1:8793/financial</div>
      </a>
      <a class="card" href="http://127.0.0.1:8792/comprehensive">
        <h2>综合分析</h2>
        <p>选择客户文件夹，自动分类征信和流水并生成综合报告。</p>
        <div class="url">http://127.0.0.1:8792/comprehensive</div>
      </a>
    </div>
    <div class="footer">提示：这些链接只在本机使用，发给其他电脑不能直接打开。</div>
  </main>
</body>
</html>""".encode("utf-8")


class HubHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = unquote(self.path.split("?", 1)[0])
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path not in {"/", "/index.html", "/本地分析平台.html"}:
            self.send_error(404)
            return

        content = DEFAULT_HUB_HTML
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_HEAD(self):
        path = unquote(self.path.split("?", 1)[0])
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path not in {"/", "/index.html", "/本地分析平台.html"}:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8791"))
    server = ThreadingHTTPServer(("127.0.0.1", port), HubHandler)
    print(f"本地分析平台统一入口：http://127.0.0.1:{port}/", flush=True)
    server.serve_forever()
