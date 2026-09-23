#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""筛选第三步：出短名单（按匹配度降序、排除已投、截断）。**不投递。**

用法：
  uv run --no-project python scripts/shortlist.py [--max N]

每一层挡掉了几个岗位都会打印出来——静默过滤等于静默漏岗。
"""
from __future__ import annotations

import argparse
import datetime
import sys

import store


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="出短名单")
    p.add_argument("--max", type=int,
                   help="本轮最多几个（默认取 config.json 的 max_per_round）")
    a = p.parse_args(argv)

    cfg = store.load_config()
    limit = a.max if a.max is not None else int(cfg.get("max_per_round", 15))

    rows = store.load_pool()
    if not rows:
        # 没出名单就是没出名单，退出码不带「池子空所以算成功」的例外——
        # 否则任何检查退出码的调用方都会把「什么都没生成」读成「已生成」。
        print("池子是空的，先跑 search.py")
        return 1

    applied = store.applied_ids()
    unscored = [r for r in rows if not str(r.get("score", "")).strip()]
    scored = [r for r in rows if str(r.get("score", "")).strip()]
    no_kind = [r for r in scored if not str(r.get("jobType", "")).strip()]
    already = [r for r in scored if str(r["jobId"]) in applied]

    eligible = [
        r for r in scored
        if str(r["jobId"]) not in applied and str(r.get("jobType", "")).strip()
    ]
    eligible.sort(key=lambda r: float(r["score"]), reverse=True)
    picked = eligible[:limit]

    print(f"池内 {len(rows)} 个 → 未打分 {len(unscored)}｜缺 jobKind {len(no_kind)}"
          f"｜已投 {len(already)} → 可出名单 {len(eligible)}")
    for r in no_kind:
        print(f"   ⚠️  缺 jobKind 已剔除：{r['jobId']} {r.get('jobName', '')}"
              f"（jobKind 必须来自搜索结果的 jobType，不猜值）")

    if not picked:
        print("没有可出的名单——先补打分（score.py）或再搜岗（search.py）")
        return 1

    today = datetime.date.today().strftime("%Y%m%d")
    store.SHORTLIST_DIR.mkdir(parents=True, exist_ok=True)
    md_path = store.SHORTLIST_DIR / f"短名单_{today}.md"
    csv_path = store.SHORTLIST_DIR / f"短名单_{today}.csv"
    # 必须显式改名：池里存的是搜索返回的 jobType，投递接口要的参数名叫 jobKind。
    # 直接扔池行进去会「静默」丢掉 jobKind 那一列（DictWriter 缺列写空值），
    # 结果是名单 15 行、apply 一看全缺 jobKind、整批跳过——2026-09-23 实测踩到过一次。
    picked_rows = [{
        "jobId": r["jobId"],
        "jobKind": r["jobType"],
        "jobName": r.get("jobName", ""),
        "company": r.get("company", ""),
        "salary": r.get("salary", ""),
        "location": r.get("location", ""),
        "score": r.get("score", ""),
        "hits": r.get("hits", ""),
        "jobDetailUrl": r.get("jobDetailUrl", ""),
    } for r in picked]
    store.write_rows(csv_path, store.SHORTLIST_FIELDS, picked_rows)

    lines = [
        f"# 短名单 {today}", "",
        f"共 {len(picked)} 个（按匹配度降序）｜池内 {len(rows)} 个，"
        f"已排除：未打分 {len(unscored)}、缺 jobKind {len(no_kind)}、已投 {len(already)}", "",
        "| # | 匹配度 | 岗位 | 公司 | 薪资 | 地点 | 命中词 |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(picked, 1):
        hits = str(r.get("hits", "")).replace("|", "、") or "—"
        lines.append(
            f"| {i} | {r['score']} | {r.get('jobName', '')} | {r.get('company', '')} "
            f"| {r.get('salary', '')} | {r.get('location', '')} | {hits} |"
        )

    try:
        rel_csv = csv_path.relative_to(store.ROOT).as_posix()
    except ValueError:
        # 名单目录不在仓库根下时（测试/自定义路径）退化成绝对路径——
        # 打印出来的命令必须能直接粘去跑，不能因为缩写路径而崩掉。
        rel_csv = str(csv_path)
    lines += [
        "", "## 下一步：投递", "",
        "先看 dry-run 清单，确认无误后再加 `--confirm`：", "```bash",
        f"uv run --no-project python scripts/apply.py --list {rel_csv}",
        f"uv run --no-project python scripts/apply.py --list {rel_csv} --confirm",
        "```", "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"✅ 已生成：\n   {md_path}\n   {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
