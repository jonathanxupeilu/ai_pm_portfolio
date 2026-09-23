"""行、入参、外部返回体的形状定义。全项目校验规则的唯一来源。

三层模型：
  BankRow / AttemptRow   —— JSONL 里一行的完整形状（含脚本自己生成的 id/at）
  BankInput / AttemptInput —— 调用方从 stdin 给的，少了脚本该自己算的字段
  ResumeEnvelope          —— 猎聘 my-resume 的返回体

异常分三种，让调用方知道错在哪一层：
  RowError（配 store 的行号）/ InputError（stdin）/ EnvelopeError（外部返回）
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    AfterValidator,
    Field,
)

KIND_LITERAL = Literal["简历深挖", "岗位场景", "通用"]
VERDICT_LITERAL = Literal["对", "部分对", "错", "unknown"]
KINDS: tuple[str, ...] = get_args(KIND_LITERAL)
VERDICTS: tuple[str, ...] = get_args(VERDICT_LITERAL)

_ID_RE = re.compile(r"^[0-9a-f]{12}$")


class RowError(ValueError):
    """某一行的内容不合法。名字带行号信息，所以继承 ValueError。"""


class InputError(ValueError):
    """stdin 给的 JSON 不合法。"""


class EnvelopeError(ValueError):
    """外部（MCP）返回体不合法。"""


def _non_blank(v: str) -> str:
    if not v.strip():
        raise ValueError("不能是空白文本")
    return v.strip()


def _kind(v: str) -> str:
    if v not in KINDS:
        raise ValueError(f"只能是 {'、'.join(KINDS)}")
    return v


def _verdict(v: str) -> str:
    if v not in VERDICTS:
        raise ValueError(f"只能是 {'、'.join(VERDICTS)}")
    return v


def _q12(v: str) -> str:
    if not _ID_RE.match(v):
        raise ValueError("必须是 12 位小写十六进制指纹")
    return v


Text = Annotated[str, AfterValidator(_non_blank)]
Kind = Annotated[str, AfterValidator(_kind)]
Verdict = Annotated[str, AfterValidator(_verdict)]
Fingerprint = Annotated[str, AfterValidator(_q12)]


class _Strict(BaseModel):
    """一切从紧：多余键禁止，字符串两端去空白。

    `str_strip_whitespace` 必须开：`_non_blank` 是在**去掉空白之后**判空的，
    不开的话 `"   "` 会被当成有内容。
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BankRow(_Strict):
    id: Fingerprint
    question: Text
    refAnswer: Text
    kind: Kind
    target: str = ""
    source: Text
    addedAt: str


class AttemptRow(_Strict):
    at: Text
    qid: Fingerprint
    answer: Text
    verdict: Verdict
    feedback: str = ""


class BankInput(_Strict):
    question: Text
    refAnswer: Text
    kind: Kind
    source: Text
    target: str = ""


class AttemptInput(_Strict):
    qid: Fingerprint
    answer: Text
    verdict: Verdict
    feedback: str


class ResumeData(_Strict):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    result: Text = Field(description="简历正文（markdown）")


class ResumeEnvelope(_Strict):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    errCode: int
    data: ResumeData

    @property
    def result(self) -> str:
        return self.data.result


def _humanize(exc: ValidationError) -> str:
    """把 pydantic 的英文报错骨架换成项目里的中文说法。

    只换外层组织方式，`msg` 原样带出来——pydantic 的 msg 里已经写了
    「只能是 '简历深挖'、'岗位场景' ...」这种我们想要的信息。
    """
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "（顶层）"
        parts.append(f"{loc}：{err['msg']}")
    return "；".join(parts)


def parse_row(model: type[_Strict], obj: dict, *, name: str, lineno: int | None) -> dict:
    """校验一行，返回**规范化后**的 dict（去空白、字段顺序按模型）。

    `lineno=None` = 这行还没落盘（append 前的预检）。此时报「第 0 行」是假信息，
    所以位置换成「要写进哪个文件的内容」。
    """
    loc = f"{name} 第 {lineno} 行" if lineno is not None else f"要写进 {name} 的内容"
    try:
        row = model.model_validate(obj)
    except ValidationError as e:
        raise RowError(f"{loc} {_humanize(e)}") from None
    return {f: getattr(row, f) for f in type(row).model_fields}


def parse_input(model: type[_Strict], raw: str, *, src: str = "stdin") -> _Strict:
    if not raw.strip():
        raise InputError(f"{src} 是空的，需要一个 JSON 对象")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise InputError(f"{src} 不是合法 JSON：{e.msg}") from None
    if not isinstance(obj, dict):
        raise InputError(f"{src} 顶层是 {type(obj).__name__}，需要 JSON 对象")
    try:
        return model.model_validate(obj)
    except ValidationError as e:
        raise InputError(f"{src} 里的内容不合法：{_humanize(e)}") from None


def parse_envelope(obj: object) -> ResumeEnvelope:
    if not isinstance(obj, dict):
        raise EnvelopeError(f"返回体是 {type(obj).__name__}，需要 JSON 对象")
    try:
        env = ResumeEnvelope.model_validate(obj)
    except ValidationError as e:
        raise EnvelopeError(f"返回体不合法：{_humanize(e)}") from None
    if env.errCode != 0:
        raise EnvelopeError(f"业务失败 errCode={env.errCode}，不是 0")
    return env


BANK_FIELDS = tuple(BankRow.model_fields)
ATTEMPT_FIELDS = tuple(AttemptRow.model_fields)
