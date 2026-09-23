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
