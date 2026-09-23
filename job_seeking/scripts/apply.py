#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""投递：默认 dry-run 只打印，加 --confirm 才真的投。**外呼不可逆。**

用法：
  uv run --no-project python scripts/apply.py --list shortlists/短名单_YYYYMMDD.csv
  uv run --no-project python scripts/apply.py --list <同名 csv> --confirm

关于判定：`user-apply-job` 的真实返回结构**尚未实测**（投递不可逆，没敢拿真岗位试）。
所以这里打印原始响应全文，并且**只在能判出成功时才记成功**；判不出一律 unknown 且不写台账。
漏记可以人工补，假记会让这个岗位被永久排除。
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys

import liepin
import store

# 先判失败再判成功：「已投递过」里含有「已投递」，顺序反了会把重复投递误判成成功。
FAIL_MARKERS = ("失败", "已结束", "已下线", "已关闭", "重复投递", "不能重复",
                "不可重复", "已投递过", "无法投递", "不满足")
SUCCESS_MARKERS = ("成功", "投递成功", "已投递")


def classify(resp) -> tuple[str, str]:
    """返回 (结论, 命中的标记词)。结论 ∈ 成功 / 失败 / unknown。"""
    text = json.dumps(resp, ensure_ascii=False)
    for mk in FAIL_MARKERS:
        if mk in text:
            return "失败", mk
    for mk in SUCCESS_MARKERS:
        if mk in text:
            return "成功", mk
    return "unknown", ""


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="批量投递（默认 dry-run）")
    p.add_argument("--list", required=True, dest="list_path", help="短名单 csv 路径")
    p.add_argument("--confirm", action="store_true", help="真的投递（不可逆）")
    p.add_argument("--max", type=int, help="本次最多投几个")
    a = p.parse_args(argv)

    cfg = store.load_config()
    limit = a.max if a.max is not None else int(cfg.get("max_per_round", 15))

    path = pathlib.Path(a.list_path)
    if not path.is_absolute():
        path = store.ROOT / path
    if not path.exists():
        raise SystemExit(f"❌ 找不到名单文件：{path}")

    rows = store.read_rows(path, store.SHORTLIST_FIELDS)[:limit]
    applied = store.applied_ids()

    todo, skip_bad, skip_done = [], [], []
    for r in rows:
        jid = str(r.get("jobId", "")).strip()
        kind = str(r.get("jobKind", "")).strip()
        if not jid or not kind:
            skip_bad.append(r)
        elif jid in applied:
            skip_done.append(r)
        else:
            todo.append(r)

    print("=" * 66)
    print(f"短名单投递 ｜ {datetime.date.today()} ｜ "
          f"{'🔴 实投（--confirm）' if a.confirm else '🔵 dry-run 预览（加 --confirm 才真投）'}")
    print(f"名单：{path}")
    print(f"共 {len(rows)} 行 → 将投 {len(todo)}｜跳过 {len(skip_done) + len(skip_bad)}")
    print("=" * 66)
    for r in skip_done:
        print(f"  ⏭️  {r['jobId']} {r.get('jobName', '')} → 台账已记录，跳过")
    for r in skip_bad:
        print(f"  ⛔ {r.get('jobId') or '(无id)'} {r.get('jobName', '')} → 缺 jobId/jobKind，跳过")
    for r in todo:
        print(f"  📮 {r['jobId']} [kind={r['jobKind']}] {r.get('jobName', '')}"
              f" @ {r.get('company', '')}  ({r.get('score', '')}分)")

    if not todo:
        print("\n没有可投项，本批零动作。")
        return 1
    if not a.confirm:
        print("\n(--dry-run：未发起任何投递。确认清单无误后加 --confirm)")
        return 0

    ok = fail = unknown = 0
    unknown_ids: list[str] = []
    for r in todo:
        jid, kind = str(r["jobId"]), str(r["jobKind"])
        try:
            resp = liepin.apply_job(int(jid), kind)
        except Exception as e:
            unknown += 1
            unknown_ids.append(jid)
            print(f"❌ {jid} 调用异常：{e} → unknown（不写台账）")
            continue

        verdict, marker = classify(resp)
        print(f"── {jid} {r.get('jobName', '')} → {verdict}（命中标记：{marker or '无'}）")
        print(f"   原始响应：{json.dumps(resp, ensure_ascii=False)[:600]}")

        if verdict == "unknown":
            unknown += 1
            unknown_ids.append(jid)
            continue

        # 逐行立即落账：中途被打断也不会丢已投记录
        store.append_row(store.LEDGER_PATH, store.LEDGER_FIELDS, {
            "jobId": jid, "jobKind": kind,
            "jobName": r.get("jobName", ""), "company": r.get("company", ""),
            "applyTime": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": verdict,
            "resultText": json.dumps(resp, ensure_ascii=False)[:300],
        })
        if verdict == "成功":
            ok += 1
        else:
            fail += 1

    print(f"\n成功 {ok}｜失败 {fail}｜判不出 {unknown}   → 台账 {store.LEDGER_PATH}")
    if unknown:
        print("⚠️  以下岗位判不出结果，**未写台账**。请到猎聘人工确认后手工补录，")
        print("    否则下一轮会把它们当成没投过，可能重复投：")
        print("    " + ", ".join(unknown_ids))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
