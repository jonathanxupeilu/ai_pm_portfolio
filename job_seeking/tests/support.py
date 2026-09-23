"""测试底座：把 store 的真实数据路径重定向到 tmp，并提供驱动 CLI 的助手。

用法：在 `test_*.py` 里**先** `from support import PipelineTestCase, ...`，
**再** import 被测脚本——support 负责把 `scripts/` 放进 sys.path。

真实 `pool/`、`ledger.csv`、`shortlists/` 在磁盘上只有一份、没有备份，
所以每个测试都必须走这里，绝不能让测试碰到真实路径。
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import pathlib
import sys
import tempfile
import unittest

JOB_SEEKING = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(JOB_SEEKING / "scripts"))

import store  # noqa: E402

REDIRECTED = ("ROOT", "POOL_PATH", "LEDGER_PATH", "CONFIG_PATH", "CRITERIA_PATH",
              "SHORTLIST_DIR")

# 刻意只放两个词：分数算出来是整数，断言好读（大模型 3 + RAG 2，总权重 5）。
CRITERIA_SAMPLE = """# 测试用打分口径（不是真实 criteria.md）

| 关键词 | 权重 |
|---|---|
| 大模型 | 3 |
| RAG | 2 |
"""

JD_MARKER = "本句只应存在于网页里，不该被写进池子"


def page_with_jd(text: str) -> str:
    return (
        "<html><head><title>某岗位页</title></head><body>"
        f'<dd data-selector="job-intro-content">{text}</dd>'
        "</body></html>"
    )


PLACEHOLDER_PAGE = (
    "<html><head><title>提示</title></head><body>"
    "此页面似乎不存在，4 秒后跳转首页"
    "</body></html>"
)


class FakeResponse:
    """冒充 urllib 的响应对象，只实现 score.py 用到的那两下。"""

    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class PipelineTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        (self.root / "pool").mkdir()
        self._saved = {k: getattr(store, k) for k in REDIRECTED}
        store.ROOT = self.root
        store.POOL_PATH = self.root / "pool" / "jobs.csv"
        store.LEDGER_PATH = self.root / "ledger.csv"
        store.SHORTLIST_DIR = self.root / "shortlists"
        store.CONFIG_PATH = self.root / "config.json"
        store.CRITERIA_PATH = self.root / "criteria.md"
        self.write_config()
        store.CRITERIA_PATH.write_text(CRITERIA_SAMPLE, encoding="utf-8")

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(store, k, v)   # 不还原会污染同进程里的其它测试
        self._tmp.cleanup()

    def write_config(self, **overrides) -> None:
        cfg = {"matcher": "keyword", "keywords": ["AI产品经理"], "cities": ["上海"],
               "pages_per_query": 1, "max_per_round": 15}
        cfg.update(overrides)
        store.CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    def write_pool(self, rows: list[dict]) -> None:
        store.save_pool([{**{f: "" for f in store.POOL_FIELDS}, **r} for r in rows])

    def read_pool(self) -> list[dict]:
        return store.load_pool()

    def write_shortlist(self, rows: list[dict], name: str = "shortlist.csv"):
        path = self.root / name
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=store.SHORTLIST_FIELDS)
            writer.writeheader()
            for i, r in enumerate(rows, 1):
                writer.writerow({**{f: "" for f in store.SHORTLIST_FIELDS},
                                 "jobId": str(i), **r})
        return path

    def ledger_row(self, job_id: str, **overrides) -> None:
        store.append_row(store.LEDGER_PATH, store.LEDGER_FIELDS, {
            **{f: "" for f in store.LEDGER_FIELDS},
            "jobId": job_id, "jobKind": "2", "jobName": "已投岗位",
            "company": "已投公司", "applyTime": "2026-09-23 10:00:00",
            "status": "成功", **overrides,
        })

    def run_cli(self, module, argv: list[str]) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = module.main(argv)
        return rc, buf.getvalue()

    def current_fp(self) -> str:
        import matcher
        return matcher.fingerprint("keyword", store.CRITERIA_PATH)

    def scored_row(self, job_id: str = "1", score: str = "50", **overrides) -> dict:
        """一行「已按当前口径打过分」的池记录。"""
        return {"jobId": job_id, "jobType": "2", "jobName": f"岗位{job_id}",
                "company": "某公司", "score": score, "criteriaFp": self.current_fp(),
                "jobDetailUrl": f"https://example.invalid/{job_id}", **overrides}
