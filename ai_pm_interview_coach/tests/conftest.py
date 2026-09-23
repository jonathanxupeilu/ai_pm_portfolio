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
