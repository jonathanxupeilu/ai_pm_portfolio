"""把计划里的代码块原样抽成一个可跑的工程，用来验证计划本身。

用法：python build_plan_check.py            # 抽到临时目录并打印路径
     python build_plan_check.py --pytest    # 抽完直接跑 pytest
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

PLAN = pathlib.Path(__file__).with_name("2026-09-23-interview-coach.md")
VENV = (pathlib.Path(__file__).resolve().parent.parent.parent
        / ".venv" / "Scripts" / "python.exe")


def _sections(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    parts = re.split(r"^(## Task \d+：[^\n]*)$", text, flags=re.M)
    for i in range(1, len(parts) - 1, 2):
        key = parts[i].split("：")[0].replace("## ", "")
        out[key] = parts[i + 1]
    return out


def _blocks(section: str) -> list[str]:
    return re.findall(r"```python\n(.*?)```", section, flags=re.S)


def assemble(dest: pathlib.Path) -> list[str]:
    notes: list[str] = []
    sec = _sections(PLAN.read_text(encoding="utf-8"))
    (dest / "scripts").mkdir(exist_ok=True)
    (dest / "tests").mkdir(exist_ok=True)

    w = dest / "tests" / "conftest.py"
    w.write_text(_blocks(sec["Task 0"])[0], encoding="utf-8")
    (dest / "tests" / "support.py").write_text(
        "\n\n".join(_blocks(sec["Task 1"])), encoding="utf-8")
    (dest / "config.json").write_text('{"per_round": 5}', encoding="utf-8")
    toml = re.findall(r"```toml\n(.*?)```", sec["Task 0"], flags=re.S)
    if not toml:
        notes.append("Task 0 里没找到 toml 块——ruff.toml 没落地，lint 闸门测的是默认配置")
    else:
        (dest / "ruff.toml").write_text(toml[0], encoding="utf-8")

    t2 = _blocks(sec["Task 2"])
    (dest / "tests" / "test_models.py").write_text(t2[0], encoding="utf-8")
    # models.py = 模型定义 + 解析函数；两个 FIELDS 常量在计划里是分开写的
    (dest / "scripts" / "models.py").write_text(
        t2[1].rstrip() + "\n\n\n" + t2[2].strip()
        + "\n\n\nBANK_FIELDS = tuple(BankRow.model_fields)\n"
        "ATTEMPT_FIELDS = tuple(AttemptRow.model_fields)\n", encoding="utf-8")

    t3 = _blocks(sec["Task 3"])
    (dest / "tests" / "test_store.py").write_text(t3[0], encoding="utf-8")
    (dest / "scripts" / "store.py").write_text(t3[1], encoding="utf-8")

    t4 = _blocks(sec["Task 4"])
    (dest / "tests" / "test_bank_add.py").write_text(t4[0], encoding="utf-8")
    (dest / "scripts" / "bank.py").write_text(t4[1], encoding="utf-8")

    # Task 5：三个测试文件 + 往 bank.py 里插实现和 subparser
    t5 = _blocks(sec["Task 5"])
    for name, src in zip(("test_bank_list.py", "test_bank_remove.py",
                          "test_bank_sample.py"), t5[:3], strict=True):
        (dest / "tests" / name).write_text(src, encoding="utf-8")
    bank = (dest / "scripts" / "bank.py").read_text(encoding="utf-8")
    bank = bank.replace("\ndef main(argv", t5[3].rstrip() + "\n\n\ndef main(argv", 1)
    bank = bank.replace("    args = p.parse_args(argv)",
                        t5[4].rstrip() + "\n    args = p.parse_args(argv)", 1)
    if "import random" not in bank:
        bank = bank.replace("import sys", "import random\nimport sys", 1)
    (dest / "scripts" / "bank.py").write_text(bank, encoding="utf-8")

    t6 = _blocks(sec["Task 6"])
    (dest / "tests" / "test_resume_config.py").write_text(t6[0], encoding="utf-8")
    (dest / "scripts" / "resume.py").write_text(t6[1], encoding="utf-8")

    t7 = _blocks(sec["Task 7"])
    (dest / "tests" / "fake_mcp.py").write_text(t7[0], encoding="utf-8")
    (dest / "tests" / "test_resume_integration.py").write_text(t7[1], encoding="utf-8")

    t8 = _blocks(sec["Task 8"])
    (dest / "tests" / "test_attempts.py").write_text(t8[0], encoding="utf-8")
    (dest / "scripts" / "attempts.py").write_text(t8[1], encoding="utf-8")

    # Task 9：store.py 换成环境变量版 + conftest 加守卫 + e2e
    t9 = _blocks(sec["Task 9"])
    sp = (dest / "scripts" / "store.py")
    s = sp.read_text(encoding="utf-8")
    old = ('BANK_PATH = ROOT / "bank" / "questions.jsonl"\n'
           'ATTEMPTS_PATH = ROOT / "attempts" / "attempts.jsonl"\n'
           'CONFIG_PATH = ROOT / "config.json"\n')
    if old not in s:
        notes.append("Task 9 的 store 常量替换没找到——计划里那段改过了")
    else:
        s = s.replace(old, t9[1].strip() + "\n", 1)
        sp.write_text(s, encoding="utf-8")
    cp = (dest / "tests" / "conftest.py")
    cp.write_text(cp.read_text(encoding="utf-8").rstrip() + "\n\n\n"
                  + t9[2].strip() + "\n", encoding="utf-8")
    (dest / "tests" / "test_e2e.py").write_text(t9[0], encoding="utf-8")

    t10 = _blocks(sec["Task 10"])
    (dest / "tests" / "test_lint.py").write_text(t10[0], encoding="utf-8")
    # Task 10 的闸门范围含 docs/plans 下这两个脚本。抽验工程里也得有它们，
    # 否则「验证工具自己游离在被验证之外」正是那条测试要拦的事——而它会红。
    plans_dir = dest / "docs" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    here = pathlib.Path(__file__).resolve().parent
    for src in sorted(here.glob("*.py")):
        shutil.copy2(src, plans_dir / src.name)
    return notes


def main() -> int:
    dest = pathlib.Path(tempfile.mkdtemp(prefix="coach-plan-check-"))
    notes = assemble(dest)
    for n in notes:
        print("⚠️ ", n)
    print("assembled ->", dest)
    if "--pytest" in sys.argv:
        rc = subprocess.run([str(VENV), "-m", "pytest", str(dest / "tests"), "-q"],
                            cwd=dest, env={**os.environ, "PYTHONUTF8": "1"},
                            text=True).returncode
        return rc
    print("跑：", VENV, "-m pytest", dest / "tests -q")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
