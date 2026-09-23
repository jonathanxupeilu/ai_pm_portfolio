#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""筛选第二步：拉 JD 正文算匹配度，写回池。**正文用完即弃，不落盘。**

用法：
  uv run --no-project python scripts/score.py [--limit N] [--rescore]

抓不到正文的岗位记 `unknown`：分数留空、下次重试，并且**不**给它一个默认分——
静默算 0 分会让「抓取失败」看起来像「不匹配」，是最难查的那种错。
"""
from __future__ import annotations

import argparse
import html as html_mod
import re
import sys
import urllib.error
import urllib.request

import matcher
import store

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
TIMEOUT = 30
BODY_RE = re.compile(r'data-selector="job-intro-content"[^>]*>(.*?)</dd>', re.S)
# 实测：不存在的 jobId 返回的是 **HTTP 200** + 一个 5KB 的「此页面似乎不存在」占位页
# （还带 4 秒后跳首页）。所以 200 不等于岗位页存在——不认这一条，这种岗位会被
# 误报成「站点改版了」，把「查无此岗」伪装成「抓取器坏了」，两边都查错方向。
NOT_FOUND_MARKERS = ("此页面似乎不存在", "页面不存在", "职位不存在", "该职位已下线")


def fetch_jd_text(url: str) -> str:
    """取岗位页并从 data-selector="job-intro-content" 抽出正文。"""
    if not url:
        raise RuntimeError("该岗位没有 jobDetailUrl")

    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            page = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"连接失败：{e.reason}") from None

    if any(k in page for k in NOT_FOUND_MARKERS):
        raise RuntimeError("岗位页不存在（服务端把占位页装在 HTTP 200 里返回，"
                           "不是抓取失败，也**不等于**该岗已下线——下线与否只有投递接口说了算）")

    m = BODY_RE.search(page)
    if not m:
        # 判不出原因就只报事实：给一个猜的原因（「站点改版」）会让人往错方向查。
        title = re.search(r"<title>(.*?)</title>", page, re.S)
        raise RuntimeError(
            f'页面里没有 data-selector="job-intro-content"'
            f'（HTTP 200，{len(page)} 字节，标题「{(title.group(1).strip() if title else "无")[:60]}」）'
            f"——原因判不出，按事实记录"
        )

    raw = m.group(1)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</(?:p|div|li|dd|dt|h[1-6])>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", "", raw)
    text = html_mod.unescape(raw).strip()
    if not text:
        raise RuntimeError("正文抽出来是空的")
    return text


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="拉 JD 正文 → 算匹配度 → 写回池")
    p.add_argument("--limit", type=int, help="最多处理多少个岗位")
    p.add_argument("--rescore", action="store_true", help="已打过分的也重算")
    a = p.parse_args(argv)

    cfg = store.load_config()
    m = matcher.get_matcher(cfg.get("matcher", "keyword"), store.CRITERIA_PATH)

    rows = store.load_pool()
    if not rows:
        # 与短名单同一条规矩：没干活就是没干活，不带「池子空所以算成功」的例外。
        print("池子是空的，先跑 search.py")
        return 1

    targets = [r for r in rows if a.rescore or not str(r.get("score", "")).strip()]
    if a.limit is not None:
        targets = targets[:a.limit]
    if not targets:
        print("没有待打分的岗位（要全部重算用 --rescore）")
        return 0

    ok = unknown = 0
    for r in targets:
        jid = r.get("jobId")
        name = str(r.get("jobName", ""))[:28]
        try:
            text = fetch_jd_text(str(r.get("jobDetailUrl", "")))
            score, hits = m.score(text, r)          # text 只存在于这次循环里
            r["score"] = score
            r["hits"] = "|".join(hits)
            ok += 1
            print(f"✅ {jid} {name} → {score}  命中 {hits or '（无）'}")
        except Exception as e:
            unknown += 1
            print(f"❌ {jid} {name} → unknown：{e}\n   {r.get('jobDetailUrl', '')}")

    store.save_pool(rows)
    print(f"\n打分完成 {ok} 个｜unknown {unknown} 个（分数留空，下次重试）")
    if unknown:
        print("⚠️  有岗位判不出，已显式标 unknown 且未给默认分——请先看上面的失败原因。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
