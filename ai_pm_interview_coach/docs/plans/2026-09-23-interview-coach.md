# 面试出题教练 · 实现计划

> 设计定稿见 `docs/plans/2026-09-23-interview-coach-design.md`（commit `62c00f0`）。
> 这份把设计切成可逐个执行的小任务。每个任务：写失败测试 → 跑确认红 → 最小实现 → 跑绿 → 提交。

**Goal:** 建 4 个脚本（`store.py` / `bank.py` / `resume.py` / `attempts.py`），
确定性活归脚本，联网搜索、出题、判分归会话里的 LLM。

**Architecture:** 脚本不互相 import 业务状态，只共享 `store.py`（读写）和
`models.py`（形状与内容校验）两层。
数据是两本 JSONL 账（`bank/`、`attempts/`），都在项目目录内、都不进版本库。
唯一的外呼是 `resume.py` 读 `my-resume`，工具名写死成常量。

**Tech Stack:** Python 3.12 + **pydantic 2.13**（校验行的形状与内容、以及 MCP 返回体）。
测试 `pytest 9.1` 跑。
依赖装在项目自己的 `.venv` 里：uv 管理的那个基础解释器是 externally-managed，
`pip install` 会被拒（`error: ... is externally managed`），而 `--break-system-packages`
会污染所有项目的解释器——所以只有 venv 这一条路。
lint 用 `ruff`（`uv tool install ruff` 装的独立可执行文件，不进 venv）。

**工作地点:** git worktree `/f/projects/ai_pm_portfolio/.worktrees/interview-coach`，
分支 `feature/interview-coach`。项目目录 `ai_pm_interview_coach/`。

**纪律（不可协商）：**
- 绝不为过测试而放宽校验。跑红了先问「是不是实现真错了」。
- 测试里不出现真令牌。真 `~/.workbuddy/mcp.json` 一个字节都不许读。
- 真实数据目录（`bank/`、`attempts/`）在每个测试里必须被重定向到临时目录，
  并有测试断言真目录字节未变（Task 9）。
- 失败一律非零退出 + stderr 说清「哪个文件、第几行、什么字段、期望什么」。
  禁止 `except: pass`，禁止静默降级。
- **校验规则只在 `models.py` 写一次。** 命令行脚本不许再手写一遍 `if kind not in (...)`——
  两处规则一定会有对不上的那天。
- 「什么都没做」不算成功。

**每步跑测试：**

```bash
cd ai_pm_interview_coach && .venv/Scripts/python -m pytest tests -q
```

**每步跑 lint：**

```bash
cd ai_pm_interview_coach && ruff check scripts tests
```

---

## 全局约定（所有任务共用，先定死）

字段与合法值的**唯一定义处是 `scripts/models.py`**（Task 2）。
下面这几组名字是它导出的结果，`store.py` 只是把它们原样再导出一次，
好让 `store.BANK_FIELDS` 这种写法在整份计划里保持一致：

```python
BANK_FIELDS    = ("id", "question", "refAnswer", "kind", "target", "source", "addedAt")
ATTEMPT_FIELDS = ("at", "qid", "answer", "verdict", "feedback")
KINDS          = ("简历深挖", "岗位场景", "通用")
VERDICTS       = ("对", "部分对", "错", "unknown")
```

**分工界线，别糊：**

| 谁 | 管什么 | 不管什么 |
| --- | --- | --- |
| `models.py` | 字段在不在、有没有多余键、类型、`kind`/`verdict` 白名单、`id` 格式、空白文本 | 文件在哪、第几行 |
| `store.py` | 读文件、**指出第几行**、追加、原子重写 | 字段该是什么值 |
| `bank.py` / `attempts.py` | CLI 流程、退出码、把校验错误原样搬到 stderr | 自己再手写一遍校验规则 |

读数据文件时两层都会过：`store` 定位行号，`models` 判内容。
所以手改 `bank/questions.jsonl` 把 `kind` 改成 `"瞎写"`，
下一次读会报「第 N 行 kind 只能是 简历深挖、岗位场景、通用」——不是等抽到这题才炸。

- **`id = sha256(question.strip()).hexdigest()[:12]`**。同指纹即同题，`add` 遇到已存在的
  指纹**拒绝且不覆盖**（要改题先 `remove`）。这样「不定期导入真题」反复跑也不会覆盖掉
  已经答错过的题的历史。
- 每个脚本暴露 `main(argv: list[str]) -> int`，
  `if __name__ == "__main__": raise SystemExit(main(sys.argv[1:]))`。
  CLI 就是公共接口，测试从 `main` 进，不从内部函数进。
- 一题一行 JSONL。记录只追加，不改写（`bank remove` 是唯一的重写路径）。
- 空行和 BOM 容忍（`encoding="utf-8-sig"`，跳过空白行）；
  其余任何解析失败都报错并指出行号。
- `attempts` 一个文件就够（几百行量级），路径常量叫 `ATTEMPTS_PATH`。

### 数据路径重定向的标准做法

`store.py` 的 `BANK_PATH` / `ATTEMPTS_PATH` 是**模块级可变常量**，测试用
`monkeypatch.setattr` 指到 `tmp_path`。这是本项目唯一的打桩点，也是唯一允许改的地方。
不要在测试里 `chdir`（`store.ROOT` 是绝对路径，chdir 没用），也不要在测试里 mock `open`。

```python
@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "BANK_PATH", tmp_path / "bank" / "questions.jsonl")
    monkeypatch.setattr(store, "ATTEMPTS_PATH", tmp_path / "attempts" / "attempts.jsonl")
    monkeypatch.setattr(store, "CONFIG_PATH", tmp_path / "config.json")
    return tmp_path
```

`tests/conftest.py` 里注册成可复用 fixture，测试文件直接按名字要 `data_dir`。

---

## Task 0：骨架

**创建：** `scripts/`、`tests/`、`.venv/`、`requirements.txt`、`ruff.toml`、
`config.json`、`README.md`、`.gitignore`（项目内那份）。

0. **先建 venv 并装依赖**——不装好，第一条测试就跑不起来，
   而报出来的错（`ModuleNotFoundError: pydantic`）容易被误当成代码写错了。

   ```bash
   cd ai_pm_interview_coach
   uv venv                                             # 基础解释器 externally-managed，只能这样
   uv pip install --python .venv/Scripts/python.exe pydantic pytest
   uv tool install ruff                               # ruff 是独立工具，不进 venv
   .venv/Scripts/python -c "import pydantic, pytest; print(pydantic.VERSION, pytest.__version__)"
   ruff --version
   ```

   预期看到 `2.13.x 9.1.1` 和 `ruff 0.16.x`。

1. `requirements.txt`（把版本钉住，别留浮动）：

```
pydantic==2.13.5
pytest==9.1.1
```

2. `ruff.toml`：

```toml
# 只挑「不修就会咬人」的规则，不做风格警察。
# 项目里的中文是内容，不是注释——所以不该被当成非 ASCII 噪声报出来。
target-version = "py312"
line-length = 100

[lint]
select = [
  "E9",    # 语法错误、缩进错误
  "F",     # pyflakes：未用 import、未定义名、f-string 里没占位符
  "B",     # bugbear：可变默认参、循环变量捕获、异常链丢失
  "SIM",   # 可简化的写法
  "UP",    # 该用新语法的地方（typing.Optional → X | None 之类）
  "RUF",
]
ignore = [
  "E501",  # 行长交给格式化，不当错误报——中文题面本来就长
  "B008",
  # 中文标点不是拼写错误。这三条会把「，」「：」「（）」全报成
  # "Did you mean ,"——本项目里中文是内容（题面、报错文案），不是手滑。
  # 关掉的是「ASCII 洁癖」，不是任何正确性规则。
  "RUF001", "RUF002", "RUF003",
]

[lint.per-file-ignores]
"tests/*" = ["B011"]
```

3. `tests/conftest.py`：

```python
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
```

4. `config.json`：

```json
{ "per_round": 5 }
```

5. `.gitignore`：

```
bank/
attempts/
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
```

