"""端到端：把整个项目拷到 tmp，用真子进程把 search→score→shortlist→apply 串一遍。

与集成层的区别：这里是**真的 `python scripts/xxx.py`**，每个脚本是独立进程，
模块级状态不共享、退出码真的会传给 shell。所以这条测试证明的是「照着 README 敲命令
能不能跑通」，而集成层证明的是「各脚本内部逻辑对不对」。

隔离靠三件事，都不用改项目代码：
1. `shutil.copytree` 拷贝到 tmp —— `store.ROOT` 由 `__file__` 推导，自然落在副本里；
2. `USERPROFILE`/`HOME` 指向 tmp 家目录 —— `expanduser("~/.workbuddy/mcp.json")` 于是
   读到夹具配置；真实令牌文件全程没被碰过；
3. MCP 端点写成本机假猎聘 —— 全程不出网。
"""
from __future__ import annotations

import csv
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from support import JOB_SEEKING, CRITERIA_SAMPLE

import fake_liepin


def real_bytes(path: pathlib.Path):
    return path.read_bytes() if path.exists() else None


class PipelineE2E(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = pathlib.Path(self._tmp.name)
        self.project = self.base / "job_seeking"
        self.project.mkdir()

        shutil.copytree(JOB_SEEKING / "scripts", self.project / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        # 用固定的小口径，断言才是确定的（真实 criteria.md/config.json 由人维护，会变）
        (self.project / "config.json").write_text(
            '{"matcher": "keyword", "keywords": ["AI产品经理"], "cities": ["上海"],'
            ' "pages_per_query": 1, "max_per_round": 15}',
            encoding="utf-8")
        (self.project / "criteria.md").write_text(CRITERIA_SAMPLE, encoding="utf-8")

        self.home = self.base / "home"
        self.mcp_cfg = self.home / ".workbuddy" / "mcp.json"
        self.server = fake_liepin.FakeLiepin().start()
        self.addCleanup(self.server.stop)
        fake_liepin.write_mcp_config(self.mcp_cfg, self.server.mcp_url)

        self.env = {**os.environ, "PYTHONUTF8": "1",
                    "USERPROFILE": str(self.home), "HOME": str(self.home)}

    # ---- 工具 ----
    def run_script(self, name: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.project / "scripts" / name), *args],
            cwd=str(self.project), env=self.env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=180)

    def out(self, res: subprocess.CompletedProcess) -> str:
        return (res.stdout or "") + (res.stderr or "")

    def pool_rows(self) -> list[dict]:
        with (self.project / "pool" / "jobs.csv").open(encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))

    def shortlist_csv(self) -> pathlib.Path:
        found = sorted((self.project / "shortlists").glob("*.csv"))
        self.assertTrue(found, "没有生成短名单 csv")
        return found[0]

    def assert_endpoint_is_local(self) -> None:
        text = self.mcp_cfg.read_text(encoding="utf-8")
        self.assertIn("127.0.0.1", text, "拒绝向非本机地址投递")

    # ---- 用例 ----
    def test_the_whole_pipeline_runs_and_closes_the_dedupe_loop(self):
        res = self.run_script("search.py", "--pages", "1")
        self.assertEqual(res.returncode, 0, self.out(res))
        self.assertEqual(len(self.pool_rows()), 2)

        res = self.run_script("score.py")
        self.assertEqual(res.returncode, 0, self.out(res))

        res = self.run_script("shortlist.py")
        self.assertEqual(res.returncode, 0, self.out(res))
        header = self.shortlist_csv().read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("jobKind", header)
        self.assertNotIn("jobType", header)

        listing = str(self.shortlist_csv())
        res = self.run_script("apply.py", "--list", listing)
        self.assertEqual(res.returncode, 0, self.out(res))
        self.assertEqual(self.server.applies, [], "dry-run 不得外呼")
        self.assertFalse((self.project / "ledger.csv").exists())

        self.assert_endpoint_is_local()
        res = self.run_script("apply.py", "--list", listing, "--confirm")
        self.assertEqual(res.returncode, 0, self.out(res))
        self.assertEqual(self.server.applies, [(101, "2"), (102, "2")])

        ledger = (self.project / "ledger.csv").read_text(encoding="utf-8")
        self.assertEqual(len(ledger.strip().splitlines()), 3, "表头 + 两行")

        # 闭环：两个岗都已入台账，再出名单必须一个都不给
        res = self.run_script("shortlist.py")
        self.assertEqual(res.returncode, 1, self.out(res))
        self.assertIn("没有可出的名单", self.out(res))

    def test_dry_run_survives_a_dead_endpoint(self):
        self.assertEqual(self.run_script("search.py", "--pages", "1").returncode, 0)
        self.assertEqual(self.run_script("score.py").returncode, 0)
        self.assertEqual(self.run_script("shortlist.py").returncode, 0)

        dead = fake_liepin.FakeLiepin().start().dead_url()
        fake_liepin.write_mcp_config(self.mcp_cfg, f"{dead}/mcp")

        res = self.run_script("apply.py", "--list", str(self.shortlist_csv()))

        self.assertEqual(res.returncode, 0, self.out(res))
        self.assertIn("dry-run", self.out(res))
        self.assertFalse((self.project / "ledger.csv").exists())

    def test_search_fails_loudly_against_a_dead_endpoint(self):
        dead = fake_liepin.FakeLiepin().start().dead_url()
        fake_liepin.write_mcp_config(self.mcp_cfg, f"{dead}/mcp")

        res = self.run_script("search.py", "--pages", "1")

        self.assertEqual(res.returncode, 1, self.out(res))
        self.assertIn("搜索失败", self.out(res))
        self.assertFalse((self.project / "pool" / "jobs.csv").exists(),
                         "搜不到不能顺手建一个空池子冒充成功")

    def test_the_suite_never_touches_the_real_data(self):
        real_pool = JOB_SEEKING / "pool" / "jobs.csv"
        real_ledger = JOB_SEEKING / "ledger.csv"
        real_shortlists = sorted(p.name for p in (JOB_SEEKING / "shortlists").glob("*"))
        before = (real_bytes(real_pool), real_bytes(real_ledger))

        self.run_script("search.py", "--pages", "1")
        self.run_script("score.py")
        self.run_script("shortlist.py")
        self.assert_endpoint_is_local()
        self.run_script("apply.py", "--list", str(self.shortlist_csv()), "--confirm")

        self.assertEqual((real_bytes(real_pool), real_bytes(real_ledger)), before)
        self.assertEqual(sorted(p.name for p in (JOB_SEEKING / "shortlists").glob("*")),
                         real_shortlists)

    def test_the_real_criteria_file_still_parses(self):
        """真实 criteria.md 是你手写的，格式坏了没人会知道——这里钉一下。"""
        res = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts');"
             "import matcher;"
             "print(matcher.fingerprint('keyword', 'criteria.md'))"],
            cwd=str(JOB_SEEKING), env=self.env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(res.returncode, 0, self.out(res))
        self.assertTrue(res.stdout.strip().startswith("keyword:"))
