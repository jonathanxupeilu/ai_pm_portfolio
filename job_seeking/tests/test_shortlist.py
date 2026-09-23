"""shortlist.py：四层排除、按分排序、jobType→jobKind 改名。"""
from __future__ import annotations

import csv
import unittest

from support import PipelineTestCase   # 先于被测脚本：它负责把 scripts/ 放进 sys.path

import store
import shortlist as shortlist_mod


def only_shortlist_csv():
    return next(store.SHORTLIST_DIR.glob("*.csv"))


def rows_of(path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


class EveryExclusionIsReported(PipelineTestCase):
    def test_applied_job_does_not_reappear(self):
        self.write_pool([self.scored_row("1", "90"), self.scored_row("2", "80")])
        self.ledger_row("1")

        rc, out = self.run_cli(shortlist_mod, [])

        self.assertEqual([r["jobId"] for r in rows_of(only_shortlist_csv())], ["2"])
        self.assertIn("已投 1", out)

    def test_stale_criteria_row_is_excluded_and_counted(self):
        self.write_pool([self.scored_row("1", "50"),
                         self.scored_row("2", "99", criteriaFp="keyword:deadbeef")])

        rc, out = self.run_cli(shortlist_mod, [])

        self.assertEqual([r["jobId"] for r in rows_of(only_shortlist_csv())], ["1"])
        self.assertIn("旧口径 1", out)

    def test_unscored_row_is_excluded(self):
        self.write_pool([self.scored_row("1"),
                         {"jobId": "2", "jobType": "2", "jobName": "没打分的岗"}])

        rc, out = self.run_cli(shortlist_mod, [])

        self.assertEqual([r["jobId"] for r in rows_of(only_shortlist_csv())], ["1"])
        self.assertIn("未打分 1", out)

    def test_row_without_jobtype_is_dropped_and_reported(self):
        self.write_pool([self.scored_row("1"), self.scored_row("2", jobType="")])

        rc, out = self.run_cli(shortlist_mod, [])

        self.assertEqual([r["jobId"] for r in rows_of(only_shortlist_csv())], ["1"])
        self.assertIn("缺 jobKind 已剔除", out)

    def test_nothing_eligible_exits_nonzero(self):
        self.write_pool([self.scored_row("1")])
        self.ledger_row("1")

        rc, _ = self.run_cli(shortlist_mod, [])

        self.assertEqual(rc, 1)

    def test_empty_pool_exits_nonzero(self):
        rc, out = self.run_cli(shortlist_mod, [])

        self.assertEqual(rc, 1)
        self.assertIn("池子是空的", out)


class CsvIsMachineReadableByApply(PipelineTestCase):
    def test_pool_jobtype_lands_in_the_jobkind_column(self):
        """历史事故：改名漏了会让名单 15 行、apply 一看全缺 jobKind、整批静默跳过。"""
        self.write_pool([self.scored_row("1", jobType="7")])

        rc, _ = self.run_cli(shortlist_mod, [])

        self.assertEqual(rc, 0)
        row = rows_of(only_shortlist_csv())[0]
        self.assertIn("jobKind", row)
        self.assertNotIn("jobType", row)
        self.assertEqual(row["jobKind"], "7")

    def test_rows_are_sorted_by_score_desc(self):
        self.write_pool([self.scored_row("1", "30"), self.scored_row("2", "90"),
                         self.scored_row("3", "60")])

        self.run_cli(shortlist_mod, [])

        self.assertEqual([r["jobId"] for r in rows_of(only_shortlist_csv())],
                         ["2", "3", "1"])

    def test_max_truncates(self):
        self.write_pool([self.scored_row(str(i), str(i * 10)) for i in range(1, 6)])

        self.run_cli(shortlist_mod, ["--max", "2"])

        self.assertEqual(len(rows_of(only_shortlist_csv())), 2)

    def test_markdown_is_written_alongside_the_csv(self):
        self.write_pool([self.scored_row("1")])

        self.run_cli(shortlist_mod, [])

        md = next(store.SHORTLIST_DIR.glob("*.md"))
        text = md.read_text(encoding="utf-8")
        self.assertIn("apply.py", text)
        self.assertIn(only_shortlist_csv().name, text)


if __name__ == "__main__":
    unittest.main()
