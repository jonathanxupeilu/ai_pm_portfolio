"""真起子进程跑一整轮。这层验证的是「接缝」，不是单个命令。"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"


def run(script: str, *args: str, env: dict, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        input=stdin, capture_output=True, text=True, encoding="utf-8",
        env=env, timeout=60,
    )


@pytest.fixture
def sandbox(tmp_path):
    """把三个数据路径用环境变量指到 tmp——真 bank/ 一个字节都碰不到。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["COACH_BANK_PATH"] = str(tmp_path / "bank" / "questions.jsonl")
    env["COACH_ATTEMPTS_PATH"] = str(tmp_path / "attempts" / "attempts.jsonl")
    env["COACH_CONFIG"] = str(tmp_path / "config.json")
    (tmp_path / "config.json").write_text('{"per_round": 2}', encoding="utf-8")
    return env


def test_full_round_trip(sandbox):
    """一条链：存题 → 抽题 → 看题 → 记一条 → 看历史 → 列弱项。"""
    for i in range(3):
        r = run("bank.py", "add", env=sandbox, stdin=json.dumps({
            "question": f"题{i}", "refAnswer": f"答{i}",
            "kind": "通用", "source": "e2e",
        }, ensure_ascii=False))
        assert r.returncode == 0, r.stderr

    r = run("bank.py", "sample", "-n", "2", "--seed", "7", env=sandbox)
    assert r.returncode == 0, r.stderr
    picked = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(picked) == 2

    r = run("bank.py", "show", picked[0], env=sandbox)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["id"] == picked[0]

    r = run("attempts.py", "record", env=sandbox, stdin=json.dumps({
        "qid": picked[0], "answer": "我的答", "verdict": "错", "feedback": "没成体系",
    }, ensure_ascii=False))
    assert r.returncode == 0, r.stderr

    r = run("attempts.py", "history", picked[0], env=sandbox)
    assert r.returncode == 0, r.stderr
    assert "错" in r.stdout

    r = run("attempts.py", "weak", env=sandbox)
    assert r.returncode == 0, r.stderr
    assert picked[0] in r.stdout

    # --fresh 现在该把答过的那题排掉
    r = run("bank.py", "sample", "-n", "5", "--fresh", env=sandbox)
    assert picked[0] not in r.stdout.split()


def test_stderr_is_utf8_not_mojibake(sandbox, tmp_path):
    """Windows 上最容易翻车的：中文错误信息进 stderr。"""
    r = run("bank.py", "add", env=sandbox, stdin="{}")
    assert r.returncode == 1
    assert "question" in r.stderr


def test_duplicate_add_via_subprocess_also_refused(sandbox):
    payload = json.dumps({"question": "同题", "refAnswer": "答",
                          "kind": "通用", "source": "s"}, ensure_ascii=False)
    assert run("bank.py", "add", env=sandbox, stdin=payload).returncode == 0
    bank_file = pathlib.Path(sandbox["COACH_BANK_PATH"])
    before = bank_file.read_bytes()
    r = run("bank.py", "add", env=sandbox, stdin=payload)
    assert r.returncode == 1
    assert bank_file.read_bytes() == before
