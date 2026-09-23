"""score.py 的失败语义：抓不到正文就留空重试，绝不默认 0 分。

「抓取失败」和「岗位不匹配」在池子里必须以不同形态存在——前者 `score` 为空，
后者是一个数。混在一起是最难查的那类错。
"""
from __future__ import annotations

import unittest
import unittest.mock
import urllib.error

from support import (JD_MARKER, PLACEHOLDER_PAGE, FakeResponse, PipelineTestCase,
                     page_with_jd)

import store
import score as score_mod


def patched_urlopen(**kwargs):
    return unittest.mock.patch("urllib.request.urlopen", **kwargs)


class FetchFailureLeavesScoreEmpty(PipelineTestCase):
    def setUp(self):
        super().setUp()
        self.write_pool([{"jobId": "1", "jobType": "2", "jobName": "岗位A",
                          "jobDetailUrl": "https://example.invalid/1"}])

    def assert_unknown(self, out: str) -> None:
        row = self.read_pool()[0]
        self.assertEqual(row["score"], "", "抓取失败必须留空，不能给默认分")
        self.assertEqual(row["hits"], "")
        self.assertEqual(row["criteriaFp"], "")
        self.assertIn("unknown", out)

    def test_unreachable_url(self):
        with patched_urlopen(side_effect=urllib.error.URLError("dns 挂了")):
            rc, out = self.run_cli(score_mod, [])
        self.assertEqual(rc, 1)
        self.assert_unknown(out)

    def test_http_error(self):
        err = urllib.error.HTTPError("https://example.invalid/1", 404, "Not Found", {}, None)
        with patched_urlopen(side_effect=err):
            rc, out = self.run_cli(score_mod, [])
        self.assertEqual(rc, 1)
        self.assert_unknown(out)

    def test_placeholder_page_behind_http_200_is_not_scored(self):
        """HTTP 200 ≠ 岗位页存在：服务端把「此页面似乎不存在」装在 200 里返回。"""
        with patched_urlopen(return_value=FakeResponse(PLACEHOLDER_PAGE)):
            rc, out = self.run_cli(score_mod, [])
        self.assertEqual(rc, 1)
        self.assert_unknown(out)

    def test_missing_jd_container_reports_facts_not_a_guessed_cause(self):
        page = ("<html><head><title>某公司首页</title></head>"
                "<body>整页都没有正文容器</body></html>")
        with patched_urlopen(return_value=FakeResponse(page)):
            rc, out = self.run_cli(score_mod, [])
        self.assertEqual(rc, 1)
        self.assert_unknown(out)
        self.assertIn("data-selector", out)   # 报的是事实……
        self.assertIn("某公司首页", out)        # ……连页面标题一起，而不是猜「站点改版了」

    def test_row_without_a_detail_url_is_unknown_not_zero(self):
        """没有 jobDetailUrl 的岗位连抓都不用抓，但也不能因此得一个 0 分。"""
        self.write_pool([{"jobId": "1", "jobType": "2", "jobName": "岗位A"}])
        with patched_urlopen(side_effect=AssertionError("没 URL 竟然还去抓了")):
            rc, out = self.run_cli(score_mod, [])

        self.assertEqual(rc, 1)
        self.assert_unknown(out)
        self.assertIn("没有 jobDetailUrl", out)

    def test_empty_jd_container_is_unknown_not_zero(self):
        """容器在、正文是空——照样是判不出，不是「命中 0 个关键词」。"""
        with patched_urlopen(return_value=FakeResponse(page_with_jd("   "))):
            rc, out = self.run_cli(score_mod, [])

        self.assertEqual(rc, 1)
        self.assert_unknown(out)
        self.assertIn("空的", out)


class SuccessfulScoring(PipelineTestCase):
    def setUp(self):
        super().setUp()
        self.write_pool([{"jobId": "1", "jobType": "2", "jobName": "岗位A",
                          "jobDetailUrl": "https://example.invalid/1"}])

    def test_score_hits_and_fingerprint_are_written(self):
        jd = f"我们做大模型与 RAG 的产品设计。{JD_MARKER}"
        with patched_urlopen(return_value=FakeResponse(page_with_jd(jd))):
            rc, _ = self.run_cli(score_mod, [])

        self.assertEqual(rc, 0)
        row = self.read_pool()[0]
        self.assertEqual(float(row["score"]), 100.0)
        self.assertEqual(row["hits"], "大模型|RAG")
        self.assertEqual(row["criteriaFp"], self.current_fp())

    def test_jd_body_is_discarded_not_persisted(self):
        with patched_urlopen(return_value=FakeResponse(page_with_jd(JD_MARKER))):
            self.run_cli(score_mod, [])
        self.assertNotIn(JD_MARKER, store.POOL_PATH.read_text(encoding="utf-8"),
                         "JD 正文用完即弃，不该留在池子里")


class StaleFingerprintIsRescored(PipelineTestCase):
    OLD = {"jobId": "1", "jobType": "2", "jobName": "岗位A",
           "jobDetailUrl": "https://example.invalid/1",
           "score": "99", "hits": "旧词", "criteriaFp": "keyword:deadbeef"}

    def test_row_scored_under_old_criteria_is_recomputed(self):
        self.write_pool([self.OLD])
        with patched_urlopen(return_value=FakeResponse(page_with_jd("只做大模型"))):
            rc, _ = self.run_cli(score_mod, [])

        self.assertEqual(rc, 0)
        row = self.read_pool()[0]
        self.assertEqual(float(row["score"]), 60.0)
        self.assertEqual(row["hits"], "大模型")
        self.assertEqual(row["criteriaFp"], self.current_fp())

    def test_stale_row_that_fails_to_fetch_loses_the_old_score(self):
        """抓取失败时必须留下「未打分」，而不是一个按旧口径算出来的分数。"""
        self.write_pool([self.OLD])
        with patched_urlopen(side_effect=urllib.error.URLError("dns 挂了")):
            rc, out = self.run_cli(score_mod, [])

        self.assertEqual(rc, 1)
        row = self.read_pool()[0]
        self.assertEqual(row["score"], "", "旧口径的 99 必须被清掉")
        self.assertEqual(row["hits"], "")
        self.assertEqual(row["criteriaFp"], "")


class EmptyPoolAndNothingToDo(PipelineTestCase):
    def test_empty_pool_is_not_a_success(self):
        rc, out = self.run_cli(score_mod, [])
        self.assertEqual(rc, 1, "池子空 = 什么都没干，不能报成功")
        self.assertIn("池子是空的", out)

    def test_nothing_left_to_score_is_a_success(self):
        """和上面那两条不同：这次是真干完了（所有岗都按当前口径打过分）。"""
        self.write_pool([self.scored_row("1", "80"), self.scored_row("2", "60")])

        rc, out = self.run_cli(score_mod, [])

        self.assertEqual(rc, 0)
        self.assertIn("没有待打分的岗位", out)


if __name__ == "__main__":
    unittest.main()
