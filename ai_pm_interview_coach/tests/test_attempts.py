import json

import pytest

import attempts
import bank
import store
from support import bank_row, run_cli, write_jsonl


@pytest.fixture
def banked(data_dir):
    rows = [bank_row(question="怎么定指标"), bank_row(question="怎么做需求优先级")]
    write_jsonl(store.BANK_PATH, rows)
    return [r["id"] for r in rows]


def record(payload) -> tuple[int, str, str]:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return run_cli(attempts.main, ["record"], stdin_text=text)


def test_record_appends_with_generated_timestamp(banked):
    rc, _, err = record({
        "qid": banked[0], "answer": "先看日活。",
        "verdict": "部分对", "feedback": "没区分北极星与护栏。",
    })
    assert rc == 0, err
    rows = store.read_rows(store.ATTEMPTS_PATH, store.ATTEMPT_FIELDS)
    assert len(rows) == 1
    assert rows[0]["qid"] == banked[0]
    assert rows[0]["at"][:4] == "2026" or rows[0]["at"][:4].isdigit()
    assert "T" in rows[0]["at"], "时间戳要能排序，光有日期不够"


def test_record_is_append_only(banked):
    record({"qid": banked[0], "answer": "a", "verdict": "错", "feedback": "f"})
    before = store.ATTEMPTS_PATH.read_bytes()
    record({"qid": banked[1], "answer": "b", "verdict": "对", "feedback": ""})
    after = store.ATTEMPTS_PATH.read_bytes()
    assert after.startswith(before), "记录只能追加，不能改写已有的行"


def test_blank_feedback_is_allowed(banked):
    """答对了可以没反馈——但字段得在。"""
    rc, _, err = record({"qid": banked[0], "answer": "a",
                         "verdict": "对", "feedback": ""})
    assert rc == 0, err


def test_blank_answer_rejected(banked):
    rc, _, err = record({"qid": banked[0], "answer": "  ",
                         "verdict": "对", "feedback": ""})
    assert rc == 1
    assert "answer" in err


def test_verdict_out_of_whitelist_rejected(banked):
    rc, _, err = record({"qid": banked[0], "answer": "a",
                         "verdict": "还行", "feedback": ""})
    assert rc == 1
    assert "部分对" in err, "报错要把合法值告回来"


def test_record_orphan_qid_is_rejected(banked):
    """记不存在的题只会造出一条永远查不到的假记录。"""
    rc, _, err = record({"qid": "ffffffffffff", "answer": "a",
                         "verdict": "对", "feedback": ""})
    assert rc == 1
    assert "ffffffffffff" in err
    assert not store.ATTEMPTS_PATH.exists(), "拒绝就不能留痕"


def test_qid_must_look_like_a_fingerprint(banked):
    """形状就不对的话，连查题库都不用查——多半是手抄断了。"""
    rc, _, err = record({"qid": "abc", "answer": "a",
                         "verdict": "对", "feedback": ""})
    assert rc == 1
    assert "12 位" in err
    assert not store.ATTEMPTS_PATH.exists()


def test_history_lists_newest_last(banked):
    record({"qid": banked[0], "answer": "第一次", "verdict": "错", "feedback": "f1"})
    record({"qid": banked[0], "answer": "第二次", "verdict": "对", "feedback": "f2"})
    rc, out, err = run_cli(attempts.main, ["history", banked[0]])
    assert rc == 0, err
    assert out.index("第一次") < out.index("第二次")


def test_history_shows_the_question_text(banked):
    record({"qid": banked[0], "answer": "a", "verdict": "对", "feedback": ""})
    rc, out, err = run_cli(attempts.main, ["history", banked[0]])
    assert rc == 0, err
    assert "怎么定指标" in out


def test_history_of_qid_never_answered_is_error(banked):
    rc, _, err = run_cli(attempts.main, ["history", banked[1]])
    assert rc == 1
    assert "没答过" in err


def test_history_tolerates_removed_question(banked):
    """题后来被 remove 了，台账不能因此报错——那是事实记录，不是外键表。"""
    record({"qid": banked[0], "answer": "a", "verdict": "错", "feedback": "f"})
    assert run_cli(bank.main, ["remove", banked[0]])[0] == 0
    rc, out, err = run_cli(attempts.main, ["history"])
    assert rc == 0, err
    assert banked[0] in out


def test_history_without_qid_shows_all(banked):
    record({"qid": banked[0], "answer": "a", "verdict": "错", "feedback": ""})
    record({"qid": banked[1], "answer": "b", "verdict": "对", "feedback": ""})
    rc, out, _ = run_cli(attempts.main, ["history"])
    assert rc == 0
    assert "共 2 条" in out


def test_weak_ranks_by_miss_count(banked):
    record({"qid": banked[0], "answer": "a", "verdict": "错", "feedback": ""})
    record({"qid": banked[0], "answer": "b", "verdict": "错", "feedback": ""})
    record({"qid": banked[1], "answer": "c", "verdict": "错", "feedback": ""})
    rc, out, err = run_cli(attempts.main, ["weak"])
    assert rc == 0, err
    assert out.index(banked[0]) < out.index(banked[1])
    assert "怎么定指标" in out


def test_weak_excludes_fully_correct(banked):
    record({"qid": banked[0], "answer": "a", "verdict": "对", "feedback": ""})
    record({"qid": banked[1], "answer": "b", "verdict": "错", "feedback": ""})
    rc, out, err = run_cli(attempts.main, ["weak"])
    assert rc == 0, err
    assert banked[1] in out and banked[0] not in out


def test_weak_treats_last_correct_as_not_weak(banked):
    """错过但最后一次答对了——不该再占弱项位。弱项是「现在还不行」，不是「曾经错过」。"""
    record({"qid": banked[0], "answer": "a", "verdict": "错", "feedback": ""})
    record({"qid": banked[0], "answer": "b", "verdict": "对", "feedback": ""})
    rc, out, _ = run_cli(attempts.main, ["weak"])
    assert rc == 1, "没有弱项时是空结果，不是成功——不写这条的话本用例为假也过"
    assert banked[0] not in out


def test_weak_on_empty_is_not_silently_fine(banked):
    rc, _, err = run_cli(attempts.main, ["weak"])
    assert rc == 1
    assert "还没有答过的题" in err


def test_missing_stdin_is_error(banked):
    rc, _, err = record("")
    assert rc == 1
    assert "stdin" in err
