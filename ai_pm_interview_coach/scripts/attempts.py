"""答题留痕。

  attempts.py record            从 stdin 读 {qid, answer, verdict, feedback}，追加一条
  attempts.py history [qid]     看记录（不给 qid 就全量）
  attempts.py weak              错过且最后一次没答对的题，按错过次数降序

只留痕，不排复习计划——「什么时候再练」不是这里决定的。
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

import models
import store


def _fail(msg: str) -> int:
    print(f"❌ {msg}", file=sys.stderr)
    return 1


def _bank_ids() -> set[str]:
    return {r["id"] for r in store.read_rows(store.BANK_PATH, store.BANK_FIELDS)}


def _read_attempts() -> list[dict]:
    return store.read_rows(store.ATTEMPTS_PATH, store.ATTEMPT_FIELDS)


def cmd_record(_args) -> int:
    try:
        payload = models.parse_input(models.AttemptInput, sys.stdin.read(), src="stdin")
    except models.InputError as e:
        return _fail(str(e))

    try:
        if payload.qid not in _bank_ids():
            return _fail(f"题库里没有 id={payload.qid}，这条记录将来查不到对应题目，不记")
    except ValueError as e:
        return _fail(str(e))

    at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    store.append_row(store.ATTEMPTS_PATH, {
        "at": at,
        "qid": payload.qid,
        "answer": payload.answer,
        "verdict": payload.verdict,
        "feedback": payload.feedback,
    }, store.ATTEMPT_FIELDS)
    print(f"已记录 {payload.verdict}  {payload.qid}")
    return 0


def cmd_history(args) -> int:
    try:
        rows = _read_attempts()
        questions = {r["id"]: r["question"] for r in
                     store.read_rows(store.BANK_PATH, store.BANK_FIELDS)}
    except ValueError as e:
        return _fail(str(e))

    if args.qid:
        rows = [r for r in rows if r["qid"] == args.qid]
        if not rows:
            return _fail(f"id={args.qid} 没答过——不是失败，但也没东西可看")
    print(f"共 {len(rows)} 条")
    for r in rows:
        q = questions.get(r["qid"], "（题已从题库删除）")
        one_line = " ".join(q.split())[:40]
        print(f"{r['at']}  {r['verdict']:<4}  {r['qid']}  {one_line}")
        print(f"    答：{' '.join(r['answer'].split())[:80]}")
        if r["feedback"]:
            print(f"    评：{' '.join(r['feedback'].split())[:80]}")
    return 0


def cmd_weak(_args) -> int:
    try:
        rows = _read_attempts()
    except ValueError as e:
        return _fail(str(e))
    if not rows:
        return _fail("还没有答过的题——没有弱项可列，不是成功")

    by_q: dict[str, list[dict]] = {}
    for r in rows:
        by_q.setdefault(r["qid"], []).append(r)

    try:
        questions = {r["id"]: r["question"] for r in
                     store.read_rows(store.BANK_PATH, store.BANK_FIELDS)}
    except ValueError as e:
        return _fail(str(e))

    weak = []
    for qid, recs in by_q.items():
        misses = sum(1 for r in recs if r["verdict"] in ("错", "部分对"))
        if misses and recs[-1]["verdict"] != "对":
            weak.append((misses, qid, recs[-1]["at"]))
    if not weak:
        return _fail("没有弱项——全部答对，不是失败但也没得练")

    weak.sort(key=lambda t: (-t[0], t[2]))
    for misses, qid, _last in weak:
        q = " ".join(questions.get(qid, "（题已从题库删除）").split())[:60]
        print(f"{misses} 次  {qid}  {q}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="attempts.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="从 stdin 记一条答题")
    r.set_defaults(fn=cmd_record)
    h = sub.add_parser("history", help="看答题记录")
    h.add_argument("qid", nargs="?")
    h.set_defaults(fn=cmd_history)
    w = sub.add_parser("weak", help="列出弱项")
    w.set_defaults(fn=cmd_weak)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except ValueError as e:
        return _fail(str(e))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