> `.venv/` 必须挡掉：它上千个文件，而且里面**可能有可执行代码**，
> 进版本库既撑大仓库又给供应链留口子。依赖用 `requirements.txt` 复现，不用 venv 本身。

6. `README.md` 先一句话占位（Task 11 补全）：

```markdown
# AI 产品经理面试出题教练

脚本只做确定性的活（存题、抽题、留痕、读在线简历）；
搜索、出题、判分由会话里的 AI 做。
```

7. **这时 `conftest.py` 里的 fixture 会 import 失败的 `store`**——但它只在被要到时才执行，
   所以 `.venv/Scripts/python -m pytest tests -q` 仍是 `no tests ran`，不是错误。跑一次确认。

8. 同时确认 lint 闸门是通的（这会儿还没代码，`All checks passed!` 或 `no targets` 都算过）：

   ```bash
   ruff check scripts tests
   ```

**提交：** `出题教练：目录骨架 + venv/依赖 + ruff 配置 + 数据目录忽略`

---

## Task 1：测试脚手架 `tests/support.py`

**这一步没有测试**——它给后面的任务用，正确性由「每个任务都靠它跑起来」证明。

```python
"""测试公共件：跑 CLI 收 (rc, out, err)、造数据行。

数据路径重定向不在这里，在 conftest.py 的 data_dir fixture。
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import tempfile
import unittest.mock


def run_cli(main, argv, stdin_text: str = "") -> tuple[int, str, str]:
    """把 main(argv) 当命令行那样跑一遍，收回调的输出。

    不起子进程：快，且 monkeypatch 生效（起进程只重定向得了环境变量，
    patch 不动模块常量）。真起进程的端到端在 test_e2e.py。
    """
    out, err = io.StringIO(), io.StringIO()
    argv = [str(a) for a in argv]
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            unittest.mock.patch("sys.stdin", io.StringIO(stdin_text)):
        try:
            rc = main(argv)
        except SystemExit as e:
            code = e.code
            rc = code if isinstance(code, int) else (0 if code is None else 1)
    return rc, out.getvalue(), err.getvalue()
```

> 为什么用字符串路径 `"sys.stdin"` 而不是 `patch.object(sys, "stdin", ...)`：
> 后者在 `sys.stdin` 被别的测试换掉过的时候会拿到已污染的引用。字符串形式每次重新解析。

造数据（字段名的唯一来源是 `store`，这里不重复定义一套）：

```python
def bank_row(question: str = "你怎么定义产品成功指标？", **over) -> dict:
    import store

    row = {
        "id": store.fingerprint(question),
        "question": question,
        "refAnswer": "能从北极星指标往下拆到可观测的埋点。",
        "kind": "通用",
        "target": "",
        "source": "人工录入",
        "addedAt": "2026-09-23",
    }
    row.update(over)
    return row


def attempt_row(qid: str, **over) -> dict:
    row = {
        "at": "2026-09-23T10:00:00+08:00",
        "qid": qid,
        "answer": "我一般先看留存。",
        "verdict": "部分对",
        "feedback": "没说到指标怎么反推需求。",
    }
    row.update(over)
    return row


def write_jsonl(path: pathlib.Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def make_tmp() -> pathlib.Path:
    return pathlib.Path(tempfile.mkdtemp(prefix="coach-tmp-"))
```

**注意 `store` 是在函数体里 import 的**，这样 Task 1 可以在 Task 3 之前先跑一遍
（`python -c "import support"` 不报错），不会被「模块还没写」卡住。

**提交：** `出题教练：测试脚手架——CLI 调用器 + 行构造`

---

## Task 2：`models.py` —— 校验规则只写这一次

**文件：** 创建 `tests/test_models.py`、`scripts/models.py`。

为什么要有这一层，而不是在各命令里手写 `if`：
`bank add`、`attempts record`、`store` 读文件、`resume` 读 MCP 返回——
**四个入口都在判断同一批规则**（字段全不全、`kind` 合不合法、文本是不是空的）。
手写四遍，早晚有一遍和别三遍对不上，而且对不上的那次一定是数据已经写坏了才发现。

pydantic 在这里干三件手写不容易干对的事：

1. **`extra="forbid"`**：stdin 里多一个拼错的键（`refanswer`）会被拒，
   而不是「静默忽略了那个字段，于是 refAnswer 用了默认值」。
2. **不做隐式放宽**：实测 pydantic 2.13 对 `int` 传给 `str` 字段是**报错**
   （`string_type`），不是 `str(123)`。所以 `{"question": 123}` 进不来。
3. **`Literal` 的报错自带合法值清单**，不用我在每个 `if` 里手拼「只能是 A、B 或 C」。

### Step 1 写失败测试

`tests/test_models.py`：

```python
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
```

### Step 2 跑红

`ModuleNotFoundError: No module named 'models'`。

### Step 3 实现 `scripts/models.py`

```python
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
```

> **`target` 用普通 `str`、`feedback` 用普通 `str`，不是漏了 `Text`。**
> 这两个是合法可空的：一道题可以没有岗位靶子，答对了可以没有反馈。
> 把它们也写成 `Text` 会把「没有反馈」变成错误。

`RowError` / `InputError` 的**抛出**还没写——在文件末尾补上三个解析函数：

```python
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
```

### 三处值得停一下的地方

1. **`_non_blank` 里自己 `strip()`，同时又开了 `str_strip_whitespace`。**
   看着重复，但不是：配置那个开关负责**所有** str 字段（含可空的 `target`），
   `_non_blank` 负责**判空**。少了前者，`target: "  x  "` 会带着空格进库。
2. **`ResumeData` / `ResumeEnvelope` 用 `extra="ignore"`，和行模型相反。**
   那是外部系统的返回体，人家多给字段是常态；
   而行模型的键是**我们自己**定的，多出来一个就是拼错了。
   **同一条规则在两个方向上不一样，这是刻意的**——别「统一」成一样。
3. **`parse_row` 返回 dict 而不是模型实例**，因为 `store` 后面要按
   `BANK_FIELDS` 的顺序序列化，dict 更省事，也让 `store` 不依赖 pydantic 的 API。

### Step 4 跑绿

```bash
cd ai_pm_interview_coach && .venv/Scripts/python -m pytest tests/test_models.py -q
```
期望 27 passed。

**提交：** `出题教练 models.py：校验规则收到一处，pydantic 兜住四个入口`

---

## Task 3：`store.py` —— 唯一读写层

**文件：** `tests/test_store.py`、`scripts/store.py`。

### Step 1 写失败测试

```python
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
    store.BANK_PATH.write_bytes(
        "\ufeff".encode("utf-8") + body.encode("utf-8")
    )
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
```

### Step 2 跑红

期望 `ModuleNotFoundError: No module named 'store'`。

### Step 3 实现 `scripts/store.py`

```python
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

BANK_PATH = ROOT / "bank" / "questions.jsonl"
ATTEMPTS_PATH = ROOT / "attempts" / "attempts.jsonl"
CONFIG_PATH = ROOT / "config.json"

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
```

**`write_rows` 里为什么是 `os.fdopen(fd, ...)` 而不是 `tmp.open(..., closefd=False)`：**
`mkstemp` 返回的是裸 fd，而 `pathlib.Path.open()` 没有 `closefd` 这个参数，
写成后者会 `TypeError: Path.open() got an unexpected keyword argument 'closefd'`。
这条是 2026-09-23 把计划里的代码抽到临时目录真跑 pytest 跑出来的，不是推测。
也别「顺手」在 `finally` 里补一个 `os.close(fd)`：`os.fdopen` 之后 fd 归那个文件对象管，
`with` 退出时已经关过了，再关一次是 `OSError`。

### Step 4 跑绿

期望 46 passed（models 27 + store 19）。

**提交：** `出题教练 store.py：JSONL 读写 + 字段严格校验 + 原子重写`

---

## Task 4：`bank.py add` / `show`

**文件：** `tests/test_bank_add.py`、`scripts/bank.py`。

### Step 1 写失败测试

```python
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
```

### Step 2 跑红

`ModuleNotFoundError: No module named 'bank'`。

### Step 3 实现 `scripts/bank.py`

