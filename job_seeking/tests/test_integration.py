"""集成层：让脚本真的走一遍 HTTP，而不是「函数被调用过」。

这里把 MCP 端点指向 127.0.0.1 上的假猎聘（tests/fake_liepin.py），于是**真实运行**的是：

- `liepin._rpc` 的 urllib 请求与 `data:` 行解析（SSE 框架）
- `x-user-token` 头是否真的从配置文件读出来并送上线
- `score.fetch_jd_text` 的 urllib 抓取 + `data-selector` 正则抽正文
- `apply.apply_job` 送出的 `jobKind` 是否原样是搜索给的那个值

**全程不出网**：假服务只绑 127.0.0.1；`--confirm` 之前有 `is_loopback` 断言兜底。
"""
from __future__ import annotations

from support import PipelineTestCase  # 必须在被测脚本之前：它负责把 scripts/ 放进 sys.path

import fake_liepin
import liepin
import matcher
import score
import search
import shortlist
import apply
import store


class FakeServerCase(PipelineTestCase):
    """把 liepin 的配置指向本地假服务。"""

    def setUp(self):
        super().setUp()
        self.server = self.make_server()
        self.addCleanup(self.server.stop)
        self.mcp_cfg = self.root / "mcp.json"
        fake_liepin.write_mcp_config(self.mcp_cfg, self.server.mcp_url)
        saved = liepin.MCP_CONFIG
        liepin.MCP_CONFIG = self.mcp_cfg
        self.addCleanup(lambda: setattr(liepin, "MCP_CONFIG", saved))

    def make_server(self) -> fake_liepin.FakeLiepin:
        return fake_liepin.FakeLiepin().start()

    def assert_endpoint_is_local(self) -> None:
        """真投之前必须先证明打的是本机假服务。"""
        url, _ = liepin.load_endpoint()
        self.assertTrue(fake_liepin.is_loopback(url), f"拒绝向非本机地址投递：{url}")


class McpOverRealHttp(FakeServerCase):
    def test_tools_list_round_trips_over_a_real_socket(self):
        tools = liepin.list_tools()
        names = [t["name"] for t in tools]
        self.assertEqual(len(names), 14)
        self.assertIn("user-search-job", names)
        self.assertIn("user-apply-job", names)

    def test_token_from_the_config_file_arrives_as_a_header(self):
        liepin.search_jobs("AI产品经理", "上海", 0)
        self.assertEqual(self.server.last_headers.get("x-user-token"),
                         fake_liepin.FAKE_TOKEN)

    def test_page_zero_is_the_first_page_no_off_by_one(self):
        server = fake_liepin.FakeLiepin(search_pages={
            0: [fake_liepin.job_row(101, "第0页的岗")],
            1: [fake_liepin.job_row(102, "第1页的岗")],
        }).start()
        self.addCleanup(server.stop)
        fake_liepin.write_mcp_config(self.mcp_cfg, server.mcp_url)

        rc, _ = self.run_cli(search, ["--pages", "2"])

        self.assertEqual(rc, 0)
        self.assertEqual([c["arguments"]["page"] for c in server.calls], [0, 1],
                         "第一页必须是 page=0，否则会整页漏岗")
        self.assertEqual({r["jobId"] for r in self.read_pool()}, {"101", "102"})


class ConfigFailuresAreLoud(FakeServerCase):
    def write_raw(self, text: str) -> None:
        self.mcp_cfg.write_text(text, encoding="utf-8")

    def test_missing_config_file_stops_loudly(self):
        liepin.MCP_CONFIG = self.root / "根本没有这个文件.json"
        with self.assertRaises(SystemExit) as ctx:
            liepin.list_tools()
        self.assertIn("找不到 MCP 配置", str(ctx.exception))

    def test_invalid_json_config_stops_loudly(self):
        self.write_raw("{这不是 JSON")
        with self.assertRaises(SystemExit) as ctx:
            liepin.list_tools()
        self.assertIn("不是合法 JSON", str(ctx.exception))

    def test_config_without_the_server_section_stops_loudly(self):
        self.write_raw('{"mcpServers": {}}')
        with self.assertRaises(SystemExit) as ctx:
            liepin.list_tools()
        self.assertIn("liepin-mcp", str(ctx.exception))

    def test_empty_url_stops_loudly(self):
        self.write_raw('{"mcpServers": {"liepin-mcp": '
                       '{"url": "", "headers": {"x-user-token": "t"}}}}')
        with self.assertRaises(SystemExit) as ctx:
            liepin.list_tools()
        self.assertIn("url 为空", str(ctx.exception))

    def test_empty_token_stops_loudly(self):
        fake_liepin.write_mcp_config(self.mcp_cfg, self.server.mcp_url, token="")
        with self.assertRaises(SystemExit) as ctx:
            liepin.list_tools()
        self.assertIn("x-user-token", str(ctx.exception))

    def test_unknown_tool_surfaces_the_server_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            liepin.call_tool("no-such-tool", {})
        self.assertIn("未知工具", str(ctx.exception))


class McpTransportErrors(FakeServerCase):
    def test_http_5xx_is_reported_with_the_status_code(self):
        fake_liepin.write_mcp_config(self.mcp_cfg, f"{self.server.url}/mcp500")

        with self.assertRaises(RuntimeError) as ctx:
            liepin.list_tools()
        self.assertIn("HTTP 500", str(ctx.exception))

    def test_unparseable_body_is_reported(self):
        fake_liepin.write_mcp_config(self.mcp_cfg, f"{self.server.url}/mcp-garbage")

        with self.assertRaises(RuntimeError) as ctx:
            liepin.list_tools()
        self.assertIn("无法解析为 JSON", str(ctx.exception))


