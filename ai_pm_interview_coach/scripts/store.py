"""题库与答题记录的唯一读写层。

为什么 JSONL 不用 SQLite：两本账都是「全量读进内存 + 整本重写」的量级
（几十到几百行），JSONL 能直接 cat、能 diff、坏了能手改；SQLite 把数据藏进
二进制里，而这个项目的第一红线是「真实数据只有一份、且要看得见」。

**这一层不管字段该是什么值**——那是 `models.py` 的事。
这里只管：文件在不在、第几行、追加、原子重写。
所以 `_validated` 只是把 `models.parse_row` 的报错接上行号再抛出去，自己不判内容。

所有失败都是异常，调用方负责转成非零退出 + stderr。
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import tempfile

import models

ROOT = pathlib.Path(__file__).resolve().parent.parent

def _path_from_env(var: str, default: pathlib.Path) -> pathlib.Path:
    """测试/多副本用的路径覆盖。没设就用项目内的默认位置。"""
    val = os.environ.get(var)
    return pathlib.Path(val) if val else default


BANK_PATH = _path_from_env("COACH_BANK_PATH", ROOT / "bank" / "questions.jsonl")
ATTEMPTS_PATH = _path_from_env("COACH_ATTEMPTS_PATH", ROOT / "attempts" / "attempts.jsonl")
CONFIG_PATH = _path_from_env("COACH_CONFIG", ROOT / "config.json")

# 名字在这里再导出一次，只为了让 `store.KINDS` 这种写法在计划里保持一致。
# 定义只在 models.py 有一份。
BANK_FIELDS = models.BANK_FIELDS
ATTEMPT_FIELDS = models.ATTEMPT_FIELDS
KINDS = models.KINDS
VERDICTS = models.VERDICTS

_MODEL_FOR = {BANK_FIELDS: models.BankRow, ATTEMPT_FIELDS: models.AttemptRow}


def fingerprint(question: str) -> str:
    """题面指纹。同指纹即同题——改题面等于换一道题，历史挂在旧 id 上。"""
    return hashlib.sha256(question.strip().encode("utf-8")).hexdigest()[:12]


def read_rows(path: pathlib.Path, fields: tuple[str, ...]) -> list[dict]:
    model = _model_for(fields)  # 传错 fields 是调用方的编程错误，文件存不存在都要报
    if not path.exists():
        return []
    rows: list[dict] = []
    text = path.read_text(encoding="utf-8-sig")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path.name} 第 {lineno} 行不是合法 JSON：{e.msg}") from None
        rows.append(models.parse_row(model, obj, name=path.name, lineno=lineno))
    return rows


def _model_for(fields: tuple[str, ...]):
    try:
        return _MODEL_FOR[fields]
    except KeyError:
        raise ValueError(
            f"store 不认这组字段：{fields}（只认识 {' / '.join(str(k) for k in _MODEL_FOR)}）"
        ) from None


def _validated(obj, fields: tuple[str, ...], name: str, lineno: int | None) -> dict:
    """内容判断整个交给 models.parse_row——这里一个字都不重复定义规则。

    `lineno=None` 是「还没落盘」的场景（append 前的预检），
    那时报「第 0 行」是假信息，所以由 parse_row 换成「要写进 X 的内容」。
    """
    return models.parse_row(_model_for(fields), obj, name=name, lineno=lineno)


def append_row(path: pathlib.Path, row: dict, fields: tuple[str, ...]) -> None:
    checked = _validated(row, fields, path.name, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(checked, ensure_ascii=False) + "\n")


def write_rows(path: pathlib.Path, rows: list[dict], fields: tuple[str, ...]) -> None:
    """整本重写。先写临时文件再 replace——不留「写了一半」的窗口。

    校验在打开临时文件之前做完（全量先验），不会因为第 50 行不合法而留下
    一个写了 49 行的半成品。
    """
    checked = [_validated(r, fields, path.name, i + 1) for i, r in enumerate(rows)]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    tmp = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for row in checked:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load_config() -> dict:
    """读 config.json。缺文件/坏 JSON/非对象一律抛异常——不猜默认值。

    猜默认值意味着「配置写错了但看起来正常跑」，那是最难查的一类问题。
    """
    raw = CONFIG_PATH.read_text(encoding="utf-8")
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"{CONFIG_PATH.name} 不是合法 JSON：{e.msg}") from None
    if not isinstance(cfg, dict):
        raise ValueError(f"{CONFIG_PATH.name} 顶层不是 JSON 对象，是 {type(cfg).__name__}")
    return cfg
