"""search.py：搜到多少先保住多少，但失败必须响亮（退出码 1）。"""
from __future__ import annotations

import unittest
import unittest.mock

from support import PipelineTestCase   # 先于被测脚本：它负责把 scripts/ 放进 sys.path

import store
import search as search_mod


def raw(job_id, **overrides) -> dict:
    return {"jobId": job_id, "jobType": "2", "jobName": f"岗位{job_id}",
            "company": "某公司", "location": "上海", "salary": "20-30k",
            "jobDetailUrl": f"https://example.invalid/{job_id}", **overrides}


class PartialFailureKeepsWhatWasFound(PipelineTestCase):
    def test_rows_from_the_successful_page_survive_the_failure(self):
        """额度在响应返回时就花掉了——丢了等于「付了钱还重付」。"""

        def fake_search(job_name, address="", page=0, **filters):
            if page == 0:
                return [raw(1), raw(2)]
            raise RuntimeError("第二页挂了")

        with unittest.mock.patch.object(search_mod.liepin, "search_jobs",
                                       side_effect=fake_search):
            rc, out = self.run_cli(search_mod, ["--pages", "2"])

        self.assertEqual(rc, 1, "没搜完就不能报成功")
        self.assertEqual([r["jobId"] for r in self.read_pool()], ["1", "2"])


class DedupeAndGuards(PipelineTestCase):
    def test_known_jobid_is_not_added_twice(self):
        self.write_pool([{"jobId": "1", "jobType": "2", "jobName": "岗位1"}])

        with unittest.mock.patch.object(search_mod.liepin, "search_jobs",
                                       return_value=[raw(1), raw(2)]):
            rc, out = self.run_cli(search_mod, [])

        self.assertEqual(rc, 0)
        ids = [r["jobId"] for r in self.read_pool()]
        self.assertEqual(ids.count("1"), 1)
        self.assertIn("2", ids)
        self.assertIn("去重跳过 1 条", out)

    def test_row_without_jobid_is_skipped(self):
        with unittest.mock.patch.object(
            search_mod.liepin, "search_jobs",
            return_value=[{"jobName": "没有 jobId 的行"}, raw(5)],
        ):
            rc, _ = self.run_cli(search_mod, [])

        self.assertEqual(rc, 0)
        self.assertEqual([r["jobId"] for r in self.read_pool()], ["5"])

    def test_dry_run_leaves_the_pool_untouched(self):
        self.write_pool([{"jobId": "1", "jobType": "2", "jobName": "岗位1"}])
        before = store.POOL_PATH.read_bytes()

        with unittest.mock.patch.object(search_mod.liepin, "search_jobs",
                                       return_value=[raw(2)]):
            rc, out = self.run_cli(search_mod, ["--dry-run"])

        self.assertEqual(rc, 0)
        self.assertEqual(store.POOL_PATH.read_bytes(), before)
        self.assertIn("--dry-run", out)


class ArgGuardsAreLoud(PipelineTestCase):
    def test_empty_keyword_list_stops_the_run(self):
        self.write_config(keywords=[])

        with self.assertRaises(SystemExit) as ctx:
            self.run_cli(search_mod, ["--pages", "1"])
        self.assertIn("keywords 为空", str(ctx.exception))

    def test_zero_pages_is_refused_instead_of_silently_searching_nothing(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_cli(search_mod, ["--pages", "0"])
        self.assertIn("至少为 1", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
