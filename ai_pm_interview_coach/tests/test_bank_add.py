import json

import bank
import store
from support import bank_row, run_cli, write_jsonl


def add(payload) -> tuple[int, str, str]:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return run_cli(bank.main, ["add"], stdin_text=text)


def test_add_writes_one_row_with_generated_id(data_dir):
    rc, _, err = add({
        "question": "你怎么定义产品成功指标？",
        "refAnswer": "北极星指标往下拆到埋点。",
        "kind": "通用",
        "source": "2026 牛客面经",
    })
    assert rc == 0, err
    rows = store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    assert len(rows) == 1
    assert rows[0]["id"] == store.fingerprint("你怎么定义产品成功指标？")
    assert rows[0]["target"] == ""
    assert len(rows[0]["addedAt"]) == 10 and rows[0]["addedAt"][4] == "-"


def test_add_prints_the_id_so_i_can_reference_it(data_dir):
    rc, out, err = add({"question": "题一", "refAnswer": "答", "kind": "通用", "source": "s"})
    assert rc == 0, err
    assert store.fingerprint("题一") in out


def test_duplicate_fingerprint_refused_not_overwritten(data_dir):
    assert add({"question": "同一道题", "refAnswer": "原答案",
                "kind": "通用", "source": "s1"})[0] == 0
    before = store.BANK_PATH.read_bytes()

    rc, _, err = add({"question": "同一道题", "refAnswer": "想覆盖的新答案",
                      "kind": "通用", "source": "s2"})
    assert rc == 1
    assert store.BANK_PATH.read_bytes() == before, "拒绝就必须一个字节都不动"
    assert "不覆盖" in err


def test_whitespace_variant_counts_as_duplicate(data_dir):
    assert add({"question": "同一道题", "refAnswer": "答",
                "kind": "通用", "source": "s"})[0] == 0
    rc, _, _ = add({"question": "  同一道题  ", "refAnswer": "答",
                    "kind": "通用", "source": "s"})
    assert rc == 1


def test_blank_required_field_rejected(data_dir):
    rc, _, err = add({"question": "   ", "refAnswer": "答",
                      "kind": "通用", "source": "s"})
    assert rc == 1
    assert "question" in err


def test_kind_out_of_whitelist_rejected(data_dir):
    rc, _, err = add({"question": "题", "refAnswer": "答",
                      "kind": "瞎写", "source": "s"})
    assert rc == 1
    assert "简历深挖" in err, "报错要把合法值告回来"


def test_empty_stdin_is_error(data_dir):
    rc, _, err = add("")
    assert rc == 1
    assert "stdin" in err


def test_show_prints_whole_row(data_dir):
    write_jsonl(store.BANK_PATH, [bank_row(question="题二")])
    qid = store.fingerprint("题二")
    rc, out, err = run_cli(bank.main, ["show", qid])
    assert rc == 0, err
    row = json.loads(out)
    assert row["question"] == "题二" and row["id"] == qid


def test_show_unknown_id_is_error(data_dir):
    write_jsonl(store.BANK_PATH, [bank_row()])
    rc, _, err = run_cli(bank.main, ["show", "ffffffffffff"])
    assert rc == 1
    assert "ffffffffffff" in err