class SearchFiltersArePassedThrough(FakeServerCase):
    def test_config_filters_reach_the_wire(self):
        """config.json 里的 search_filters 要是透传丢了，筛选会静默失效。"""
        self.write_config(search_filters={"salaryFloor": "30", "eduLevel": "本科"})

        rc, out = self.run_cli(search, ["--pages", "1"])

        self.assertEqual(rc, 0, out)
        args = self.server.calls[-1]["arguments"]
        self.assertEqual(args["salaryFloor"], "30")
        self.assertEqual(args["eduLevel"], "本科")
        self.assertEqual(args["page"], 0)

    def test_empty_filter_values_are_dropped_not_sent_as_empty(self):
        self.write_config(search_filters={"salaryFloor": "", "companyName": None})

        self.run_cli(search, ["--pages", "1"])

        args = self.server.calls[-1]["arguments"]
        self.assertNotIn("salaryFloor", args)
        self.assertNotIn("companyName", args)


class ApplyConfirmFailurePath(FakeServerCase):
    def test_dead_endpoint_makes_every_row_unknown_and_writes_no_ledger(self):
        """接口挂了的时候，绝不能变成「投过了」——假记一条会永久排除该岗。"""
        path = self.write_shortlist([{"jobKind": "2", "jobName": "AI产品经理"}])
        dead = self.server.dead_url()
        self.assertTrue(fake_liepin.is_loopback(dead), "拒绝向非本机地址投递")
        fake_liepin.write_mcp_config(self.mcp_cfg, f"{dead}/mcp")

        rc, out = self.run_cli(apply, ["--list", str(path), "--confirm"])

        self.assertEqual(rc, 1, out)
        self.assertIn("unknown", out)
        self.assertIn("未写台账", out)
        self.assertFalse(store.LEDGER_PATH.exists())


class ScoreOverRealHttp(FakeServerCase):
    def pool_row(self, url: str, job_id: str = "101") -> dict:
        self.write_pool([{"jobId": job_id, "jobType": "2", "jobName": "AI产品经理",
                          "company": "某公司", "jobDetailUrl": url}])
        return self.read_pool()[0]

    def test_jd_is_extracted_from_a_real_page_and_scored(self):
        self.pool_row(self.server.job_url(101))

        rc, out = self.run_cli(score, [])

        row = self.read_pool()[0]
        self.assertEqual(rc, 0, out)
        self.assertAlmostEqual(float(row["score"]), 100.0)
        self.assertEqual(row["hits"], "大模型|RAG")
        self.assertEqual(row["criteriaFp"], self.current_fp())

    def test_unreachable_job_page_leaves_the_score_empty(self):
        dead = self.server.dead_url()
        self.pool_row(f"{dead}/job/101")

        rc, out = self.run_cli(score, [])

        row = self.read_pool()[0]
        self.assertEqual(rc, 1, out)
        self.assertEqual(row["score"], "", "抓不到正文不能给分，0 分会伪装成「不匹配」")
        self.assertEqual(row["criteriaFp"], "")

    def test_nonexistent_job_id_returns_200_but_is_still_a_failure(self):
        # 实测：不存在的 jobId 返回 HTTP 200 + 「此页面似乎不存在」占位页。
        # 不认这一条，就会把「查无此岗」读成「抓到正文了」。
        self.pool_row(self.server.job_url(999), job_id="999")

        rc, out = self.run_cli(score, [])

        self.assertEqual(rc, 1, out)
        self.assertEqual(self.read_pool()[0]["score"], "")
        self.assertIn("岗位页不存在", out)


class SearchThenScoreSeam(FakeServerCase):
    def test_url_written_by_search_is_fetchable_by_score(self):
        """接缝测试：search 存下的 jobDetailUrl 必须能被 score 抓下来。"""
        rc1, out1 = self.run_cli(search, ["--pages", "1"])
        self.assertEqual(rc1, 0, out1)
        pool = self.read_pool()
        self.assertEqual(len(pool), 2)
        self.assertTrue(all(r["jobDetailUrl"] for r in pool))

        rc2, out2 = self.run_cli(score, [])

        self.assertEqual(rc2, 0, out2)
        for r in self.read_pool():
            self.assertNotEqual(r["score"], "", f"{r['jobId']} 没拿到分：{out2}")


class ApplyPassesJobKindVerbatim(FakeServerCase):
    def two_rows(self):
        return self.write_shortlist([{"jobKind": "1", "score": "90"},
                                     {"jobKind": "2", "score": "80"}])

    def test_dry_run_over_real_http_touches_nothing(self):
        csv_path = self.two_rows()

        rc, out = self.run_cli(apply, ["--list", str(csv_path)])

        self.assertEqual(rc, 0, out)
        self.assertEqual(self.server.applies, [], "dry-run 不得外呼")
        self.assertFalse(store.LEDGER_PATH.exists(), "dry-run 不得写台账")

    def test_confirm_sends_job_kind_verbatim_and_records_the_ledger(self):
        csv_path = self.two_rows()
        self.assert_endpoint_is_local()

        rc, out = self.run_cli(apply, ["--list", str(csv_path), "--confirm"])

        self.assertEqual(rc, 0, out)
        self.assertEqual(self.server.applies, [(1, "1"), (2, "2")],
                         "jobKind 必须是名单里的原值，不得自行推导")
        ledger = store.load_ledger()
        self.assertEqual([r["jobId"] for r in ledger], ["1", "2"])
        self.assertTrue(all(r["status"] == "成功" for r in ledger))
