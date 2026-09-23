"""按计划文件的行号做定点替换（带原文断言），避免全局 replace 打错地方。

用法：python patch_lines.py rules.json
rules.json: [{"line": 1287, "expect": "…", "replace": ["行1", "行2"]}, …]
行号 1 起；必须按行号降序给出，否则前面的插入会让后面的行号错位。
"""
import json
import pathlib
import sys

PLAN = pathlib.Path(__file__).with_name("2026-09-23-interview-coach.md")


def main() -> int:
    rules = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    lines = PLAN.read_text(encoding="utf-8").splitlines(keepends=True)
    prev = None
    for r in rules:
        n = r["line"]
        if prev is not None and n >= prev:
            raise SystemExit(f"行号必须降序：{n} 在 {prev} 之后")
        prev = n
        old = lines[n - 1]
        if r["expect"] not in old:
            raise SystemExit(f"第 {n} 行不是预期内容：{old!r}")
        nl = "\n" if old.endswith("\n") else ""
        body = [x + "\n" for x in r["replace"]]
        body[-1] = body[-1].rstrip("\n") + nl
        lines[n - 1:n] = body
    PLAN.write_text("".join(lines), encoding="utf-8")
    print(f"ok: {len(rules)} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
