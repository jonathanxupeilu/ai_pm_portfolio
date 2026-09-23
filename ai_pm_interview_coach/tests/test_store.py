import json

import pytest

import store
from support import bank_row, write_jsonl


def test_read_empty_bank_when_file_missing(data_dir):
    assert store.read_rows(store.BANK_PATH, store.BANK_FIELDS) == []


def test_append_then_read_roundtrips(data_dir):
    row = bank_row()
    store.append_row(store.BANK_PATH, row, store.BANK_FIELDS)
    assert store.read_rows(store.BANK_PATH, store.BANK_FIELDS) == [row]


def test_append_creates_parent_dir(data_dir):
    assert not store.BANK_PATH.parent.exists()
    store.append_row(store.BANK_PATH, bank_row(), store.BANK_FIELDS)
    assert store.BANK_PATH.parent.is_dir()


def test_blank_line_is_tolerated(data_dir):
    store.append_row(store.BANK_PATH, bank_row(), store.BANK_FIELDS)
    text = store.BANK_PATH.read_text(encoding="utf-8")
    store.BANK_PATH.write_text(text + "\n\n", encoding="utf-8")
    assert len(store.read_rows(store.BANK_PATH, store.BANK_FIELDS)) == 1


def test_bom_is_tolerated(data_dir):
    row = bank_row()
    body = json.dumps(row, ensure_ascii=False) + "\n"
    store.BANK_PATH.parent.mkdir(parents=True, exist_ok=True)
    store.BANK_PATH.write_bytes("\ufeff".encode("utf-8") + body.encode("utf-8"))
    assert store.read_rows(store.BANK_PATH, store.BANK_FIELDS) == [row]


def test_bad_json_names_the_line(data_dir):
    store.append_row(store.BANK_PATH, bank_row(), store.BANK_FIELDS)
    with store.BANK_PATH.open("a", encoding="utf-8") as f:
        f.write("{不是 JSON}\n")
    with pytest.raises(ValueError) as e:
        store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    assert "第 2 行" in str(e.value)


def test_missing_field_names_the_field_and_line(data_dir):
    row = bank_row()
    del row["refAnswer"]
    write_jsonl(store.BANK_PATH, [row])
    with pytest.raises(ValueError) as e:
        store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    msg = str(e.value)
    assert "第 1 行" in msg and "refAnswer" in msg


def test_extra_field_is_rejected_not_silently_dropped(data_dir):
    write_jsonl(store.BANK_PATH, [{**bank_row(), "typoField": 1}])
    with pytest.raises(ValueError) as e:
        store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    assert "typoField" in str(e.value)


def test_write_rows_replaces_atomically(data_dir):
    store.append_row(store.BANK_PATH, bank_row(), store.BANK_FIELDS)
    keep = bank_row(question="另一道题")
    store.write_rows(store.BANK_PATH, [keep], store.BANK_FIELDS)
    assert store.read_rows(store.BANK_PATH, store.BANK_FIELDS) == [keep]
    assert not list(store.BANK_PATH.parent.glob(".tmp-*")), "临时文件没清掉"


def test_fingerprint_strips_surrounding_whitespace():
    assert store.fingerprint("  同一道题  ") == store.fingerprint("同一道题")


def test_fingerprint_is_12_hex_chars():
    fp = store.fingerprint("题面")
    assert len(fp) == 12 and all(c in "0123456789abcdef" for c in fp)


def test_config_missing_file_is_loud_error(data_dir):
    store.CONFIG_PATH.unlink(missing_ok=True)
    with pytest.raises(FileNotFoundError):
        store.load_config()


def test_config_bad_json_is_loud_error(data_dir):
    store.CONFIG_PATH.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        store.load_config()


def test_config_non_dict_is_loud_error(data_dir):
    store.CONFIG_PATH.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        store.load_config()


def test_load_config_does_not_invent_defaults(data_dir):
    store.CONFIG_PATH.write_text('{"other": 1}', encoding="utf-8")
    assert "per_round" not in store.load_config()


# ---------- 内容错误要在「读」的时候就被拦住，而不是等抽到那题 ----------

def test_bad_kind_in_file_is_caught_on_read(data_dir):
    """手改 JSONL 把 kind 改成非法值——读的时候就得报，别等 sample 抽到它。"""
    write_jsonl(store.BANK_PATH, [bank_row(kind="简历深挖"), bank_row(question="另一题",
                                                                       kind="瞎写")])
    with pytest.raises(ValueError) as e:
        store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    msg = str(e.value)
    assert "第 2 行" in msg and "简历深挖" in msg, "行号 + 合法值都要在"


def test_bad_id_in_file_is_caught_on_read(data_dir):
    write_jsonl(store.BANK_PATH, [bank_row(id="not-a-fingerprint")])
    with pytest.raises(ValueError) as e:
        store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    assert "第 1 行" in str(e.value) and "id" in str(e.value)


def test_append_precheck_failure_writes_nothing(data_dir):
    """预检失败时不该有「第 0 行」这种假信息，也不该留下半个文件。"""
    with pytest.raises(ValueError) as e:
        store.append_row(store.BANK_PATH, bank_row(kind="瞎写"), store.BANK_FIELDS)
    msg = str(e.value)
    assert "第 0 行" not in msg, "还没落盘，报行号是骗人"
    assert "questions.jsonl" in msg
    assert not store.BANK_PATH.exists()


def test_unknown_fields_tuple_is_a_clear_error(data_dir):
    with pytest.raises(ValueError) as e:
        store.read_rows(store.BANK_PATH, ("nope",))
    assert "不认" in str(e.value)
