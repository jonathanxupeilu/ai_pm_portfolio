"""matcher.py：口径表的解析、指纹的敏感度、以及 embedding 空位必须报错。"""
from __future__ import annotations

import unittest

from support import PipelineTestCase   # 先于被测脚本：它负责把 scripts/ 放进 sys.path

import matcher


def table(*rows: str) -> str:
    return "\n".join(["| 关键词 | 权重 |", "|---|---|", *[f"| {r} |" for r in rows]])


class LoadCriteriaParsing(PipelineTestCase):
    def write_criteria(self, text: str) -> str:
        path = self.root / "criteria_under_test.md"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_comments_blank_lines_and_table_order_are_ignored(self):
        path = self.write_criteria(
            "# 打分标准\n"
            "\n"
            "表头之前出现的表格行不算数：\n"
            "\n"
            + table("大模型 | 3", "RAG | 2", "# 被注释的词 | 5")
            + "\n\n改口径只需要改这张表。\n"
        )

        self.assertEqual(matcher.load_criteria(path), [("大模型", 3.0), ("RAG", 2.0)])

    def test_blank_weight_defaults_to_one(self):
        path = self.write_criteria(table("提示词 | ", "评测 | 2"))
        self.assertEqual(matcher.load_criteria(path), [("提示词", 1.0), ("评测", 2.0)])

    def test_non_numeric_weight_is_refused_loudly(self):
        path = self.write_criteria(table("大模型 | 高"))
        with self.assertRaises(SystemExit):
            matcher.load_criteria(path)

    def test_missing_table_is_refused_loudly(self):
        path = self.write_criteria("这里只有文字，没有任何表格。\n")
        with self.assertRaises(SystemExit):
            matcher.load_criteria(path)

    def test_missing_file_is_refused_loudly(self):
        with self.assertRaises(SystemExit):
            matcher.load_criteria(self.root / "不存在.md")

    def test_a_stray_row_without_a_weight_column_is_skipped(self):
        """表格里混进一行只有一个格子的（手滑多打一个 |）不该让整张表解析失败。"""
        path = self.write_criteria(table("大模型 | 3", "光杆一行", "RAG | 2"))

        self.assertEqual(matcher.load_criteria(path), [("大模型", 3.0), ("RAG", 2.0)])


class FingerprintTracksOnlyRealChanges(PipelineTestCase):
    def fp(self, text: str, name: str = "keyword") -> str:
        path = self.root / "fp.md"
        path.write_text(text, encoding="utf-8")
        return matcher.fingerprint(name, path)

    def test_comments_and_row_order_do_not_change_it(self):
        a = self.fp(table("大模型 | 3", "RAG | 2"))
        b = self.fp("# 换了个注释\n" + table("RAG | 2", "大模型 | 3") + "\n\n多了一行空话\n")
        self.assertEqual(a, b, "改注释/调行序不该让全池重算")

    def test_adding_a_term_changes_it(self):
        self.assertNotEqual(self.fp(table("大模型 | 3")),
                            self.fp(table("大模型 | 3", "RAG | 2")))

    def test_changing_a_weight_changes_it(self):
        self.assertNotEqual(self.fp(table("大模型 | 3")),
                            self.fp(table("大模型 | 4")))

    def test_switching_matcher_changes_it(self):
        text = table("大模型 | 3")
        self.assertNotEqual(self.fp(text, "keyword"), self.fp(text, "embedding"))


class MatcherSelection(PipelineTestCase):
    def test_keyword_matcher_scores_case_insensitively(self):
        path = self.root / "c.md"
        path.write_text(table("LLM | 3", "RAG | 2"), encoding="utf-8")
        m = matcher.get_matcher("keyword", path)

        score, hits = m.score("我们做 llm 与 rag", {})

        self.assertEqual(score, 100.0)
        self.assertEqual(hits, ["LLM", "RAG"])

    def test_embedding_refuses_to_score_instead_of_falling_back(self):
        """静默退回关键词＝在不知情的情况下用错口径打分，比直接失败更糟。"""
        path = self.root / "c.md"
        path.write_text(table("大模型 | 3"), encoding="utf-8")
        with self.assertRaises(NotImplementedError):
            matcher.get_matcher("embedding", path)

    def test_unknown_matcher_name_is_refused(self):
        path = self.root / "c.md"
        path.write_text(table("大模型 | 3"), encoding="utf-8")
        with self.assertRaises(SystemExit):
            matcher.get_matcher("随便写的", path)

    def test_empty_criteria_table_is_refused(self):
        with self.assertRaises(ValueError):
            matcher.KeywordMatcher([])


if __name__ == "__main__":
    unittest.main()
