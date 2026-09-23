#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""猎聘 MCP 客户端（共享模块，不是给人直接跑的主流程）。

令牌只从 ~/.workbuddy/mcp.json 读，**绝不打印、绝不复制、绝不落盘、绝不进 git**。
配置缺失一律显式报错，不做降级猜测。

单独运行可自检：  liepin.py --probe
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

MCP_CONFIG = pathlib.Path(os.path.expanduser("~/.workbuddy/mcp.json"))
SERVER_NAME = "liepin-mcp"
SEARCH_TOOL = "user-search-job"
APPLY_TOOL = "user-apply-job"
TIMEOUT = 60


def load_endpoint() -> tuple[str, str]:
    """返回 (url, token)。缺任何一项都停下来报错。"""
    if not MCP_CONFIG.exists():
        raise SystemExit(
            f"❌ 找不到 MCP 配置：{MCP_CONFIG}\n"
            f"   本流程从该文件读猎聘令牌，请先确认它存在且已登录。"
        )
    try:
        cfg = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"❌ {MCP_CONFIG} 不是合法 JSON：{e}")

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

    # 服务端走 SSE 风格，正文在 data: 行里
    lines = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
    payload = "\n".join(lines) if lines else raw
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        raise RuntimeError(f"MCP 返回无法解析为 JSON：{payload[:300]}") from None


def list_tools() -> list[dict]:
    resp = _rpc("tools/list", {}, 2)
    return (resp.get("result") or {}).get("tools") or []


def call_tool(name: str, arguments: dict) -> dict:
    """调工具并把 content[0].text 里的 JSON 解出来。"""
    resp = _rpc("tools/call", {"name": name, "arguments": arguments}, 3)
    if "error" in resp:
        raise RuntimeError(f"MCP 调用 {name} 出错：{resp['error']}")
    result = resp.get("result") or {}
    for c in result.get("content") or []:
        if c.get("type") == "text":
            txt = c["text"]
            try:
                return json.loads(txt)
            except json.JSONDecodeError:
                raise RuntimeError(f"{name} 的 content 不是 JSON：{txt[:300]}") from None
    raise RuntimeError(
        f"{name} 的返回里没有 text content：{json.dumps(result, ensure_ascii=False)[:300]}"
    )


def search_jobs(job_name: str, address: str = "", page: int = 0, **filters) -> list[dict]:
    """按关键词搜岗。page 从 0 开始（0 = 第 1 页），每页 20 条。"""
    args: dict = {"jobName": job_name, "page": page}
    if address:
        args["address"] = address
    for k, v in filters.items():
        if v not in (None, ""):
            args[k] = v
    data = call_tool(SEARCH_TOOL, args)
    return ((data or {}).get("data") or {}).get("list") or []


def apply_job(job_id: int, job_kind: str) -> dict:
    """投递。jobKind 必须来自搜索结果的 jobType，不要自行推导。"""
    return call_tool(APPLY_TOOL, {"jobId": job_id, "jobKind": job_kind})


def _probe() -> int:
    tools = list_tools()
    print(f"✅ MCP 通道可用  配置：{MCP_CONFIG}")
    print(f"   工具共 {len(tools)} 个：")
    for t in tools:
        print(f"     - {t.get('name')}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("用法： liepin.py --probe")
        return 0
    if argv[0] == "--probe":
        return _probe()
    print(f"未知参数：{argv[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
