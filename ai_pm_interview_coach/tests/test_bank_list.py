import store
from support import bank_row, run_cli, write_jsonl

import bank


def test_list_reports_total_count(data_dir):
    write_jsonl(store.BANK_PATH, [bank_row(question=f"题{i}") for i in range(3)])
    rc, out, err = run_cli(bank.main, ["list"])
    assert rc == 0, err
    assert "题库共 3 题" in out


def test_empty_bank_list_is_not_an_error(data_dir):
    rc, out, err = run_cli(bank.main, ["list"])
    assert rc == 0, err
    assert "题库共 0 题" in out


def test_each_question_is_one_line_even_if_multiline(data_dir):
    """一行一题是 list 的契约——题面带换行也不能把列表撑坏。"""
    write_jsonl(store.BANK_PATH, [bank_row(question="第一行\n第二行\n第三行")])
    rc, out, err = run_cli(bank.main, ["list"])
    assert rc == 0, err
    body = [ln for ln in out.splitlines() if ln.strip() and "题库共" not in ln]
    assert len(body) == 1


def test_list_shows_id_kind_target(data_dir):
    write_jsonl(store.BANK_PATH,
                [bank_row(question="题九", kind="简历深挖", target="AI产品经理")])
    rc, out, err = run_cli(bank.main, ["list"])
    assert rc == 0, err
    assert store.fingerprint("题九") in out
    assert "简历深挖" in out and "AI产品经理" in out


def test_list_bad_file_is_error(data_dir):
    store.BANK_PATH.parent.mkdir(parents=True, exist_ok=True)
    store.BANK_PATH.write_text("{坏\n", encoding="utf-8")
    rc, _, err = run_cli(bank.main, ["list"])
    assert rc == 1
    assert "第 1 行" in err
