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


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="bank.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="从 stdin 存一题")
    a.set_defaults(fn=cmd_add)
    s = sub.add_parser("show", help="按 id 看一题")
    s.add_argument("id")
    s.set_defaults(fn=cmd_show)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
