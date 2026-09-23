"""读猎聘在线简历（my-resume）。本项目唯一的外呼。

  resume.py            把在线简历正文打到 stdout（markdown 文本）

红线：只读。工具名写死成常量，没有任何参数能改它。
真实 MCP 另有 9 个写简历的工具，这个脚本碰不到——不调，也不给入口。

令牌只从 ~/.workbuddy/mcp.json 读：只读、不落盘、不打印、不进 git。
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request

import models

SERVER_NAME = "liepin-mcp"
RESUME_TOOL = "my-resume"
TIMEOUT = 60

DEFAULT_CONFIG_PATH = pathlib.Path("~/.workbuddy/mcp.json").expanduser()
MCP_CONFIG = DEFAULT_CONFIG_PATH


def load_endpoint() -> tuple[str, str]:
    """返回 (url, token)。缺任何一项都停下来报错，不许降级猜测。"""
    if not MCP_CONFIG.exists():
        raise SystemExit(
            f"❌ 找不到 MCP 配置：{MCP_CONFIG}\n"
            f"   本流程从该文件读猎聘令牌，请先确认它存在且已登录。"
        )
    try:
        cfg = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"❌ {MCP_CONFIG} 不是合法 JSON：{e}") from None
    srv = (cfg.get("mcpServers") or {}).get(SERVER_NAME)
    if not isinstance(srv, dict):
        raise SystemExit(f"❌ {MCP_CONFIG} 里没有 mcpServers.{SERVER_NAME}")
    url = srv.get("url")
    token = (srv.get("headers") or {}).get("x-user-token")
    if not url:
        raise SystemExit(f"❌ mcpServers.{SERVER_NAME}.url 为空")
    if not token:
        raise SystemExit(f"❌ mcpServers.{SERVER_NAME}.headers.x-user-token 为空")
    return url, token


def _rpc(method: str, params=None, rid: int = 1) -> dict:
    url, token = load_endpoint()
    body: dict = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "x-user-token": token,          # 只在这里出现，且不落任何日志
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read()[:400].decode("utf-8", "replace")
        raise RuntimeError(f"MCP 返回 HTTP {e.code}：{detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"MCP 连接失败：{e.reason}") from None

    lines = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
    payload = "\n".join(lines) if lines else raw
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        raise RuntimeError(f"MCP 返回无法解析为 JSON：{payload[:300]}") from None


def fetch_resume() -> str:
    """调 my-resume，取出 content[0].text 里的 markdown 正文。

    实测形状：content[0].text 是 JSON
    {"data": {"result": <2745 字 markdown 文本>}, "errCode": 0}。
    errCode 非 0 或 result 为空都算失败——协议成功不等于业务有结论。
    这两条的判断规则在 `models.ResumeEnvelope`，不在这里重写一遍。
    """
    resp = _rpc("tools/call", {"name": RESUME_TOOL, "arguments": {}}, 3)
    if "error" in resp:
        raise RuntimeError(f"MCP 调用 {RESUME_TOOL} 出错：{resp['error']}")
    result = resp.get("result") or {}
    # 下面是 MCP 协议层的剥壳，不是业务规则：拿 content[0].text 那段 JSON 文本。
    text = next((c.get("text") for c in (result.get("content") or [])
                 if c.get("type") == "text"), None)
    if text is None:
        raise RuntimeError(f"{RESUME_TOOL} 的返回里没有 text content")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(f"{RESUME_TOOL} 的 content 不是 JSON：{text[:200]}") from None
    return models.parse_envelope(data).result


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    try:
        sys.stdout.write(fetch_resume())
    except (RuntimeError, models.EnvelopeError) as e:
        print(f"❌ 读在线简历失败：{e}", file=sys.stderr)
        return 1
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
