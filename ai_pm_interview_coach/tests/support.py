"""测试公共件：跑 CLI 收 (rc, out, err)、造数据行。

数据路径重定向不在这里，在 conftest.py 的 data_dir fixture。
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import tempfile
import unittest.mock


def run_cli(main, argv, stdin_text: str = "") -> tuple[int, str, str]:
    """把 main(argv) 当命令行那样跑一遍，收回调的输出。

    不起子进程：快，且 monkeypatch 生效（起进程只重定向得了环境变量，
    patch 不动模块常量）。真起进程的端到端在 test_e2e.py。
    """
    out, err = io.StringIO(), io.StringIO()
    argv = [str(a) for a in argv]
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            unittest.mock.patch("sys.stdin", io.StringIO(stdin_text)):
        try:
            rc = main(argv)
        except SystemExit as e:
            code = e.code
            rc = code if isinstance(code, int) else (0 if code is None else 1)
    return rc, out.getvalue(), err.getvalue()


def bank_row(question: str = "你怎么定义产品成功指标？", **over) -> dict:
    import store

    row = {
        "id": store.fingerprint(question),
        "question": question,
        "refAnswer": "能从北极星指标往下拆到可观测的埋点。",
        "kind": "通用",
        "target": "",
        "source": "人工录入",
        "addedAt": "2026-09-23",
    }
    row.update(over)
    return row


def attempt_row(qid: str, **over) -> dict:
    row = {
        "at": "2026-09-23T10:00:00+08:00",
        "qid": qid,
        "answer": "我一般先看留存。",
        "verdict": "部分对",
        "feedback": "没说到指标怎么反推需求。",
    }
    row.update(over)
    return row


def write_jsonl(path: pathlib.Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def make_tmp() -> pathlib.Path:
    return pathlib.Path(tempfile.mkdtemp(prefix="coach-tmp-"))
