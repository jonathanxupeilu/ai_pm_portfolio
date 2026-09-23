#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""岗位池与投递台账的读写（共享模块）。

**台账是投递去重的唯一真源**：shortlist.py 和 apply.py 都靠 `applied_ids()` 判断
某个岗位是否已经投过。这个判断只在这里定义一次——两处各写一份迟早会漂移，
而漂移的后果是重复投递（不可逆）。

CSV 一律写不带 BOM 的 utf-8，读的时候容忍 BOM。
"""
from __future__ import annotations

import csv
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
POOL_PATH = ROOT / "pool" / "jobs.csv"
LEDGER_PATH = ROOT / "ledger.csv"
CONFIG_PATH = ROOT / "config.json"
CRITERIA_PATH = ROOT / "criteria.md"
SHORTLIST_DIR = ROOT / "shortlists"

POOL_FIELDS = [
    "jobId", "jobType", "jobName", "company", "location", "salary",
    "education", "workYears", "industry", "companyTags", "financingStage",
    "companySize", "jobDetailUrl",
    "score", "hits",                      # 打分结果（score 为空 = 还没打分）
    "criteriaFp",                         # 这个分数是按哪一版口径算的（见 matcher.fingerprint）
    "searchKeyword", "searchCity", "foundAt",
]

LEDGER_FIELDS = ["jobId", "jobKind", "jobName", "company", "applyTime", "status", "resultText"]

SHORTLIST_FIELDS = [
    "jobId", "jobKind", "jobName", "company", "salary", "location",
    "score", "hits", "jobDetailUrl",
]


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"❌ 找不到配置文件：{CONFIG_PATH}")
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"❌ config.json 不是合法 JSON：{e}") from None


def read_rows(path: pathlib.Path, fields: list[str]) -> list[dict]:
    """读 CSV；文件不存在返回空表（首次运行时是正常状态，不是错误）。"""
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != fields:
            raise SystemExit(
                f"❌ {path.name} 的表头与预期不符——拒绝继续（列对不上会让数据串列）。\n"
                f"   实际：{reader.fieldnames}\n   预期：{fields}"
            )
        return [dict(r) for r in reader]


def write_rows(path: pathlib.Path, fields: list[str], rows: list[dict]) -> None:
    # 缺列一律拦下来：DictWriter 的 extrasaction="ignore" 只忽略「多余」的键，
    # 少了的键会被**静默写成空值**——空 jobKind 会让整批投递被跳过而没人报错。
    for i, r in enumerate(rows, 1):
        missing = [f for f in fields if f not in r]
        if missing:
            raise SystemExit(
                f"❌ 写 {path.name} 时第 {i} 行缺列 {missing}——"
                f"拒绝写入（缺列会被静默写成空，这里宁可停下）"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def append_row(path: pathlib.Path, fields: list[str], row: dict) -> None:
    """追加一行。投递时逐行调用，中途被打断也不丢已投记录。"""
    exists = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def load_pool() -> list[dict]:
    return read_rows(POOL_PATH, POOL_FIELDS)


def save_pool(rows: list[dict]) -> None:
    write_rows(POOL_PATH, POOL_FIELDS, rows)


def load_ledger() -> list[dict]:
    return read_rows(LEDGER_PATH, LEDGER_FIELDS)


def applied_ids() -> set[str]:
    """台账里出现过的 jobId 一律视为已投/已处理，不再出名单、不再投。"""
    return {str(r.get("jobId", "")).strip() for r in load_ledger() if r.get("jobId")}
