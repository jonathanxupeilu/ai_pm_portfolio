"""apply.py 的两道闸门：dry-run 零外呼、台账已投的岗位不再投。"""
from __future__ import annotations

import unittest
import unittest.mock

from support import PipelineTestCase   # 先于被测脚本：它负责把 scripts/ 放进 sys.path

import store
import apply as apply_mod


class DryRunNeverCallsOut(PipelineTestCase):
    def test_dry_run_exits_zero_and_makes_zero_calls(self):
        path = self.write_shortlist([{"jobKind": "2", "jobName": "AI产品经理",
                                      "company": "甲公司", "score": "40"}])
        with unittest.mock.patch.object(
            apply_mod.liepin, "apply_job",
            side_effect=AssertionError("dry-run 竟然外呼了"),
        ) as spy:
            rc, out = self.run_cli(apply_mod, ["--list", str(path)])

        self.assertEqual(rc, 0)
        self.assertEqual(spy.call_count, 0)
        self.assertIn("dry-run", out)
        self.assertFalse(store.LEDGER_PATH.exists(), "dry-run 不该写台账")

    def test_confirm_makes_exactly_one_call_per_row_and_writes_ledger(self):
        path = self.write_shortlist([{"jobKind": "2", "jobName": "AI产品经理",
                                      "company": "甲公司", "score": "40"}])
        with unittest.mock.patch.object(
            apply_mod.liepin, "apply_job", return_value={"message": "投递成功"},
        ) as spy:
            rc, _ = self.run_cli(apply_mod, ["--list", str(path), "--confirm"])

        self.assertEqual(rc, 0)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(spy.call_args.args, (1, "2"))
        rows = store.load_ledger()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "成功")
        self.assertEqual(rows[0]["jobKind"], "2")


class LedgerIsTheDedupeSource(PipelineTestCase):
    def test_row_already_in_ledger_is_skipped(self):
        path = self.write_shortlist([{"jobKind": "2", "jobName": "AI产品经理"}])
        self.ledger_row("1")
        with unittest.mock.patch.object(
            apply_mod.liepin, "apply_job",
            side_effect=AssertionError("对已投岗位外呼了"),
        ) as spy:
            rc, out = self.run_cli(apply_mod, ["--list", str(path), "--confirm"])

        self.assertEqual(spy.call_count, 0)
        self.assertIn("台账已记录", out)
        self.assertEqual(rc, 1, "没有可投项 → 退出码 1（零动作不等于成功）")


class UnknownIsNotRecorded(PipelineTestCase):
    def test_unclassifiable_response_is_not_written_to_ledger(self):
        path = self.write_shortlist([{"jobKind": "2", "jobName": "AI产品经理"}])
        with unittest.mock.patch.object(apply_mod.liepin, "apply_job",
                                       return_value={"unexpected": "shape"}):
            rc, out = self.run_cli(apply_mod, ["--list", str(path), "--confirm"])

        self.assertEqual(rc, 1)
        self.assertIn("判不出", out)
        self.assertFalse(store.LEDGER_PATH.exists(), "判不出的结果绝不进台账")

    def test_dup_phrase_without_the_word_failure_is_still_a_failure(self):
        """回包里只有「已投递过」、没有「失败」时，判定顺序反了就会记成成功。

        真实台账里观测到的原文是「应聘失败: 您已投递过该职位！」，它自带「失败」二字，
        拿它来测**测不出顺序**——必须用只有重复投递语义的那一句。
        """
        path = self.write_shortlist([{"jobKind": "2", "jobName": "AI产品经理"}])
        with unittest.mock.patch.object(
            apply_mod.liepin, "apply_job",
            return_value={"msg": "您已投递过该职位"},
        ):
            self.run_cli(apply_mod, ["--list", str(path), "--confirm"])

        self.assertEqual(store.load_ledger()[0]["status"], "失败")

    def test_real_observed_dup_message_is_also_a_failure(self):
        path = self.write_shortlist([{"jobKind": "2", "jobName": "AI产品经理"}])
        with unittest.mock.patch.object(
            apply_mod.liepin, "apply_job",
            return_value={"msg": "应聘失败: 您已投递过该职位！"},
        ):
            self.run_cli(apply_mod, ["--list", str(path), "--confirm"])

        self.assertEqual(store.load_ledger()[0]["status"], "失败")


