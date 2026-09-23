"""lint 闸门。ruff 找不到就 skip——但 Task 0 把它列为必装，
skip 本身就说明环境没按 Task 0 建，这条别当成「过」。（`-rs` 会显式报 skip 原因。）"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def ruff():
    exe = shutil.which("ruff")
    if exe is None:
        pytest.skip("ruff 未安装：Task 0 第 0 步要求 `uv tool install ruff`")
    return exe


def test_ruff_is_configured():
    assert (ROOT / "ruff.toml").exists(), "没有配置文件，ruff 会用它的全默认而不是我们的"


def test_scripts_and_tests_are_clean(ruff):
    r = subprocess.run([ruff, "check", "scripts", "tests"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, f"ruff 报了问题，先修再提交：\n{r.stdout}{r.stderr}"


def test_the_gate_actually_catches_something(tmp_path, ruff):
    """select 配错、一条规则都没挑中时，「ruff 全绿」是个假信号。
    喂一个它必须拦的东西，证明闸门有牙齿。"""
    bad = tmp_path / "bad.py"
    bad.write_text("import json\n", encoding="utf-8")  # F401：未使用的 import
    r = subprocess.run([ruff, "check", "--config", str(ROOT / "ruff.toml"), str(bad)],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0, "连未使用的 import 都不报，说明 select 没挑中 F"
    assert "F401" in r.stdout
