#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""匹配层：把 JD 正文算成一个 0-100 的匹配度。

**这是唯一需要改就能换算法的地方。** 由 config.json 的 `matcher` 字段选择实现。

注意：正则（re）只用于在 score.py 里从 HTML 抽正文，不参与这里的匹配判断。
"""
from __future__ import annotations

import hashlib
import pathlib
from typing import Protocol


class Matcher(Protocol):
    def score(self, jd_text: str, job: dict) -> tuple[float, list[str]]:
        """返回 (匹配度 0-100, 命中词列表)。"""
        ...


class KeywordMatcher:
    """忽略大小写的子串匹配，按权重归一化。

    不讲语义：『大模型』和『LLM』在它眼里是两个无关的词。同义词请在 criteria.md
    各写一行——这是换来「分数可解释」的代价。
    """

    def __init__(self, keywords: list[tuple[str, float]]):
        if not keywords:
            raise ValueError("没解析出任何关键词，拒绝用空表打分")
        self.keywords = keywords
        self._total = sum(w for _, w in keywords) or 1.0

    def score(self, jd_text: str, job: dict) -> tuple[float, list[str]]:
        low = (jd_text or "").lower()
        hits: list[str] = []
        got = 0.0
        for term, weight in self.keywords:
            if term.lower() in low:
                hits.append(term)
                got += weight
        return round(100.0 * got / self._total, 1), hits


class EmbeddingMatcher:
    """语义匹配空位——刻意让它报错。

    不静默退回关键词算法：那样你会在不知情的情况下用错口径打分，比直接失败更糟。
    实现方向见 criteria.md 末尾。
    """

    def __init__(self, *_, **__):
        raise NotImplementedError(
            "EmbeddingMatcher 尚未实现，拒绝打分。\n"
            "  二选一：① 在 scripts/matcher.py 里实现它；\n"
            "          ② 把 config.json 的 matcher 改回 \"keyword\"。"
        )


def load_criteria(path) -> list[tuple[str, float]]:
    """从 criteria.md 的『| 关键词 | 权重 |』表格读词表。"""
    path = pathlib.Path(path)
    if not path.exists():
        raise SystemExit(f"❌ 找不到打分标准：{path}")

    terms: list[tuple[str, float]] = []
    header_seen = sep_seen = False
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if not header_seen:
            if "关键词" in cells[0]:
                header_seen = True
            continue
        if not sep_seen and set("".join(cells)) <= set("-: "):
            sep_seen = True
            continue

        term = cells[0]
        if not term or term.startswith("#"):
            continue
        try:
            weight = float(cells[1]) if cells[1] else 1.0
        except ValueError:
            raise SystemExit(
                f"❌ criteria.md 里『{term}』的权重不是数字：{cells[1]!r}"
            ) from None
        terms.append((term, weight))

    if not terms:
        raise SystemExit(
            f"❌ {path} 里没解析到关键词，请检查『| 关键词 | 权重 |』表头是否存在"
        )
    return terms


def fingerprint(name: str, criteria_path) -> str:
    """打分口径的短指纹，用来判断一个已存的分数是不是还有效。

    刻意哈希**解析后的词表**（去重后按词排序）而不是 criteria.md 的文件字节：
    改注释、加空行、调行序都不该让全池重算，只有真正会改变分数的改动
    （加词/删词/改权重/换 matcher）才让指纹变。

    不哈希行序，是因为 `匹配度 = 权重和 ÷ 总权重` 与顺序无关。
    """
    key = (name or "keyword").strip().lower()
    pairs = sorted((str(t), float(w)) for t, w in load_criteria(criteria_path))
    blob = "\n".join(f"{t}\t{w}" for t, w in pairs).encode("utf-8")
    return f"{key}:{hashlib.sha256(blob).hexdigest()[:12]}"


def get_matcher(name: str, criteria_path) -> Matcher:
    key = (name or "keyword").strip().lower()
    if key == "keyword":
        return KeywordMatcher(load_criteria(criteria_path))
    if key == "embedding":
        return EmbeddingMatcher()
    raise SystemExit(
        f"❌ config.json 的 matcher 取值无法识别：{name!r}（可用：keyword / embedding）"
    )
