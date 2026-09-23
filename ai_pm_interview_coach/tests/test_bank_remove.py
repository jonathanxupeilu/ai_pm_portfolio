import store
from support import bank_row, run_cli, write_jsonl

import bank


def test_remove_deletes_exactly_one_row(data_dir):
    write_jsonl(store.BANK_PATH, [bank_row(question="留"), bank_row(question="删")])
    rc, _, err = run_cli(bank.main, ["remove", store.fingerprint("删")])
    assert rc == 0, err
    left = store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    assert [r["question"] for r in left] == ["留"]


def test_remove_unknown_id_changes_nothing(data_dir):
    write_jsonl(store.BANK_PATH, [bank_row(question="留")])
    before = store.BANK_PATH.read_bytes()
    rc, _, err = run_cli(bank.main, ["remove", "ffffffffffff"])
    assert rc == 1
    assert store.BANK_PATH.read_bytes() == before, "找不到 id 就不该动文件"
    assert "没动任何数据" in err


def test_remove_prints_what_it_deleted(data_dir):
    write_jsonl(store.BANK_PATH, [bank_row(question="删这题")])
    rc, out, _ = run_cli(bank.main, ["remove", store.fingerprint("删这题")])
    assert rc == 0
    assert "删这题" in out
