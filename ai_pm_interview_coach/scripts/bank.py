"""题库命令行。

  bank.py add          从 stdin 读一个 JSON 对象，存一题
  bank.py show <id>    打印整题
  bank.py list         一行一题列出来
  bank.py remove <id>  删一题
  bank.py sample       抽本轮的题

只存确定性事实。搜什么、出什么题、判得对不对，都不在这个脚本里。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys

import models
import store


def _fail(msg: str) -> int:
    print(f"❌ {msg}", file=sys.stderr)
    return 1


def cmd_add(_args) -> int:
    try:
        payload = models.parse_input(models.BankInput, sys.stdin.read(), src="stdin")
    except models.InputError as e:
        return _fail(str(e))

    qid = store.fingerprint(payload.question)
    try:
        existing = store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    except ValueError as e:
        return _fail(str(e))
    if any(r["id"] == qid for r in existing):
        return _fail(f"已存在同指纹题（id={qid}），不覆盖——先 remove 再 add，或人工合并")

    store.append_row(store.BANK_PATH, {
        "id": qid,
        "question": payload.question,
        "refAnswer": payload.refAnswer,
        "kind": payload.kind,
        "target": payload.target,
        "source": payload.source,
        "addedAt": dt.date.today().isoformat(),
    }, store.BANK_FIELDS)
    print(qid)
    return 0


def cmd_show(args) -> int:
    try:
        rows = store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    except ValueError as e:
        return _fail(str(e))
    for r in rows:
        if r["id"] == args.id:
            print(json.dumps(r, ensure_ascii=False, indent=2))
            return 0
    return _fail(f"题库里没有 id={args.id}（bank.py list 看全量）")


def _filtered(kind, target) -> list[dict]:
    rows = store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    if target:
        rows = [r for r in rows if r["target"] == target]
    return rows


def cmd_list(_args) -> int:
    try:
        rows = store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    except ValueError as e:
        return _fail(str(e))
    print(f"题库共 {len(rows)} 题")
    for r in rows:
        one_line = " ".join(r["question"].split())[:60]
        tgt = f" [{r['target']}]" if r["target"] else ""
        print(f"{r['id']}  {r['kind']}{tgt}  {one_line}")
    return 0


def cmd_remove(args) -> int:
    try:
        rows = store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    except ValueError as e:
        return _fail(str(e))
    keep = [r for r in rows if r["id"] != args.id]
    if len(keep) == len(rows):
        return _fail(f"题库里没有 id={args.id}，没动任何数据")
    gone = next(r for r in rows if r["id"] == args.id)
    store.write_rows(store.BANK_PATH, keep, store.BANK_FIELDS)
    print(f"已删 {gone['id']}  {gone['kind']}  {' '.join(gone['question'].split())[:60]}")
    return 0


def cmd_sample(args) -> int:
    try:
        cfg = store.load_config()
    except (FileNotFoundError, ValueError) as e:
        return _fail(str(e))
    n = args.n if args.n is not None else cfg.get("per_round")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        return _fail(f"-n / per_round 要是 ≥1 的整数，现在是 {n!r}")

    try:
        pool = _filtered(args.kind, args.target)
        if args.fresh:
            seen = {r["qid"] for r in
                    store.read_rows(store.ATTEMPTS_PATH, store.ATTEMPT_FIELDS)}
            pool = [r for r in pool if r["id"] not in seen]
    except ValueError as e:
        return _fail(str(e))

    if not pool:
        return _fail("没有可出的题——题库空（或筛选 / --fresh 之后没剩），不是成功")

    rng = random.Random(args.seed) if args.seed is not None else random.SystemRandom()
    for r in rng.sample(pool, min(n, len(pool))):
        print(r["id"])
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="bank.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="从 stdin 存一题")
    a.set_defaults(fn=cmd_add)
    s = sub.add_parser("show", help="按 id 看一题")
    s.add_argument("id")
    s.set_defaults(fn=cmd_show)
    l = sub.add_parser("list", help="一行一题列出来")
    l.set_defaults(fn=cmd_list)
    rm = sub.add_parser("remove", help="按 id 删一题")
    rm.add_argument("id")
    rm.set_defaults(fn=cmd_remove)
    sp = sub.add_parser("sample", help="抽本轮的题（只出 id）")
    sp.add_argument("-n", type=int, default=None)
    sp.add_argument("--seed", type=int, default=None)
    sp.add_argument("--kind", choices=store.KINDS, default=None)
    sp.add_argument("--target", default=None)
    sp.add_argument("--fresh", action="store_true", help="排除答过的题")
    sp.set_defaults(fn=cmd_sample)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