本任务只写 `add` / `show`；`list` / `remove` / `sample` 在 Task 5。

```python
"""题库命令行。

  bank.py add          从 stdin 读一个 JSON 对象，存一题
  bank.py show <id>    打印整题
  bank.py list         一行一题列出来
  bank.py remove <id>  删一题
  bank.py sample       抽本轮的题

只存确定性事实。搜什么、出什么题、判得对不对，都不在这个脚本里。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import models
import store


def _fail(msg: str) -> int:
    print(f"❌ {msg}", file=sys.stderr)
    return 1


def cmd_add(_args) -> int:
    try:
        payload = models.parse_input(models.BankInput, sys.stdin.read(), src="stdin")
    except models.InputError as e:
        return _fail(str(e))

    qid = store.fingerprint(payload.question)
    try:
        existing = store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    except ValueError as e:
        return _fail(str(e))
    if any(r["id"] == qid for r in existing):
        return _fail(f"已存在同指纹题（id={qid}），不覆盖——先 remove 再 add，或人工合并")

    store.append_row(store.BANK_PATH, {
        "id": qid,
        "question": payload.question,
        "refAnswer": payload.refAnswer,
        "kind": payload.kind,
        "target": payload.target,
        "source": payload.source,
        "addedAt": dt.date.today().isoformat(),
    }, store.BANK_FIELDS)
    print(qid)
    return 0


def cmd_show(args) -> int:
    try:
        rows = store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    except ValueError as e:
        return _fail(str(e))
    for r in rows:
        if r["id"] == args.id:
            print(json.dumps(r, ensure_ascii=False, indent=2))
            return 0
    return _fail(f"题库里没有 id={args.id}（bank.py list 看全量）")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="bank.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="从 stdin 存一题")
    a.set_defaults(fn=cmd_add)
    s = sub.add_parser("show", help="按 id 看一题")
    s.add_argument("id")
    s.set_defaults(fn=cmd_show)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

### Step 4 跑绿

期望 55 passed（models 27 + store 19 + bank add/show 9）。

**提交：** `出题教练 bank add/show：同指纹拒绝不覆盖`

---

## Task 5：`bank.py list` / `remove` / `sample`

**文件：** 创建 `tests/test_bank_list.py`、`tests/test_bank_remove.py`、
`tests/test_bank_sample.py`；改 `scripts/bank.py`。

### Step 1 写失败测试

`tests/test_bank_list.py`：

```python
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
```

`tests/test_bank_remove.py`：

```python
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
```

`tests/test_bank_sample.py`：

```python
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
```

### Step 2 跑红

`unrecognized arguments` / 子命令不存在。

### Step 3 实现（往 `scripts/bank.py` 加）

顶部 `import random`。

```python
def _filtered(kind, target) -> list[dict]:
    rows = store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    if target:
        rows = [r for r in rows if r["target"] == target]
    return rows


def cmd_list(_args) -> int:
    try:
        rows = store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    except ValueError as e:
        return _fail(str(e))
    print(f"题库共 {len(rows)} 题")
    for r in rows:
        one_line = " ".join(r["question"].split())[:60]
        tgt = f" [{r['target']}]" if r["target"] else ""
        print(f"{r['id']}  {r['kind']}{tgt}  {one_line}")
    return 0


def cmd_remove(args) -> int:
    try:
        rows = store.read_rows(store.BANK_PATH, store.BANK_FIELDS)
    except ValueError as e:
        return _fail(str(e))
    keep = [r for r in rows if r["id"] != args.id]
    if len(keep) == len(rows):
        return _fail(f"题库里没有 id={args.id}，没动任何数据")
    gone = next(r for r in rows if r["id"] == args.id)
    store.write_rows(store.BANK_PATH, keep, store.BANK_FIELDS)
    print(f"已删 {gone['id']}  {gone['kind']}  {' '.join(gone['question'].split())[:60]}")
    return 0


def cmd_sample(args) -> int:
    try:
        cfg = store.load_config()
    except (FileNotFoundError, ValueError) as e:
        return _fail(str(e))
    n = args.n if args.n is not None else cfg.get("per_round")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        return _fail(f"-n / per_round 要是 ≥1 的整数，现在是 {n!r}")

    try:
        pool = _filtered(args.kind, args.target)
        if args.fresh:
            seen = {r["qid"] for r in
                    store.read_rows(store.ATTEMPTS_PATH, store.ATTEMPT_FIELDS)}
            pool = [r for r in pool if r["id"] not in seen]
    except ValueError as e:
        return _fail(str(e))

    if not pool:
        return _fail("没有可出的题——题库空（或筛选 / --fresh 之后没剩），不是成功")

    rng = random.Random(args.seed) if args.seed is not None else random.SystemRandom()
    for r in rng.sample(pool, min(n, len(pool))):
        print(r["id"])
    return 0
```

`main()` 里加三个 subparser：

```python
    l = sub.add_parser("list", help="一行一题列出来")
    l.set_defaults(fn=cmd_list)
    rm = sub.add_parser("remove", help="按 id 删一题")
    rm.add_argument("id")
    rm.set_defaults(fn=cmd_remove)
    sp = sub.add_parser("sample", help="抽本轮的题（只出 id）")
    sp.add_argument("-n", type=int, default=None)
    sp.add_argument("--seed", type=int, default=None)
    sp.add_argument("--kind", choices=store.KINDS, default=None)
    sp.add_argument("--target", default=None)
    sp.add_argument("--fresh", action="store_true", help="排除答过的题")
    sp.set_defaults(fn=cmd_sample)
```

**两个设计点，不要「顺手优化」掉：**

1. `--seed` 不给时用 `random.SystemRandom()`，不是全局 `random`。
   同一轮里 `add` 完再 `sample`，不该被前面的随机调用挪走序列。
2. `--kind` 用 `choices=store.KINDS`，argparse 自己就拒绝非法值并打出合法值——
   和 `cmd_add` 里手写的白名单报错是两条路，但结论一致：**不猜**。

### Step 4 跑绿

期望 75 passed（models 27 + store 19 + add/show 9 + list 5 + remove 3 + sample 12）。

**提交：** `出题教练 bank list/remove/sample：--seed 可复现，抽不到题不是成功`

---

## Task 6：`resume.py` —— 唯一的外呼，只读 `my-resume`

**文件：** 创建 `tests/test_resume_config.py`、`scripts/resume.py`。

这一层拆两半：**配置与白名单**（本任务，离线可测）和
**协议与数据形状**（Task 7，用假 MCP 服务测）。分开是因为
「不许改成别的工具」这条红线要在没有网络的情况下也能被测试钉住。

### 红线（设计文档里的第三条）

真实猎聘 MCP 有 14 个工具，其中 9 个是写简历的
（`add-work-exp`、`add-project-exp`、`add-edu-exp`、`add-job-want`、`modify-work-exp`、
`modify-edu-exp`、`modify-self-assess`、`modify-job-want`、`modify-resume-base-info`、
`modify-project-exp`）。这个脚本**只能读**。防护不是「我记得不调」，而是：

- `RESUME_TOOL = "my-resume"` 是模块常量；
- `main()` 不接受任何能改工具名的参数；
- 调用点只有一处，`name` 不是变量。

### Step 1 写失败测试

`tests/test_resume_config.py`：

```python
import inspect
import json
import pathlib

import pytest

import resume


def test_resume_tool_is_my_resume():
    assert resume.RESUME_TOOL == "my-resume"


def test_tool_name_is_a_constant_not_a_parameter():
    """红线：没有任何入口能把工具名换成写简历的那 9 个之一。"""
    assert list(inspect.signature(resume.main).parameters) == ["argv"]
    src = pathlib.Path(resume.__file__).read_text(encoding="utf-8")
    for forbidden in ("--tool", "add-work-exp", "modify-self-assess",
                      "modify-resume-base-info"):
        assert forbidden not in src, f"resume.py 里不该出现 {forbidden}"
    assert "tools/call" in src, "确实只有一次调用点"


