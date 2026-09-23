import json

import pytest

import models


def bank_kwargs(**over):
    row = {
        "id": "a" * 12,
        "question": "你怎么定义产品成功指标？",
        "refAnswer": "从北极星往下拆到埋点。",
        "kind": "通用",
        "target": "",
        "source": "人工录入",
        "addedAt": "2026-09-23",
    }
    row.update(over)
    return row


# ---------- 合法值与白名单 ----------

def test_valid_row_passes_and_dumps_back_to_json():
    row = models.BankRow.model_validate(bank_kwargs())
    assert json.loads(row.model_dump_json())["kind"] == "通用"


def test_kind_literal_is_the_single_source_for_choices():
    """argparse 的 choices 和校验用的是同一个元组，不会漂移。"""
    assert models.KINDS == ("简历深挖", "岗位场景", "通用")
    assert models.BankRow.model_validate(bank_kwargs(kind="简历深挖")).kind == "简历深挖"


def test_bad_kind_error_lists_every_legal_value():
    with pytest.raises(models.RowError) as e:
        models.parse_row(models.BankRow, bank_kwargs(kind="瞎写"), name="questions.jsonl", lineno=3)
    msg = str(e.value)
    for kind in models.KINDS:
        assert kind in msg, f"报错要把三个合法值都告回来，缺 {kind}"


def test_verdict_whitelist_including_unknown():
    ok = {"at": "2026-09-23T10:00:00+08:00", "qid": "b" * 12,
          "answer": "答", "verdict": "unknown", "feedback": ""}
    assert models.AttemptRow.model_validate(ok).verdict == "unknown"
    with pytest.raises(models.RowError) as e:
        models.parse_row(models.AttemptRow, {**ok, "verdict": "还行"},
                         name="attempts.jsonl", lineno=1)
    assert "unknown" in str(e.value)


# ---------- 空白与类型 ----------

@pytest.mark.parametrize("field", ["question", "refAnswer", "source"])
def test_blank_text_rejected_per_field(field):
    with pytest.raises(models.RowError) as e:
        models.parse_row(models.BankRow, bank_kwargs(**{field: "   \n "}),
                         name="questions.jsonl", lineno=7)
    assert field in str(e.value)
    assert "第 7 行" in str(e.value)


def test_whitespace_is_stripped_not_silently_kept():
    row = models.BankRow.model_validate(bank_kwargs(question="  题面  "))
    assert row.question == "题面"


def test_int_is_not_coerced_into_string():
    """这条是实测行为，不是愿望：pydantic 2.13 对 str 字段收到 123 是报错。"""
    with pytest.raises(models.RowError) as e:
        models.parse_row(models.BankRow, bank_kwargs(question=123),
                         name="questions.jsonl", lineno=1)
    assert "question" in str(e.value)


def test_none_is_rejected_not_treated_as_empty():
    with pytest.raises(models.RowError):
        models.parse_row(models.BankRow, bank_kwargs(refAnswer=None),
                         name="questions.jsonl", lineno=1)


def test_id_must_be_12_lowercase_hex():
    for bad in ("A" * 12, "abc", "z" * 12, ""):
        with pytest.raises(models.RowError) as e:
            models.parse_row(models.BankRow, bank_kwargs(id=bad),
                             name="questions.jsonl", lineno=1)
        assert "id" in str(e.value)


# ---------- 多余键 / 缺键 ----------

def test_extra_key_is_rejected_not_ignored():
    """拼错的键必须报出来。「静默用默认值」是最难查的一类数据损坏。"""
    with pytest.raises(models.RowError) as e:
        models.parse_row(models.BankRow, bank_kwargs(refanswer="小写 a 的拼错版"),
                         name="questions.jsonl", lineno=2)
    msg = str(e.value)
    assert "refanswer" in msg
    assert "question" in msg, "同一个对象里正确的 question 也在——两条都要看得见"


def test_missing_key_is_rejected():
    row = bank_kwargs()
    del row["addedAt"]
    with pytest.raises(models.RowError) as e:
        models.parse_row(models.BankRow, row, name="questions.jsonl", lineno=1)
    assert "addedAt" in str(e.value)


