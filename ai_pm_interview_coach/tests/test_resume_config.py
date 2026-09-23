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
