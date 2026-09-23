#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""筛选第一步：按关键词搜岗并入池（按 jobId 去重）。**不投递。**

用法：
  uv run --no-project python scripts/search.py [--pages N] [--dry-run] [--keyword K] [--city C]

搜索失败（认证/网络）会直接报错退出，不会退化成「没搜到」——那样会把真实故障
伪装成市场的冷淡。
"""
from __future__ import annotations

import argparse
import datetime
import sys

import liepin
import store


def build_row(raw: dict, keyword: str, city: str, today: str) -> dict:
    tags = raw.get("companyTags") or []
    return {
        "jobId": raw.get("jobId", ""),
        "jobType": raw.get("jobType", ""),          # 投递时要用的 jobKind，先存下来
        "jobName": raw.get("jobName", ""),
        "company": raw.get("company", ""),
        "location": raw.get("location", ""),
        "salary": raw.get("salary", ""),
        "education": raw.get("education", ""),
        "workYears": raw.get("workYears", ""),
        "industry": raw.get("industry", ""),
        "companyTags": "|".join(str(t) for t in tags),
        "financingStage": raw.get("financingStage", ""),
        "companySize": raw.get("companySize", ""),
        "jobDetailUrl": raw.get("jobDetailUrl", ""),
        "score": "", "hits": "",
        "criteriaFp": "",                   # 打分时由 score.py 填
        "searchKeyword": keyword, "searchCity": city, "foundAt": today,
    }


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="猎聘搜岗 → 入池（不投递）")
    p.add_argument("--pages", type=int, help="每个「关键词×城市」翻几页（每页 20 条）")
    p.add_argument("--dry-run", action="store_true", help="只报告，不写池")
    p.add_argument("--keyword", help="只搜这一个关键词（默认用 config.json 里的全部）")
    p.add_argument("--city", help="只搜这一个城市（默认用 config.json 里的全部）")
    a = p.parse_args(argv)

    cfg = store.load_config()
    pages = a.pages if a.pages is not None else int(cfg.get("pages_per_query", 1))
    keywords = [a.keyword] if a.keyword else list(cfg.get("keywords") or [])
    cities = [a.city] if a.city else list(cfg.get("cities") or [""])
    filters = cfg.get("search_filters") or {}

    if not keywords:
        raise SystemExit("❌ config.json 的 keywords 为空")
    if pages < 1:
        raise SystemExit("❌ --pages 至少为 1")

    pool = store.load_pool()
    known = {str(r["jobId"]) for r in pool}
    today = datetime.date.today().strftime("%Y-%m-%d")
    new_rows: list[dict] = []
    skipped = 0

    def flush() -> None:
        if a.dry_run:
            print("(--dry-run：未写池)")
            return
        store.save_pool(pool + new_rows)
        print(f"✅ 已写入 {store.POOL_PATH}")

    for kw in keywords:
        for city in cities:
            for page in range(pages):
                try:
                    raw_list = liepin.search_jobs(kw, city, page, **filters)
                except Exception as e:
                    print(f"❌ 搜索失败（{kw}@{city or '不限'} p{page}）：{e}", file=sys.stderr)
                    # 已经搜到的先入库：额度是响应返回时就花掉的，丢掉等于「付了钱还重付」。
                    # 但退出码保持 1——失败要响亮，不能让人把「没搜完」读成「搜完了」。
                    if new_rows:
                        print(f"⚠️  先保住已搜到的 {len(new_rows)} 条，再退出", file=sys.stderr)
                        flush()
                    return 1
                print(f"🔎 {kw}@{city or '不限'} p{page} → 返回 {len(raw_list)} 条")
                for raw in raw_list:
                    jid = str(raw.get("jobId", "")).strip()
                    if not jid:
                        continue
                    if jid in known:
                        skipped += 1
                        continue
                    known.add(jid)
                    new_rows.append(build_row(raw, kw, city, today))

    total = len(pool) + len(new_rows)
    print(f"\n新增 {len(new_rows)} 条｜去重跳过 {skipped} 条｜池内共 {total} 条")
    flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