class MissingKindIsSkipped(PipelineTestCase):
    def test_row_without_jobkind_is_skipped_not_guessed(self):
        path = self.write_shortlist([{"jobKind": "", "jobName": "缺kind的岗"}])
        with unittest.mock.patch.object(
            apply_mod.liepin, "apply_job",
            side_effect=AssertionError("对缺 jobKind 的行外呼了"),
        ) as spy:
            rc, out = self.run_cli(apply_mod, ["--list", str(path), "--confirm"])

        self.assertEqual(spy.call_count, 0)
        self.assertIn("缺 jobId/jobKind", out)


class MissingListFileIsRefused(PipelineTestCase):
    def test_nonexistent_shortlist_is_a_loud_refusal(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_cli(apply_mod, ["--list", str(self.root / "没有这个名单.csv")])
        self.assertIn("找不到名单文件", str(ctx.exception))


class CallFailureIsUnknownNotASuccess(PipelineTestCase):
    def test_interface_exception_is_unknown_and_writes_no_ledger(self):
        """接口抛异常（超时/认证失效）绝不能变成「投过了」——假记一条会永久排除该岗。"""
        path = self.write_shortlist([{"jobKind": "2", "jobName": "AI产品经理"}])
        with unittest.mock.patch.object(apply_mod.liepin, "apply_job",
                                       side_effect=RuntimeError("连接失败：timed out")):
            rc, out = self.run_cli(apply_mod, ["--list", str(path), "--confirm"])

        self.assertEqual(rc, 1)
        self.assertIn("调用异常", out)
        self.assertIn("判不出", out)
        self.assertFalse(store.LEDGER_PATH.exists(), "异常路径绝不写台账")


class RealResponseShapesFromTheLiveEndpoint(PipelineTestCase):
    """两种回包都是 2026-09-23 对真实端点实测到的，不是编的。

    最重要的一条：**`errCode` 在成功和失败两种情形下都是 0**。所以 `errCode == 0`
    只说明「请求被处理了」，绝不能当成功判据——拿它判定会把重复投递假记成成功。
    """

    REAL_SUCCESS = {"data": {"result": "应聘成功"}, "errCode": 0}
    REAL_DUPLICATE = {"data": {"result": "应聘失败: 您已投递过该职位！"}, "errCode": 0}

    def run_with(self, resp) -> tuple[int, str]:
        path = self.write_shortlist([{"jobKind": "2", "jobName": "AI产品经理"}])
        with unittest.mock.patch.object(apply_mod.liepin, "apply_job", return_value=resp):
            return self.run_cli(apply_mod, ["--list", str(path), "--confirm"])

    def test_real_success_envelope_is_recorded_as_success(self):
        rc, _ = self.run_with(self.REAL_SUCCESS)

        self.assertEqual(rc, 0)
        self.assertEqual(store.load_ledger()[0]["status"], "成功")

    def test_real_duplicate_envelope_is_a_failure_despite_errcode_zero(self):
        self.run_with(self.REAL_DUPLICATE)
        self.assertEqual(store.load_ledger()[0]["status"], "失败")

    def test_the_same_err_code_yields_opposite_verdicts(self):
        """把这条钉死：errCode 相同而结论相反，所以判定只能看 data.result。"""
        self.assertEqual(self.REAL_SUCCESS["errCode"], self.REAL_DUPLICATE["errCode"])

        self.assertEqual(apply_mod.classify(self.REAL_SUCCESS)[0], "成功")
        self.assertEqual(apply_mod.classify(self.REAL_DUPLICATE)[0], "失败")

    def test_errcode_zero_without_a_marker_word_is_unknown_not_success(self):
        rc, _ = self.run_with({"data": {"result": "已受理"}, "errCode": 0})

        self.assertEqual(rc, 1)
        self.assertFalse(store.LEDGER_PATH.exists(), "errCode 0 不是成功判据")

    def test_the_raw_envelope_is_kept_in_the_ledger_for_audit(self):
        self.run_with(self.REAL_SUCCESS)
        self.assertIn("errCode", store.load_ledger()[0]["resultText"])


if __name__ == "__main__":
    unittest.main()
