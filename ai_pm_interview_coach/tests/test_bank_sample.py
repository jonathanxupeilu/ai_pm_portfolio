import pytest
import store
from support import attempt_row, bank_row, run_cli, write_jsonl

import bank


def seed_bank(n: int) -> list[str]:
    rows = [bank_row(question=f"题{i}") for i in range(n)]
    write_jsonl(store.BANK_PATH, rows)
    return [r["id"] for r in rows]


def ids_of(out: str) -> list[str]:
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def row_by_id(qid: str) -> dict:
    return next(r for r in store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
                if r["id"] == qid)


def test_sample_default_n_from_config(data_dir):
    seed_bank(20)
    rc, out, err = run_cli(bank.main, ["sample"])
    assert rc == 0, err
    assert len(ids_of(out)) == 5, "config.json: per_round = 5"


def test_sample_explicit_n(data_dir):
    seed_bank(20)
    rc, out, _ = run_cli(bank.main, ["sample", "-n", "3"])
    assert rc == 0
    assert len(ids_of(out)) == 3


def test_n_larger_than_bank_returns_all_not_an_error(data_dir):
    seed_bank(2)
    rc, out, _ = run_cli(bank.main, ["sample", "-n", "10"])
    assert rc == 0
    assert len(ids_of(out)) == 2


def test_seed_makes_it_reproducible(data_dir):
    seed_bank(20)
    a = ids_of(run_cli(bank.main, ["sample", "-n", "5", "--seed", "42"])[1])
    b = ids_of(run_cli(bank.main, ["sample", "-n", "5", "--seed", "42"])[1])
    c = ids_of(run_cli(bank.main, ["sample", "-n", "5", "--seed", "43"])[1])
    assert a == b and len(set(a)) == 5
    assert a != c


def test_filter_by_kind(data_dir):
    write_jsonl(store.BANK_PATH, [
        bank_row(question="深挖1", kind="简历深挖"),
        bank_row(question="深挖2", kind="简历深挖"),
        bank_row(question="通用1", kind="通用"),
    ])
    rc, out, _ = run_cli(bank.main, ["sample", "-n", "5", "--kind", "简历深挖"])
    assert rc == 0
    got = ids_of(out)
    assert len(got) == 2
    assert all(row_by_id(i)["kind"] == "简历深挖" for i in got)


def test_filter_by_target(data_dir):
    write_jsonl(store.BANK_PATH, [
        bank_row(question="A", target="AI产品经理"),
        bank_row(question="B", target="数据产品经理"),
    ])
    rc, out, err = run_cli(bank.main, ["sample", "--target", "AI产品经理"])
    assert rc == 0, err
    assert ids_of(out) == [store.fingerprint("A")]


def test_fresh_excludes_already_answered(data_dir):
    ids = seed_bank(5)
    write_jsonl(store.ATTEMPTS_PATH, [attempt_row(ids[0]), attempt_row(ids[1])])
    rc, out, err = run_cli(bank.main, ["sample", "-n", "5", "--fresh"])
    assert rc == 0, err
    assert set(ids_of(out)) == set(ids[2:])


def test_empty_bank_is_not_success(data_dir):
    rc, _, err = run_cli(bank.main, ["sample"])
    assert rc == 1
    assert "没有可出的题" in err


def test_filter_matching_nothing_is_not_success(data_dir):
    seed_bank(3)
    rc, _, err = run_cli(bank.main, ["sample", "--kind", "岗位场景"])
    assert rc == 1
    assert "没有可出的题" in err


def test_fresh_when_all_answered_is_not_success(data_dir):
    ids = seed_bank(2)
    write_jsonl(store.ATTEMPTS_PATH, [attempt_row(i) for i in ids])
    rc, _, err = run_cli(bank.main, ["sample", "--fresh"])
    assert rc == 1
    assert "没有可出的题" in err


def test_n_must_be_positive(data_dir):
    seed_bank(5)
    for bad in ("0", "-1"):
        rc, _, _ = run_cli(bank.main, ["sample", "-n", bad])
        assert rc != 0, f"n={bad} 不该被接受"


def test_kind_outside_whitelist_is_rejected(data_dir):
    seed_bank(3)
    rc, _, _ = run_cli(bank.main, ["sample", "--kind", "瞎写"])
    assert rc != 0


@pytest.mark.parametrize("bad", ['"5"', "true", "0", "null", "1.5", "{}"])
def test_config_per_round_is_type_checked(bad, data_dir):
    """`-n` 有 argparse 兜着，`per_round` 只有 `cmd_sample` 那一句守着。

    不喂坏值就是没测：那句 `isinstance` 一旦被人「简化」成 `int(cfg[...])`，
    true / null / {} 都会悄悄变成一个能抽题的数。
    """
    store.CONFIG_PATH.write_text(f'{{"per_round": {bad}}}', encoding="utf-8")
    seed_bank(5)
    rc, _, err = run_cli(bank.main, ["sample"])
    assert rc == 1
    assert "per_round" in err
