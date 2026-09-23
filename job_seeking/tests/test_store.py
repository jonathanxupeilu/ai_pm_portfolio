"""store.py 的守卫：坏文件必须让流水线停下来，而不是静默串列/写空值。"""
from __future__ import annotations

import csv
import unittest

from support import PipelineTestCase   # 先于被测脚本：它负责把 scripts/ 放进 sys.path

import store
import shortlist as shortlist_mod


class BadPoolFileHaltsThePipeline(PipelineTestCase):
    def test_header_mismatch_stops_the_run_instead_of_misaligning_columns(self):
        store.POOL_PATH.write_text("jobName,jobId\n某岗位,1\n", encoding="utf-8")

        with self.assertRaises(SystemExit):
            self.run_cli(shortlist_mod, ["--max", "5"])

        self.assertEqual(list(store.SHORTLIST_DIR.glob("*")), [],
                         "文件读不进来就不该产出名单")


class WriteRowsRefusesMissingColumns(PipelineTestCase):
    def test_missing_column_is_refused_before_anything_is_written(self):
        target = self.root / "would_be_written.csv"

        with self.assertRaises(SystemExit):
            store.write_rows(target, ["a", "b"], [{"a": "1"}])

        self.assertFalse(target.exists(),
                         "守卫必须在打开文件之前生效——空 jobKind 会让整批投递被跳过")

    def test_extra_columns_are_ignored(self):
        target = self.root / "ok.csv"
        store.write_rows(target, ["a", "b"], [{"a": "1", "b": "2", "c": "多余的"}])

        with target.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(rows, [{"a": "1", "b": "2"}])


class ReadRowsRoundTrip(PipelineTestCase):
    def test_missing_file_is_an_empty_table_not_an_error(self):
        self.assertEqual(store.load_pool(), [])

    def test_write_then_read_preserves_rows(self):
        rows = [{"jobId": "1", "jobName": "甲"}, {"jobId": "2", "jobName": "乙"}]
        store.write_rows(store.POOL_PATH, store.POOL_FIELDS,
                         [{**{f: "" for f in store.POOL_FIELDS}, **r} for r in rows])

        back = store.read_rows(store.POOL_PATH, store.POOL_FIELDS)

        self.assertEqual([r["jobId"] for r in back], ["1", "2"])
        self.assertEqual([r["jobName"] for r in back], ["甲", "乙"])

    def test_bom_in_an_existing_file_is_tolerated(self):
        row = ["1"] + [""] * (len(store.POOL_FIELDS) - 1)
        store.POOL_PATH.write_text(
            "\ufeff" + ",".join(store.POOL_FIELDS) + "\n" + ",".join(row) + "\n",
            encoding="utf-8")

        self.assertEqual(store.read_rows(store.POOL_PATH, store.POOL_FIELDS)[0]["jobId"], "1")


class AppendRowNeverDuplicatesTheHeader(PipelineTestCase):
    def test_header_is_written_once(self):
        store.append_row(store.LEDGER_PATH, store.LEDGER_FIELDS, {"jobId": "1"})
        store.append_row(store.LEDGER_PATH, store.LEDGER_FIELDS, {"jobId": "2"})

        lines = store.LEDGER_PATH.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], ",".join(store.LEDGER_FIELDS))
        self.assertEqual(len(lines), 3)


class AppliedIdsIsTheDedupeTruth(PipelineTestCase):
    def test_blank_and_padded_ids_are_handled(self):
        for job_id in ("1", "", " 2 "):
            store.append_row(store.LEDGER_PATH, store.LEDGER_FIELDS, {"jobId": job_id})

        applied = store.applied_ids()

        self.assertEqual(applied, {"1", "2"})
        self.assertNotIn("", applied, "空 jobId 不能被当成「投过」")


class ConfigFailuresAreLoud(PipelineTestCase):
    def test_missing_config_file_stops_the_run(self):
        store.CONFIG_PATH.unlink()

        with self.assertRaises(SystemExit) as ctx:
            store.load_config()
        self.assertIn("找不到配置文件", str(ctx.exception))

    def test_invalid_config_json_stops_the_run(self):
        store.CONFIG_PATH.write_text("{这,不是,JSON", encoding="utf-8")

        with self.assertRaises(SystemExit) as ctx:
            store.load_config()
        self.assertIn("不是合法 JSON", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
