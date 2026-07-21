#!/usr/bin/env python3
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

DEFAULT_HUB_HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>本地分析平台</title><style>
*{box-sizing:border-box}body{margin:0;background:#eef2f5;color:#162033;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}header{min-height:64px;background:#20252d;color:#fff;display:flex;align-items:center;justify-content:space-between;padding:10px 22px;gap:15px}h1{font-size:20px;margin:0;white-space:nowrap}.tabs{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}button,a.btn{border:0;border-radius:8px;background:#edf3f7;color:#1b4050;padding:10px 14px;cursor:pointer;text-decoration:none;font-size:14px}button.active{background:#2d7d9a;color:#fff}main{height:calc(100vh - 64px);display:grid;grid-template-rows:auto 1fr}.bar{display:flex;gap:10px;align-items:center;justify-content:space-between;padding:12px 16px;background:#fff;border-bottom:1px solid #d7dee8}.hint{color:#677485;font-size:13px}.links{display:none;padding:16px;background:#fff;border-bottom:1px solid #d7dee8}.links a{display:inline-flex;margin:4px 8px 4px 0}.warn{display:none;color:#9a3412;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:10px;margin-left:12px;font-size:13px}iframe{width:100%;height:100%;border:0;background:#fff}@media(max-width:760px){header{align-items:flex-start;flex-direction:column}.tabs{justify-content:flex-start}main{height:calc(100vh - 116px)}}
</style></head><body><header><h1>本地分析平台</h1><div class="tabs"><button data-key="credit">征信分析</button><button data-key="flow">流水统计</button><button data-key="financial">财务报表分析</button><button data-key="comprehensive">综合分析</button></div></header><main><div class="bar"><div><span class="hint" id="hint"></span><span class="warn" id="warn">如果内嵌页面空白，请点右侧“新窗口打开”。</span></div><a class="btn" id="openNew" target="_blank">新窗口打开</a></div><div class="links" id="links"></div><iframe id="frame"></iframe></main><script>
const items={credit:{name:'征信分析',url:'http://127.0.0.1:8789/'},flow:{name:'流水统计',url:'http://127.0.0.1:8790/flow'},financial:{name:'财务报表分析',url:'http://127.0.0.1:8793/financial'},comprehensive:{name:'综合分析',url:'http://127.0.0.1:8792/comprehensive'}},frame=document.getElementById('frame'),hint=document.getElementById('hint'),openNew=document.getElementById('openNew'),links=document.getElementById('links'),warn=document.getElementById('warn');links.innerHTML=Object.values(items).map(x=>`<a class="btn" target="_blank" href="${x.url}">${x.name}</a>`).join('');function show(key){const x=items[key]||items.credit;frame.src=x.url;openNew.href=x.url;hint.textContent='当前：'+x.name;document.querySelectorAll('[data-key]').forEach(b=>b.classList.toggle('active',b.dataset.key===key));localStorage.setItem('analysisPlatformTab',key);setTimeout(()=>{warn.style.display='inline-block';links.style.display='block'},2500)}document.querySelectorAll('[data-key]').forEach(b=>b.onclick=()=>show(b.dataset.key));show(items[localStorage.getItem('analysisPlatformTab')]?localStorage.getItem('analysisPlatformTab'):'credit');
</script></body></html>""".encode("utf-8")


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
