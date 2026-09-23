"""假猎聘 MCP：只绑 127.0.0.1，按脚本的期望回 SSE 帧。

为什么必须回 SSE（`data:` 行）而不是裸 JSON：`resume._rpc` 是按 SSE 解析的，
服务端要是总回裸 JSON，那条解析路径就永远没被测到——线上才会第一次走。
"""
from __future__ import annotations

import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FAKE_TOKEN = "fake-token-for-tests-never-real"
RESUME_BODY = "## 基本信息\n姓名：测试\n\n## 工作经历\n某公司 AI 产品经理\n"


class Call:
    """一次被收到的请求，给断言用。"""

    def __init__(self, body: dict, headers):
        self.body = body
        self.token = headers.get("x-user-token")
        self.method = body.get("method")
        self.params = body.get("params") or {}


def mcp_envelope(*, err_code=0, result=RESUME_BODY, tool_name="my-resume") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{
                "type": "text",
                "text": json.dumps(
                    {"data": {"result": result}, "errCode": err_code},
                    ensure_ascii=False,
                ),
            }],
        },
    }


class FakeMCP:
    def __init__(self, handler_mode: str = "ok"):
        """handler_mode: ok | raw_json | errcode | empty_result | http500 |
        bad_json | jsonrpc_error

        `mode` 是**可读属性**，测试可以在构造后改它（一个服务实例跑多种响应形状，
        不用重开端口）。
        """
        self.mode = handler_mode
        self.calls: list[Call] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):       # 别把噪声打到测试输出里
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8")
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    body = {"_raw": raw}
                outer.calls.append(Call(body, self.headers))

                if outer.mode == "http500":
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"boom")
                    return

                if outer.mode == "errcode":
                    payload = mcp_envelope(err_code=43001)
                elif outer.mode == "empty_result":
                    payload = mcp_envelope(result="   ")
                elif outer.mode == "jsonrpc_error":
                    payload = {"jsonrpc": "2.0", "id": 1,
                               "error": {"code": -32601, "message": "tool not found"}}
                else:
                    payload = mcp_envelope()

                text = json.dumps(payload, ensure_ascii=False)
                if outer.mode == "bad_json":
                    text = "{坏"

                if outer.mode == "raw_json":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(text.encode("utf-8"))
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(f"event: message\ndata: {text}\n\n".encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    @property
    def last(self) -> Call:
        assert self.calls, "假 MCP 一个请求都没收到——脚本没走网络？"
        return self.calls[-1]


def write_config(tmp_path: pathlib.Path, url: str,
                 token: str = FAKE_TOKEN) -> pathlib.Path:
    """造一份指向假服务的 mcp.json。真配置一个字节都不读。"""
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps({
        "mcpServers": {
            "liepin-mcp": {"url": url, "headers": {"x-user-token": token}}
        }
    }, ensure_ascii=False), encoding="utf-8")
    return p