def test_config_path_default_is_workbuddy_mcp_json():
    """默认路径就在 ~/.workbuddy/mcp.json，不搜别的文件。

    断言路径的**分段**，不断言整串：expanduser 在 Windows 上是反斜杠、
    家目录还带空格，比字符串只会假红。
    """
    parts = resume.DEFAULT_CONFIG_PATH.parts
    assert parts[-2:] == (".workbuddy", "mcp.json")


def test_missing_config_is_loud_error(tmp_path, monkeypatch):
    monkeypatch.setattr(resume, "MCP_CONFIG", tmp_path / "nope.json")
    with pytest.raises(SystemExit) as e:
        resume.load_endpoint()
    assert "找不到 MCP 配置" in str(e.value)


def test_bad_json_config_names_the_file(tmp_path, monkeypatch):
    p = tmp_path / "mcp.json"
    p.write_text("{", encoding="utf-8")
    monkeypatch.setattr(resume, "MCP_CONFIG", p)
    with pytest.raises(SystemExit) as e:
        resume.load_endpoint()
    assert "不是合法 JSON" in str(e.value)
    assert str(p) in str(e.value)


def _write_cfg(tmp_path, monkeypatch, servers: dict):
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps({"mcpServers": servers}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(resume, "MCP_CONFIG", p)
    return p


def test_missing_server_section_is_loud(tmp_path, monkeypatch):
    _write_cfg(tmp_path, monkeypatch, {})
    with pytest.raises(SystemExit) as e:
        resume.load_endpoint()
    assert "liepin-mcp" in str(e.value)


def test_empty_token_is_loud_never_falls_back(tmp_path, monkeypatch):
    _write_cfg(tmp_path, monkeypatch, {
        "liepin-mcp": {"url": "http://x", "headers": {"x-user-token": ""}}
    })
    with pytest.raises(SystemExit) as e:
        resume.load_endpoint()
    assert "x-user-token" in str(e.value)


def test_missing_headers_is_loud(tmp_path, monkeypatch):
    _write_cfg(tmp_path, monkeypatch, {"liepin-mcp": {"url": "http://x"}})
    with pytest.raises(SystemExit) as e:
        resume.load_endpoint()
    assert "x-user-token" in str(e.value)


def test_empty_url_is_loud(tmp_path, monkeypatch):
    _write_cfg(tmp_path, monkeypatch, {
        "liepin-mcp": {"url": "", "headers": {"x-user-token": "t"}}
    })
    with pytest.raises(SystemExit) as e:
        resume.load_endpoint()
    assert "url" in str(e.value)


def test_load_endpoint_returns_url_and_token(tmp_path, monkeypatch):
    _write_cfg(tmp_path, monkeypatch, {
        "liepin-mcp": {"url": "http://127.0.0.1:9", "headers": {"x-user-token": "tok"}}
    })
    assert resume.load_endpoint() == ("http://127.0.0.1:9", "tok")
```

**每个用例都用 `monkeypatch.setattr`，没有一处直接给 `resume.MCP_CONFIG` 赋值。**
直接赋值不会还原，同进程后面的用例会拿到前一个用例的假路径——那种假红/假绿最难查。

### Step 2 跑红

`ModuleNotFoundError: No module named 'resume'`。

### Step 3 实现 `scripts/resume.py`

`load_endpoint` / `_rpc` 两段**逐段复制自** `job_seeking/scripts/liepin.py`
（这就是设计里定的「复制并解耦」），按本项目改三处：

1. 配置路径拆成 `DEFAULT_CONFIG_PATH`（写死的来源）和 `MCP_CONFIG`（可被测试替换的值）；
2. 删掉 `SEARCH_TOOL` / `APPLY_TOOL`，只留 `RESUME_TOOL = "my-resume"`；
3. `_rpc` 的 `Accept` 头和 SSE `data:` 行抽取照抄——**服务端走 SSE 风格，正文在
   `data:` 行里**，省了线上就会解析失败。

```python
"""读猎聘在线简历（my-resume）。本项目唯一的外呼。

  resume.py            把在线简历正文打到 stdout（markdown 文本）

红线：只读。工具名写死成常量，没有任何参数能改它。
真实 MCP 另有 9 个写简历的工具，这个脚本碰不到——不调，也不给入口。

令牌只从 ~/.workbuddy/mcp.json 读：只读、不落盘、不打印、不进 git。
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request

SERVER_NAME = "liepin-mcp"
RESUME_TOOL = "my-resume"
TIMEOUT = 60

DEFAULT_CONFIG_PATH = pathlib.Path("~/.workbuddy/mcp.json").expanduser()
MCP_CONFIG = DEFAULT_CONFIG_PATH


def load_endpoint() -> tuple[str, str]:
    """返回 (url, token)。缺任何一项都停下来报错，不许降级猜测。"""
    if not MCP_CONFIG.exists():
        raise SystemExit(
            f"❌ 找不到 MCP 配置：{MCP_CONFIG}\n"
            f"   本流程从该文件读猎聘令牌，请先确认它存在且已登录。"
        )
    try:
        cfg = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"❌ {MCP_CONFIG} 不是合法 JSON：{e}") from None
    srv = (cfg.get("mcpServers") or {}).get(SERVER_NAME)
    if not isinstance(srv, dict):
        raise SystemExit(f"❌ {MCP_CONFIG} 里没有 mcpServers.{SERVER_NAME}")
    url = srv.get("url")
    token = (srv.get("headers") or {}).get("x-user-token")
    if not url:
        raise SystemExit(f"❌ mcpServers.{SERVER_NAME}.url 为空")
    if not token:
        raise SystemExit(f"❌ mcpServers.{SERVER_NAME}.headers.x-user-token 为空")
    return url, token


def _rpc(method: str, params=None, rid: int = 1) -> dict:
    url, token = load_endpoint()
    body: dict = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "x-user-token": token,          # 只在这里出现，且不落任何日志
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read()[:400].decode("utf-8", "replace")
        raise RuntimeError(f"MCP 返回 HTTP {e.code}：{detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"MCP 连接失败：{e.reason}") from None

    lines = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
    payload = "\n".join(lines) if lines else raw
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        raise RuntimeError(f"MCP 返回无法解析为 JSON：{payload[:300]}") from None


def fetch_resume() -> str:
    """调 my-resume，取出 content[0].text 里的 markdown 正文。

    实测形状：content[0].text 是 JSON
    {"data": {"result": <2745 字 markdown 文本>}, "errCode": 0}。
    errCode 非 0 或 result 为空都算失败——协议成功不等于业务有结论。
    """
    resp = _rpc("tools/call", {"name": RESUME_TOOL, "arguments": {}}, 3)
    if "error" in resp:
        raise RuntimeError(f"MCP 调用 {RESUME_TOOL} 出错：{resp['error']}")
    result = resp.get("result") or {}
    text = next((c.get("text") for c in (result.get("content") or [])
                 if c.get("type") == "text"), None)
    if text is None:
        raise RuntimeError(f"{RESUME_TOOL} 的返回里没有 text content")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(f"{RESUME_TOOL} 的 content 不是 JSON：{text[:200]}") from None
    if (data or {}).get("errCode") != 0:
        raise RuntimeError(f"{RESUME_TOOL} 业务失败 errCode={(data or {}).get('errCode')!r}")
    body = ((data or {}).get("data") or {}).get("result")
    if not isinstance(body, str) or not body.strip():
        raise RuntimeError(f"{RESUME_TOOL} 返回的 result 是空的——简历读不到，不是没写过")
    return body


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    try:
        sys.stdout.write(fetch_resume())
    except RuntimeError as e:
        print(f"❌ 读在线简历失败：{e}", file=sys.stderr)
        return 1
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

`load_endpoint` 用 `SystemExit` 报错（跟 job_seeking 一致），而 `main` 是 CLI 入口，
把它转成 `return 1` 并原样把那条 `❌` 搬到 stderr——「配置缺失」于是表现为非零退出，
而不是异常外泄一段 traceback。

### Step 4 跑绿

期望 85 passed（新增 10）。

**提交：** `出题教练 resume.py：my-resume 硬编码白名单，配置缺失显式退出`

---

## Task 7：假 MCP + 集成测试 —— 把红线跑在真协议上

**文件：** 创建 `tests/fake_mcp.py`、`tests/test_resume_integration.py`。

Task 6 的白名单测试只是结构检查（常量值、签名、源码里没出现禁词）。
真正的牙齿在这层：**起一个 127.0.0.1 的假 MCP，看它到底收到什么**。
只有跑过真 HTTP，才能断言「请求体里 `params.name` 永远是 `my-resume`」
和「令牌确实带上了、且从没出现在输出里」。

### Step 1 先写服务端 `tests/fake_mcp.py`

```python
"""假猎聘 MCP：只绑 127.0.0.1，按脚本的期望回 SSE 帧。

为什么必须回 SSE（`data:` 行）而不是裸 JSON：`resume._rpc` 是按 SSE 解析的，
服务端要是总回裸 JSON，那条解析路径就永远没被测到——线上才会第一次走。
"""
from __future__ import annotations

import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FAKE_TOKEN = "fake-token-for-tests-never-real"
RESUME_BODY = "## 基本信息\n姓名：测试\n\n## 工作经历\n某公司 AI 产品经理\n"


class Call:
    """一次被收到的请求，给断言用。"""

    def __init__(self, body: dict, headers):
        self.body = body
        self.token = headers.get("x-user-token")
        self.method = body.get("method")
        self.params = body.get("params") or {}


def mcp_envelope(*, err_code=0, result=RESUME_BODY, tool_name="my-resume") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{
                "type": "text",
                "text": json.dumps(
                    {"data": {"result": result}, "errCode": err_code},
                    ensure_ascii=False,
                ),
            }],
        },
    }


class FakeMCP:
    def __init__(self, handler_mode: str = "ok"):
        """handler_mode: ok | raw_json | errcode | empty_result | http500 |
        bad_json | jsonrpc_error

        `mode` 是**可读属性**，测试可以在构造后改它（一个服务实例跑多种响应形状，
        不用重开端口）。
        """
        self.mode = handler_mode
        self.calls: list[Call] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):       # 别把噪声打到测试输出里
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8")
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    body = {"_raw": raw}
                outer.calls.append(Call(body, self.headers))

                if outer.mode == "http500":
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"boom")
                    return

                if outer.mode == "errcode":
                    payload = mcp_envelope(err_code=43001)
                elif outer.mode == "empty_result":
                    payload = mcp_envelope(result="   ")
                elif outer.mode == "jsonrpc_error":
                    payload = {"jsonrpc": "2.0", "id": 1,
                               "error": {"code": -32601, "message": "tool not found"}}
                else:
                    payload = mcp_envelope()

                text = json.dumps(payload, ensure_ascii=False)
                if outer.mode == "bad_json":
                    text = "{坏"

                if outer.mode == "raw_json":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(text.encode("utf-8"))
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(f"event: message\ndata: {text}\n\n".encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    @property
    def last(self) -> Call:
        assert self.calls, "假 MCP 一个请求都没收到——脚本没走网络？"
        return self.calls[-1]


def write_config(tmp_path: pathlib.Path, url: str,
                 token: str = FAKE_TOKEN) -> pathlib.Path:
    """造一份指向假服务的 mcp.json。真配置一个字节都不读。"""
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps({
        "mcpServers": {
            "liepin-mcp": {"url": url, "headers": {"x-user-token": token}}
        }
    }, ensure_ascii=False), encoding="utf-8")
    return p
```

> `raw_json` 这个 mode 是给 `_rpc` 的另一条分支用的：
> `payload = "\n".join(lines) if lines else raw`。默认那几个用例只走 `lines` 那条，
> 裸 JSON 那条一步没跑过。所以补一条 `test_bare_json_body_also_parses`。

### Step 2 写失败测试

`tests/test_resume_integration.py`：

```python
import pytest

import resume
from fake_mcp import FAKE_TOKEN, RESUME_BODY, FakeMCP, write_config


@pytest.fixture
def mcp():
    srv = FakeMCP()
    yield srv
    srv.stop()


@pytest.fixture
def online(mcp, tmp_path, monkeypatch):
    monkeypatch.setattr(resume, "MCP_CONFIG", write_config(tmp_path, mcp.url))
    return mcp


def test_happy_path_prints_resume_body(online, capsys):
    assert resume.main([]) == 0
    out = capsys.readouterr().out
    assert "AI 产品经理" in out
    assert out.strip() == RESUME_BODY.strip()


def test_only_my_resume_is_ever_called(online):
    """红线在协议层的落点：请求体里的工具名。"""
    resume.main([])
    resume.fetch_resume()
    for call in online.calls:
        assert call.params["name"] == "my-resume"
        assert call.method == "tools/call"


def test_token_is_actually_sent(online):
    resume.main([])
    assert online.last.token == FAKE_TOKEN


def test_token_never_appears_in_output(online, capsys):
    resume.main([])
    io = capsys.readouterr()
    assert FAKE_TOKEN not in io.out
    assert FAKE_TOKEN not in io.err


def test_token_never_appears_in_error_output(tmp_path, monkeypatch, capsys):
    """失败路径最容易顺手把配置内容打出来。故意指到一个连不上的端口。"""
    srv = FakeMCP()
    url = srv.url
    srv.stop()
    monkeypatch.setattr(resume, "MCP_CONFIG", write_config(tmp_path, url))
    assert resume.main([]) == 1
    io = capsys.readouterr()
    assert FAKE_TOKEN not in io.out and FAKE_TOKEN not in io.err
    assert "连接失败" in io.err


def test_business_errcode_is_not_success(online, capsys):
    online.mode = "errcode"
    assert resume.main([]) == 1
    assert "43001" in capsys.readouterr().err


def test_empty_resume_body_is_not_success(online, capsys):
    online.mode = "empty_result"
    assert resume.main([]) == 1
    assert "result 是空的" in capsys.readouterr().err


def test_http_500_is_not_success(online, capsys):
    online.mode = "http500"
    assert resume.main([]) == 1
    assert "HTTP 500" in capsys.readouterr().err


def test_jsonrpc_error_is_not_success(online, capsys):
    online.mode = "jsonrpc_error"
    assert resume.main([]) == 1
    assert "tool not found" in capsys.readouterr().err


def test_unparsable_body_is_not_success(online, capsys):
    online.mode = "bad_json"
    assert resume.main([]) == 1
    assert "无法解析" in capsys.readouterr().err


def test_dead_port_is_not_success(tmp_path, monkeypatch, capsys):
    srv = FakeMCP()
    url = srv.url
    srv.stop()                       # 端口关掉，连接必被拒
    monkeypatch.setattr(resume, "MCP_CONFIG", write_config(tmp_path, url))
    assert resume.main([]) == 1
    assert "连接失败" in capsys.readouterr().err


def test_sse_frame_is_parsed(online):
    """假服务默认回 SSE；这条能过就说明 `data:` 抽取那条路是真的。"""
    assert "AI 产品经理" in resume.fetch_resume()


def test_bare_json_body_also_parses(online):
    """_rpc 有两条解析分支，SSE 那几个用例只喂了 `data:` 那条。"""
    online.mode = "raw_json"
    assert "AI 产品经理" in resume.fetch_resume()
```

### Step 3 跑红 → 实现 → 跑绿

Task 6 已经把 `resume.py` 写完了，所以这一步**预期大部分直接绿**。
跑出来要是有红的，那才是真发现（最可能的一处：SSE 帧里带 `event: message` 行，
`_rpc` 的 `splitlines()` 抽取要能跳过它——照抄的实现是能跳过的，所以应该过）。

```bash
cd ai_pm_interview_coach && python -m pytest tests/test_resume_integration.py -q
```
期望 13 passed；全量 98 passed。

**提交：** `出题教练集成测试：假 MCP 钉住 my-resume、令牌不外泄、失败非零退出`

---

## Task 8：`attempts.py` —— 留痕

**文件：** 创建 `tests/test_attempts.py`、`scripts/attempts.py`。

设计里定的是「记，但不做复习机制」。所以这里有 `record` / `history` / `weak` 三个命令，
**没有** next-review 之类的时间调度：`weak` 只是把「错过几次的题」列出来给人看，
不决定下一轮抽什么（抽题是 `bank.py sample --fresh` 的事）。

一个刻意的不对称，写测试时容易搞混：

- **`record` 拒绝孤儿**：`qid` 不在题库里就报错。刚答完的题不可能不在题库里，
  对不上只可能是 id 打错了——这时候记下去是一条永远查不到的假记录。
- **`history` / `weak` 容忍孤儿**：题后来被 `remove` 掉了，历史记录不能因此消失或报错。
  台账是事实，不是外键表。

### Step 1 写失败测试

```python
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
    assert banked[0] not in out


def test_weak_on_empty_is_not_silently_fine(banked):
    rc, _, err = run_cli(attempts.main, ["weak"])
    assert rc == 1
    assert "还没有答过的题" in err


def test_missing_stdin_is_error(banked):
    rc, _, err = record("")
    assert rc == 1
    assert "stdin" in err
```

### Step 2 跑红

`ModuleNotFoundError: No module named 'attempts'`。

### Step 3 实现 `scripts/attempts.py`

```python
"""答题留痕。

  attempts.py record            从 stdin 读 {qid, answer, verdict, feedback}，追加一条
  attempts.py history [qid]     看记录（不给 qid 就全量）
  attempts.py weak              错过且最后一次没答对的题，按错过次数降序

只留痕，不排复习计划——「什么时候再练」不是这里决定的。
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

import models
import store


def _fail(msg: str) -> int:
    print(f"❌ {msg}", file=sys.stderr)
    return 1


def _bank_ids() -> set[str]:
    return {r["id"] for r in store.read_rows(store.BANK_PATH, store.BANK_FIELDS)}


def _read_attempts() -> list[dict]:
    return store.read_rows(store.ATTEMPTS_PATH, store.ATTEMPT_FIELDS)


def cmd_record(_args) -> int:
    try:
        payload = models.parse_input(models.AttemptInput, sys.stdin.read(), src="stdin")
    except models.InputError as e:
        return _fail(str(e))

    try:
        if payload.qid not in _bank_ids():
            return _fail(f"题库里没有 id={payload.qid}，这条记录将来查不到对应题目，不记")
    except ValueError as e:
        return _fail(str(e))

    at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    store.append_row(store.ATTEMPTS_PATH, {
        "at": at,
        "qid": payload.qid,
        "answer": payload.answer,
        "verdict": payload.verdict,
        "feedback": payload.feedback,
    }, store.ATTEMPT_FIELDS)
    print(f"已记录 {payload.verdict}  {payload.qid}")
    return 0


def cmd_history(args) -> int:
    try:
        rows = _read_attempts()
        questions = {r["id"]: r["question"] for r in
                     store.read_rows(store.BANK_PATH, store.BANK_FIELDS)}
    except ValueError as e:
        return _fail(str(e))

    if args.qid:
        rows = [r for r in rows if r["qid"] == args.qid]
        if not rows:
            return _fail(f"id={args.qid} 没答过——不是失败，但也没东西可看")
    print(f"共 {len(rows)} 条")
    for r in rows:
        q = questions.get(r["qid"], "（题已从题库删除）")
        one_line = " ".join(q.split())[:40]
        print(f"{r['at']}  {r['verdict']:<4}  {r['qid']}  {one_line}")
        print(f"    答：{' '.join(r['answer'].split())[:80]}")
        if r["feedback"]:
            print(f"    评：{' '.join(r['feedback'].split())[:80]}")
    return 0


def cmd_weak(_args) -> int:
    try:
        rows = _read_attempts()
    except ValueError as e:
        return _fail(str(e))
    if not rows:
        return _fail("还没有答过的题——没有弱项可列，不是成功")

    by_q: dict[str, list[dict]] = {}
    for r in rows:
        by_q.setdefault(r["qid"], []).append(r)

    try:
        questions = {r["id"]: r["question"] for r in
                     store.read_rows(store.BANK_PATH, store.BANK_FIELDS)}
    except ValueError as e:
        return _fail(str(e))

    weak = []
    for qid, recs in by_q.items():
        misses = sum(1 for r in recs if r["verdict"] in ("错", "部分对"))
        if misses and recs[-1]["verdict"] != "对":
            weak.append((misses, qid, recs[-1]["at"]))
    if not weak:
        return _fail("没有弱项——全部答对，不是失败但也没得练")

    weak.sort(key=lambda t: (-t[0], t[2]))
    for misses, qid, _last in weak:
        q = " ".join(questions.get(qid, "（题已从题库删除）").split())[:60]
        print(f"{misses} 次  {qid}  {q}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="attempts.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="从 stdin 记一条答题")
    r.set_defaults(fn=cmd_record)
    h = sub.add_parser("history", help="看答题记录")
    h.add_argument("qid", nargs="?")
    h.set_defaults(fn=cmd_history)
    w = sub.add_parser("weak", help="列出弱项")
    w.set_defaults(fn=cmd_weak)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except ValueError as e:
        return _fail(str(e))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

**三处不要动：**

1. `cmd_weak` 用 `recs[-1]` 判「最后一次」——依赖记录是**追加序**。
   这正是 `write_rows` 不参与 record 路径的原因：记录永不被重写，追加序就是时间序。
2. `misses` 把 `部分对` 也算错过。部分对就是还没到能上场的程度，
   只数 `错` 会低估。
3. `weak` 没弱项时 **exit 1**。这条容易被后来的人「优化」成 0——
   但它跟 `sample` 空题池是同一个道理：调用方（我）需要根据退出码判断有没有可练的东西，
   静默的「列了个空表」会被当成有结果。

### Step 4 跑绿

期望 17 passed（新增 17）；全量 115 passed。

**提交：** `出题教练 attempts.py：追加式留痕 + history/weak，无弱项不是成功`

---

## Task 9：端到端 + 「真数据一根毛都没动」的守卫

**文件：** 创建 `tests/test_e2e.py`；改 `scripts/store.py`、`tests/conftest.py`。

前面所有测试都是**同进程调用 `main()`**，靠 `monkeypatch` 改模块常量。
端到端不一样：真的起子进程、真的走完一轮命令链。这时候 `monkeypatch` 够不着了
（那是另一个进程的内存），得有个**进程边界上的**重定向口子。

### Step 1 写失败测试

`tests/test_e2e.py`：

```python
"""真起子进程跑一整轮。这层验证的是「接缝」，不是单个命令。"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"


def run(script: str, *args: str, env: dict, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        input=stdin, capture_output=True, text=True, encoding="utf-8",
        env=env, timeout=60,
    )


@pytest.fixture
def sandbox(tmp_path):
    """把三个数据路径用环境变量指到 tmp——真 bank/ 一个字节都碰不到。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["COACH_BANK_PATH"] = str(tmp_path / "bank" / "questions.jsonl")
    env["COACH_ATTEMPTS_PATH"] = str(tmp_path / "attempts" / "attempts.jsonl")
    env["COACH_CONFIG"] = str(tmp_path / "config.json")
    (tmp_path / "config.json").write_text('{"per_round": 2}', encoding="utf-8")
    return env


def test_full_round_trip(sandbox):
    """一条链：存题 → 抽题 → 看题 → 记一条 → 看历史 → 列弱项。"""
    for i in range(3):
        r = run("bank.py", "add", env=sandbox, stdin=json.dumps({
            "question": f"题{i}", "refAnswer": f"答{i}",
            "kind": "通用", "source": "e2e",
        }, ensure_ascii=False))
        assert r.returncode == 0, r.stderr

    r = run("bank.py", "sample", "-n", "2", "--seed", "7", env=sandbox)
    assert r.returncode == 0, r.stderr
    picked = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(picked) == 2

    r = run("bank.py", "show", picked[0], env=sandbox)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["id"] == picked[0]

    r = run("attempts.py", "record", env=sandbox, stdin=json.dumps({
        "qid": picked[0], "answer": "我的答", "verdict": "错", "feedback": "没成体系",
    }, ensure_ascii=False))
    assert r.returncode == 0, r.stderr

    r = run("attempts.py", "history", picked[0], env=sandbox)
    assert r.returncode == 0, r.stderr
    assert "错" in r.stdout

    r = run("attempts.py", "weak", env=sandbox)
    assert r.returncode == 0, r.stderr
    assert picked[0] in r.stdout

    # --fresh 现在该把答过的那题排掉
    r = run("bank.py", "sample", "-n", "5", "--fresh", env=sandbox)
    assert picked[0] not in r.stdout.split()


def test_stderr_is_utf8_not_mojibake(sandbox, tmp_path):
    """Windows 上最容易翻车的：中文错误信息进 stderr。"""
    r = run("bank.py", "add", env=sandbox, stdin="{}")
    assert r.returncode == 1
    assert "question" in r.stderr


def test_duplicate_add_via_subprocess_also_refused(sandbox):
    payload = json.dumps({"question": "同题", "refAnswer": "答",
                          "kind": "通用", "source": "s"}, ensure_ascii=False)
    assert run("bank.py", "add", env=sandbox, stdin=payload).returncode == 0
    bank_file = pathlib.Path(sandbox["COACH_BANK_PATH"])
    before = bank_file.read_bytes()
    r = run("bank.py", "add", env=sandbox, stdin=payload)
    assert r.returncode == 1
    assert bank_file.read_bytes() == before
```

### Step 2 跑红

三个用例全红：`store` 还不认环境变量，子进程会往**真的 `bank/`** 里写。

**这一步跑之前先确认 `bank/` 和 `attempts/` 现在是空的或不存在**
（`ls ai_pm_interview_coach/`）。如果已经有真数据，先自己挪走再跑红——
这条是红线，不是可以「跑完再恢复」的事。

### Step 3 实现：`store.py` 顶部加环境变量口子

```python
def _path_from_env(var: str, default: pathlib.Path) -> pathlib.Path:
    """测试/多副本用的路径覆盖。没设就用项目内的默认位置。"""
    val = os.environ.get(var)
    return pathlib.Path(val) if val else default


BANK_PATH = _path_from_env("COACH_BANK_PATH", ROOT / "bank" / "questions.jsonl")
ATTEMPTS_PATH = _path_from_env("COACH_ATTEMPTS_PATH", ROOT / "attempts" / "attempts.jsonl")
CONFIG_PATH = _path_from_env("COACH_CONFIG", ROOT / "config.json")
```

（替换掉原来那三行直接赋值的常量；`load_config` 不用改，它读的就是 `CONFIG_PATH`。）

### Step 4 加守卫：真数据必须整场测试一字不变

改 `tests/conftest.py`，加一个 **session 级 autouse** fixture。
它不改变任何行为，只在跑完整个测试会话后核对一次：真的 `bank/`、`attempts/`
还是不是我开始前的样子。**只要有一个测试忘了重定向，这里就会红。**

```python
def _snapshot(root: pathlib.Path) -> dict:
    if not root.exists():
        return {"__missing__": True}
    out = {"__missing__": False}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = (p.stat().st_size, p.stat().st_mtime_ns)
    return out


@pytest.fixture(scope="session", autouse=True)
def real_data_untouched():
    """整个测试会话期间，项目内的真 bank/ 与 attempts/ 必须一个字节都不变。

    忘了重定向的测试会在这里现形——不用人去 review 每个用例有没有 leak。
    """
    import store

    targets = [store.ROOT / "bank", store.ROOT / "attempts"]
    before = {str(t): _snapshot(t) for t in targets}
    yield
    for t in targets:
        assert _snapshot(t) == before[str(t)], f"真数据被动过：{t}"
```

> 用 size + mtime_ns 而不是读全文比对：这两项足以证明「没写过」。
> 读全文做哈希只有在「担心有人原地重写出完全相同的大小和时间戳」时才有意义，
> 而那不是我防的失败模式（我防的是某个测试忘了重定向，真往项目里 append 一行）。

守卫报的是 **session 结束时的 teardown ERROR**，泄漏那个用例自己仍然是 `passed`。
所以看到 `119 passed, 1 error` 别当成小瑕疵——那就是有测试没重定向，去查谁写的真目录。

### Step 5 跑绿 + 全量回归

```bash
cd ai_pm_interview_coach && python -m pytest tests -q
```
期望 115 + 3 = 118 passed。

再跑一次 job_seeking 的老套件，确认没跨项目串味：

```bash
cd ../job_seeking && python -m pytest tests -q
```
期望 91 passed（worktree 基线就是这个数）。

**提交：** `出题教练端到端测试 + COACH_* 路径覆盖 + 真数据不变守卫`

---

## Task 10：lint 闸门 —— 让 `ruff.toml` 变成一条会红的测试

**文件：** 创建 `tests/test_lint.py`。

为什么单独占一个任务、而不是「记得手动跑一下 ruff」：手动的事会忘。
写进测试目录里，`pytest -q` 就会替我记住，而且和真数据守卫一样在 CI/本地同一条命令里。

### Step 1 写测试

```python
"""lint 闸门。ruff 找不到就 skip——但 Task 0 把它列为必装，
skip 本身就说明环境没按 Task 0 建，这条别当成「过」。（`-rs` 会显式报 skip 原因。）"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def ruff():
    exe = shutil.which("ruff")
    if exe is None:
        pytest.skip("ruff 未安装：Task 0 第 0 步要求 `uv tool install ruff`")
    return exe


def test_ruff_is_configured():
    assert (ROOT / "ruff.toml").exists(), "没有配置文件，ruff 会用它的全默认而不是我们的"


def test_scripts_and_tests_are_clean(ruff):
    r = subprocess.run([ruff, "check", "scripts", "tests"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, f"ruff 报了问题，先修再提交：\n{r.stdout}{r.stderr}"


def test_the_gate_actually_catches_something(tmp_path, ruff):
    """select 配错、一条规则都没挑中时，「ruff 全绿」是个假信号。
    喂一个它必须拦的东西，证明闸门有牙齿。"""
    bad = tmp_path / "bad.py"
    bad.write_text("import json\n", encoding="utf-8")  # F401：未使用的 import
    r = subprocess.run([ruff, "check", "--config", str(ROOT / "ruff.toml"), str(bad)],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0, "连未使用的 import 都不报，说明 select 没挑中 F"
    assert "F401" in r.stdout
```

### Step 2 跑

```bash
cd ai_pm_interview_coach && .venv/Scripts/python -m pytest tests/test_lint.py -q
```

**这里大概率不会直接绿**——前 9 个任务的代码是照「跑对」写的，没照 ruff 写过。
这正是这个任务的作用：把攒下的问题一次清掉。

### Step 3 修到绿

```bash
ruff check scripts tests            # 看全量
ruff check --fix scripts tests      # 能自动修的先让 ruff 自己修
```

**只改 ruff 报的那些，不动逻辑。** 修完必须重跑全量测试：
`--fix` 会删 import、会把 `x == None` 换成 `x is None`，这类改动做错一处就是行为变化。

如果某条 ruff 报得没道理（比如它坚持要把中文常量改成 ASCII 命名），
**在 `ruff.toml` 的 `ignore` 里加规则并写一行为什么**，不要在代码里
`# noqa` 到处贴——`noqa` 是「这一处我确认过」，`ignore` 是「这条规则整个项目不适用」。
前者用于例外，后者用于不合身，混用会让下次读代码的人分不清你当时是哪种判断。

### Step 4 跑绿 + 全量回归

期望 3 passed。`test_the_gate_actually_catches_something` 是**自测**：
它故意喂 ruff 一个未使用的 import，要求它必须报 `F401`。这条绿了才说明
上一节「全绿」不是「一条规则都没配」换来的假信号。

**提交：** `出题教练 lint 闸门：ruff 进测试目录，并附「闸门有牙齿」自证`

---

## Task 11：README —— 写「怎么用」，不写「怎么实现」

**文件：** 改 `ai_pm_interview_coach/README.md`。

内容（一次 call 的实际命令序列，跟设计文档的 7 步对齐）：

```markdown
# AI 产品经理面试出题教练

脚本只做确定性的活；搜索、出题、判分由会话里的 AI 做。

## 一轮怎么用

    python scripts/resume.py                      # 读在线简历，我据此出题的靶子
    python scripts/bank.py sample --fresh         # 抽本轮题（只出 id）
    python scripts/bank.py show <id>              # 看题面和参考答案
    # 我作答 → AI 搜索面经、出题、判分
    echo '{"qid":"<id>","answer":"…","verdict":"部分对","feedback":"…"}' \
      | python scripts/attempts.py record         # 留痕
    python scripts/attempts.py weak               # 现在哪几题还不行

## 加真题

    echo '{"question":"…","refAnswer":"…","kind":"简历深挖","source":"…"}' \
      | python scripts/bank.py add

同指纹（同题面）会**拒绝且不覆盖**，所以导入可以重复跑。

## 三个退出码约定

- `0` 有结果
- `1` 没结果或输入不合法（「没抽到题」不是成功）
- stderr 永远说清是哪个文件、第几行、什么字段、期望什么

## 令牌

只从 `~/.workbuddy/mcp.json` 读，只读 `my-resume`，不落盘、不打印、不进 git。
```

**提交：** `出题教练 README：一轮的实际命令序列与退出码约定`

---

## 完成标准

- [ ] `cd ai_pm_interview_coach && .venv/Scripts/python -m pytest tests -q` 全绿（121 个用例）。
- [ ] 其中 `test_lint.py` 三条是绿的——即 `ruff check scripts tests` 零输出，
      且它自证的「闸门有牙齿」那条也过（不是靠 select 配空换来的绿）。
- [ ] `cd ../job_seeking && python -m pytest tests -q` 仍 91 全绿。
- [ ] 手工跑一遍 `resume.py`，确认能读到真简历、且 `git status` 干净（没有新文件冒出来）。
- [ ] 真 `bank/`、`attempts/` 在整个测试会话里字节不变（守卫测试红过就说明没做到）。
- [ ] 全仓 `grep` 一遍真令牌串，零命中。

## 执行选择

计划到这里就完整了。两种走法：

1. **本会话逐任务执行**（subagent-driven-development）：一个任务一个子代理，
   每个任务跑完我 review 一次再继续。慢一点，但每步都有人看。
2. **开新会话执行**（executing-plans）：把这份计划原样喂给一个干净的会话，
   它按任务顺序跑完再来找你。

**别混着来**：同一个任务在两个地方跑会互相覆盖工作树。


---

---

## 附录：这份计划已经跑过两遍（2026-09-23）

### 怎么复现这次验证

```bash
cd ai_pm_interview_coach
.venv/Scripts/python.exe docs/plans/build_plan_check.py --pytest
```

`docs/plans/build_plan_check.py` 把计划里每个任务的代码块**原样**抽到一个临时目录
（`models.py` / `store.py` / `bank.py` / `resume.py` / `attempts.py` + `fake_mcp.py`
+ 全部测试 + `conftest.py` + `ruff.toml`），然后直接 `pytest`。
改完计划就重跑一次——表里的数字是这么来的，不是我估的。
`docs/plans/patch_lines.py` 是配套的定点改写工具（按行号替换、先断言原文），
用来避免「全局 replace 打错地方」——这个错我真犯过，见下面第 2 条。

### 全量结果

`121 passed in 14.96s`。按文件的用例数（`--collect-only -q`）：

| 文件 | 用例 | 属于 | 累计 |
| --- | --- | --- | --- |
| `test_models.py` | 27 | Task 2 | 27 |
| `test_store.py` | 19 | Task 3 | 46 |
| `test_bank_add.py` | 9 | Task 4 | 55 |
| `test_bank_list.py` / `test_bank_remove.py` / `test_bank_sample.py` | 5 + 3 + 12 | Task 5 | 75 |
| `test_resume_config.py` | 10 | Task 6 | 85 |
| `test_resume_integration.py` | 13 | Task 7 | 98 |
| `test_attempts.py` | 17 | Task 8 | 115 |
| `test_e2e.py` | 3 | Task 9 | 118 |
| `test_lint.py` | 3 | Task 10 | **121** |

**所以逐任务执行时，跑红跑绿的数量应当和这张表一致。**
对不上就是环境或抄写有出入，先查清楚再往下走。

### 第一遍跑出来的三个真缺陷（已改进正文）

1. **`write_rows` 用了 `tmp.open(..., closefd=False)`** →
   `TypeError: Path.open() got an unexpected keyword argument 'closefd'`。
   `mkstemp` 给的是裸 fd，必须 `os.fdopen`。见 Task 3 的说明。
2. **`test_bank_sample.py` 用了 `attempt_row` 却没 import** → 2 个 `NameError`。
   （是我把一处 import 修改误做成了全局替换带进来的。）
3. **`test_full_round_trip` 里写成
   `assert rc == 0, r.stderr and "错" in r.stdout`** —— 后半截被当成了断言消息，
   等于没断言。拆成两条。

### 第二遍（加进 `models.py` 和 lint 闸门之后）跑出来的

4. **`store.read_rows` 里 `if not path.exists(): return []` 挡在 `_model_for` 前面** →
   传错 `fields` 元组时，只要文件不存在就静默返回空列表，那句「store 不认这组字段」
   永远走不到。新写的 `test_unknown_fields_tuple_is_a_clear_error` 直接抓到这条。
   改成进函数先解析模型：参数错是调用方的编程错误，与文件在不在无关。

5. **`ruff check scripts tests` 第一次跑报 208 条。** 其中约 190 条是
   `RUF001/002/003`——把中文的「，」「：」「（）」报成 "Did you mean ,"。
   这正好是我在 `ruff.toml` 注释里承诺要放行、却只写了个 `"RUF"` 大类没细挑的那几条。
   现在显式 ignore 并写了理由（`RUF` 的其它条目如 `RUF059` 仍然生效）。
   **剩下 17 条是真问题**，逐个改了：
   - 2 个未使用的 import（`test_bank_add.py` 的 `pytest`、`test_resume_integration.py` 的 `json`）；
   - `fake_mcp.py` 里 `.encode("utf-8")` 的多余参数（`str.encode` 本来就是 utf-8）；
   - `resume.py` 一处 `except` 里 `raise SystemExit(...)` 没写 `from None`，
     会把 JSONDecodeError 的链一起打出来——B904；
   - 11 处 `rc, out, err = run_cli(...)` 里有一个变量从来不用（`RUF059`）。

   最后这类的修法值得说一句：**不是全都改成 `_` 就完事。**
   有几处是测试本该断 `rc == 0` 却没断（`bank list` / `bank sample` / `attempts history`），
   我把 `_` 换成 `err` 并补上 `assert rc == 0, err`——顺手堵掉「命令报错也能过」的假绿。
   `test_weak_treats_last_correct_as_not_weak` 反过来：那种情况下 `weak` **本来就该返回 1**
   （没有弱项不是成功），所以补的是 `assert rc == 1`。
   同一个 linter 抱怨，有两种相反的修法；照它默认的 `--fix` 走会全变成 `_`，
   把那三个漏断言继续留在那儿。

6. **`test_field_tuples_derive_from_models` 是同义反复**：
   它断言 `models.BANK_FIELDS == tuple(models.BankRow.model_fields)`，而 `BANK_FIELDS`
   的定义就是 `tuple(BankRow.model_fields)`——把字段改名它照样绿，
   而那正是会让已有 `bank/questions.jsonl` 全部读不出来的改动类型。
   改成 `test_field_tuples_are_the_on_disk_format`，写字面值把落盘格式钉住
   （`SIM300` 顺带消失，但那是次要的）。

7. **`store` 顶部 docstring 里一句 markup 写坏了**（`**接上_row 行号_再抛出去`），
   读起来是噪声。改平。

守卫本身也有牙齿，单独验过：临时塞一个「忘了重定向、直接往 `store.ROOT/bank/` 写」
的用例，session teardown 立刻报 `AssertionError: 真数据被动过`。
lint 闸门有同类的自测（`test_the_gate_actually_catches_something`），
所以「121 passed」不等于「把规则调到空换来的绿」。