def test_all_errors_are_reported_together():
    row = bank_kwargs(kind="瞎写", question="  ", id="zz")
    with pytest.raises(models.RowError) as e:
        models.parse_row(models.BankRow, row, name="questions.jsonl", lineno=4)
    msg = str(e.value)
    assert "kind" in msg and "question" in msg and "id" in msg


# ---------- 落盘格式锁死 ----------

def test_field_tuples_are_the_on_disk_format():
    """写字面值，不写 `== tuple(BankRow.model_fields)`。

    后者是 `A == A`——把字段改名它照样绿，而那正是会让已有 `bank/questions.jsonl`
    全部读不出来的那种改动。落盘的 key 是外部格式，改它等于换数据版本。
    """
    assert models.BANK_FIELDS == (
        "id", "question", "refAnswer", "kind", "target", "source", "addedAt")
    assert models.ATTEMPT_FIELDS == ("at", "qid", "answer", "verdict", "feedback")


# ---------- stdin 入参（没有 id / addedAt / at，由脚本生成）----------

def test_input_model_accepts_minimal_payload():
    got = models.parse_input(models.BankInput, json.dumps({
        "question": "题", "refAnswer": "答", "kind": "通用", "source": "s",
    }, ensure_ascii=False), src="stdin")
    assert got.target == ""


def test_input_model_rejects_fields_the_script_owns():
    """id 是脚本算的，调用方塞进来就该被拒——否则等于允许伪造 id。"""
    with pytest.raises(models.InputError) as e:
        models.parse_input(models.BankInput, json.dumps({
            "question": "题", "refAnswer": "答", "kind": "通用", "source": "s",
            "id": "f" * 12,
        }, ensure_ascii=False), src="stdin")
    assert "id" in str(e.value)


@pytest.mark.parametrize("raw", ["", "   ", "[1,2]", '"题"', "{坏"])
def test_non_object_stdin_is_a_clear_error(raw):
    with pytest.raises(models.InputError) as e:
        models.parse_input(models.BankInput, raw, src="stdin")
    assert "stdin" in str(e.value)


# ---------- MCP 返回体 ----------

def test_resume_envelope_needs_errcode_zero():
    ok = {"data": {"result": "## 基本信息"}, "errCode": 0}
    assert models.ResumeEnvelope.model_validate(ok).result == "## 基本信息"
    with pytest.raises(models.EnvelopeError):
        models.parse_envelope({"data": {"result": "x"}, "errCode": 43001})


def test_resume_envelope_rejects_empty_result():
    with pytest.raises(models.EnvelopeError) as e:
        models.parse_envelope({"data": {"result": "   "}, "errCode": 0})
    assert "空" in str(e.value)


def test_resume_envelope_rejects_garbage():
    for bad in ({}, {"errCode": 0}, {"data": {}, "errCode": 0},
                {"data": {"result": 5}, "errCode": 0}):
        with pytest.raises(models.EnvelopeError):
            models.parse_envelope(bad)


# ---------- parse_row 的位置文案 ----------

def test_parse_row_with_lineno_names_the_line():
    good = bank_kwargs()
    assert models.parse_row(models.BankRow, good, name="questions.jsonl", lineno=3) == good
    with pytest.raises(models.RowError) as e:
        models.parse_row(models.BankRow, {**good, "kind": "瞎写"},
                         name="questions.jsonl", lineno=3)
    assert "questions.jsonl 第 3 行" in str(e.value)


def test_parse_row_without_lineno_says_not_written_yet():
    """预检失败时文件里还没有这一行，报「第 0 行」是假信息。"""
    bad = bank_kwargs(kind="瞎写")
    with pytest.raises(models.RowError) as e:
        models.parse_row(models.BankRow, bad, name="questions.jsonl", lineno=None)
    msg = str(e.value)
    assert "要写进 questions.jsonl 的内容" in msg
    assert "第 0 行" not in msg and "第 None 行" not in msg
