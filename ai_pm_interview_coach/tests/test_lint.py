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
    """闸门范围 = 所有会执行代码的地方，含 docs/plans 下那两个计划辅助脚本。

    计划本身是要被抽出来跑的（`build_plan_check.py`），它不干净就等于
    「验证工具自己游离在被验证之外」。范围悄悄变小由下一条 assert 兜住。
    """
    helpers = sorted((ROOT / "docs" / "plans").glob("*.py"))
    assert helpers, "docs/plans 下的计划辅助脚本没被发现——闸门范围在无声缩小"
    r = subprocess.run(
        [ruff, "check", "scripts", "tests", *(str(p.relative_to(ROOT)) for p in helpers)],
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
