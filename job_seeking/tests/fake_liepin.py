"""本地假猎聘：MCP 端点（JSON-RPC + SSE 框架）+ 岗位详情页。

**只绑 127.0.0.1，永不外呼。** 集成/端到端测试用它替掉 mock：这样真实跑的是
`liepin._rpc` 的 HTTP 与 SSE 解析、`score.fetch_jd_text` 的 urllib 与正则抽正文，
而不是「函数被调用过」。

夹具里的令牌是 `fake-token-for-tests`——测试**不读也不需要**真实令牌。
"""
from __future__ import annotations

import http.server
import json
import threading
from urllib.parse import urlparse

FAKE_TOKEN = "fake-token-for-tests"

DEFAULT_TOOLS = ["user-search-job", "user-apply-job", "user-job-detail", "user-collect-job",
                 "user-my-resume", "user-apply-list", "search-jobs", "user-job-recommend",
                 "user-company-info", "user-chat-list", "user-send-message",
                 "user-job-filter", "user-industry-list", "user-city-list"]


def is_loopback(url: str) -> bool:
    return (urlparse(url).hostname or "") in ("127.0.0.1", "localhost", "::1")


def write_mcp_config(path, url: str, token: str = FAKE_TOKEN) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "mcpServers": {"liepin-mcp": {"url": url, "headers": {"x-user-token": token}}}
    }, ensure_ascii=False), encoding="utf-8")


def job_row(job_id: int, name: str) -> dict:
    return {"jobId": job_id, "jobType": "2", "jobName": name, "company": f"公司{job_id}",
            "location": "上海", "salary": "30-50k", "education": "本科",
            "workYears": "5-10年", "industry": "互联网", "companyTags": ["大模型"],
            "financingStage": "B轮", "companySize": "500-2000人"}


class FakeLiepin:
    """一个假猎聘。`search_pages` 按页号给结果，`jd_text` 是岗位页正文。"""

    def __init__(self, search_pages: dict | None = None, apply_response: dict | None = None,
                 jd_text: str = "大模型 与 RAG，含评测环节", tools: list[str] | None = None):
        self.search_pages = search_pages if search_pages is not None else {
            0: [job_row(101, "AI产品经理"), job_row(102, "大模型产品经理")],
        }
        self.apply_response = apply_response if apply_response is not None else {"message": "投递成功"}
        self.jd_text = jd_text
        self.tools = tools if tools is not None else list(DEFAULT_TOOLS)
        self.applies: list[tuple] = []      # 收到的 (jobId, jobKind)
        self.calls: list[dict] = []         # 收到的每次 tools/call
        self.last_headers: dict = {}
        self._srv = None
        self._thread = None

    # ---- 地址 ----
    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._srv.server_address[1]}"

    @property
    def mcp_url(self) -> str:
        return f"{self.url}/mcp"

    def job_url(self, job_id) -> str:
        return f"{self.url}/job/{job_id}"

    # ---- 生命周期 ----
    def start(self) -> "FakeLiepin":
        self._srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        # 幂等：dead_url() 会先关一次，测试收尾还会再关一次。
        srv, self._srv = self._srv, None
        if srv is not None:
            srv.shutdown()
            srv.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ---- 协议 ----
    def _make_handler(self):
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):    # 别把访问日志打到测试输出里
                pass

            def _send(self, code: int, body: str, ctype: str) -> None:
                data = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                path = urlparse(self.path).path
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8")
                fake.last_headers = {k.lower(): v for k, v in self.headers.items()}
                if path == "/mcp500":
                    self._send(500, "服务端 500", "text/plain; charset=utf-8")
                    return
                if path == "/mcp-garbage":
                    self._send(200, "这不是 JSON，也不是 SSE", "text/plain; charset=utf-8")
                    return
                request = json.loads(raw)
                response = fake.handle_rpc(request)
                # 服务端真实形态：SSE 风格，正文在 data: 行里
                self._send(200, "data: " + json.dumps(response, ensure_ascii=False) + "\n\n",
                           "text/event-stream; charset=utf-8")

            def do_GET(self):
                path = urlparse(self.path).path
                if path == "/boom":
                    self._send(500, "服务端炸了", "text/plain; charset=utf-8")
                    return
                if path.startswith("/job/"):
                    job_id = path[len("/job/"):]
                    if job_id in fake.known_job_ids():
                        body = (f"<html><head><title>岗位 {job_id}</title></head><body>"
                                f'<dd data-selector="job-intro-content">{fake.jd_text}</dd>'
                                f"</body></html>")
                    else:
                        body = ("<html><head><title>提示</title></head><body>"
                                "此页面似乎不存在</body></html>")
                    self._send(200, body, "text/html; charset=utf-8")
                    return
                self._send(404, "没有这个页面", "text/plain; charset=utf-8")

        return Handler

    def known_job_ids(self) -> set[str]:
        return {str(r["jobId"]) for rows in self.search_pages.values() for r in rows}

    def handle_rpc(self, request: dict) -> dict:
        rid = request.get("id", 1)
        method = request.get("method")
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": rid,
                    "result": {"tools": [{"name": n} for n in self.tools]}}
        if method != "tools/call":
            return {"jsonrpc": "2.0", "id": rid, "error": {"message": f"未知方法 {method}"}}

        params = request.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        self.calls.append({"name": name, "arguments": args})

        if name == "user-search-job":
            page = int(args.get("page", 0))
            rows = [{**r, "jobDetailUrl": self.job_url(r["jobId"])}
                    for r in self.search_pages.get(page, [])]
            payload = {"data": {"list": rows}}
        elif name == "user-apply-job":
            self.applies.append((args.get("jobId"), args.get("jobKind")))
            payload = self.apply_response
        else:
            return {"jsonrpc": "2.0", "id": rid, "error": {"message": f"未知工具 {name}"}}

        return {"jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text",
                                        "text": json.dumps(payload, ensure_ascii=False)}]}}

    def dead_url(self) -> str:
        """拿一个「已经关掉的」端口——用它验证失败路径真的会失败。"""
        port = self._srv.server_address[1]
        self.stop()
        return f"http://127.0.0.1:{port}"
