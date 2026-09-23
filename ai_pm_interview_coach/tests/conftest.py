import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """把 store 的两个数据路径 + 配置路径指到 tmp，跑完自动还原。

    不还原会污染同进程其它测试——那是最难查的一类假绿。
    """
    import store

    monkeypatch.setattr(store, "BANK_PATH", tmp_path / "bank" / "questions.jsonl")
    monkeypatch.setattr(store, "ATTEMPTS_PATH", tmp_path / "attempts" / "attempts.jsonl")
    monkeypatch.setattr(store, "CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / "config.json").write_text('{"per_round": 5}', encoding="utf-8")
    return tmp_path


def _snapshot(root: pathlib.Path) -> dict:
    if not root.exists():
        return {"__missing__": True}
    out = {"__missing__": False}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = (p.stat().st_size, p.stat().st_mtime_ns)
    return out


@pytest.fixture(scope="session", autouse=True)
def real_data_untouched():
    """整个测试会话期间，项目内的真 bank/ 与 attempts/ 必须一个字节都不变。

    忘了重定向的测试会在这里现形——不用人去 review 每个用例有没有 leak。
    """
    import store

    targets = [store.ROOT / "bank", store.ROOT / "attempts"]
    before = {str(t): _snapshot(t) for t in targets}
    yield
    for t in targets:
        assert _snapshot(t) == before[str(t)], f"真数据被动过：{t}"
