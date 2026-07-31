"""Test tích hợp tầng mô hình ngôn ngữ với mock Ollama.

Không gọi Ollama thật. Thay vào đó, mock ``urllib.request.urlopen`` để kiểm tra
toàn bộ luồng từ đầu vào → xây prompt → gửi HTTP → xử lý response → đầu ra.

Mục đích:
- Kiểm tra ``_generate()`` xử lý đúng mọi dạng response (thành công, timeout,
  HTTP error, JSON lỗi, response rỗng).
- Kiểm tra luồng đầy đủ của từng entrypoint khi Ollama trả lời đúng.
- Kiểm tra ``<think>`` block bị cắt trong luồng thật.
- Kiểm tra request body gửi cho Ollama đúng schema.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import llm


# ══════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════
CFG = {
    "llm": {"enabled": True, "base_url": "http://127.0.0.1:11434", "model": "gemma3:4b", "timeout_sec": 10},
    "checkin": {"late_after_min": 10},
}


def _make_ollama_response(response_text: str) -> MagicMock:
    """Tạo một mock response giống urllib.request.urlopen trả về."""
    payload = json.dumps({"response": response_text}).encode("utf-8")
    mock = MagicMock()
    mock.read.return_value = payload
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def _capture_request(monkeypatch) -> dict[str, Any]:
    """Bắt request body gửi cho Ollama và trả response cố định."""
    captured: dict[str, Any] = {}

    def fake_urlopen(req, **kwargs):
        captured["url"] = req.full_url
        captured["method"] = req.method
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = kwargs.get("timeout")
        return _make_ollama_response("OK")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return captured


# ══════════════════════════════════════════════════════════════════════════
# _generate — xử lý response
# ══════════════════════════════════════════════════════════════════════════
class TestGenerateResponseHandling:
    def test_success_returns_text(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: _make_ollama_response("Học viên vắng 3 buổi."),
        )
        result = llm._generate("test prompt", CFG)
        assert result == "Học viên vắng 3 buổi."

    def test_strips_think_block_from_response(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: _make_ollama_response(
                "<think>suy nghĩ nội tâm rất dài</think>Câu trả lời sạch."
            ),
        )
        result = llm._generate("test", CFG)
        assert result == "Câu trả lời sạch."
        assert "suy nghĩ" not in result

    def test_empty_response_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: _make_ollama_response(""),
        )
        assert llm._generate("test", CFG) is None

    def test_only_think_block_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: _make_ollama_response("<think>chỉ suy nghĩ</think>"),
        )
        assert llm._generate("test", CFG) is None

    def test_timeout_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: (_ for _ in ()).throw(TimeoutError()),
        )
        assert llm._generate("test", CFG) is None

    def test_connection_refused_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: (_ for _ in ()).throw(
                urllib.error.URLError("Connection refused")
            ),
        )
        assert llm._generate("test", CFG) is None

    def test_http_error_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: (_ for _ in ()).throw(
                urllib.error.HTTPError(
                    url="http://test", code=500, msg="ISE",
                    hdrs=None, fp=io.BytesIO(b""),  # type: ignore[arg-type]
                )
            ),
        )
        assert llm._generate("test", CFG) is None

    def test_malformed_json_returns_none(self, monkeypatch):
        mock = MagicMock()
        mock.read.return_value = b"not json at all"
        mock.__enter__ = lambda s: s
        mock.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: mock)
        assert llm._generate("test", CFG) is None

    def test_os_error_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: (_ for _ in ()).throw(OSError("Network down")),
        )
        assert llm._generate("test", CFG) is None

    def test_disabled_returns_none_without_network_call(self, monkeypatch):
        call_count = {"n": 0}

        def should_not_be_called(*a, **k):
            call_count["n"] += 1

        monkeypatch.setattr("urllib.request.urlopen", should_not_be_called)
        result = llm._generate("test", {"llm": {"enabled": False}})
        assert result is None
        assert call_count["n"] == 0


# ══════════════════════════════════════════════════════════════════════════
# _generate — request body
# ══════════════════════════════════════════════════════════════════════════
class TestGenerateRequestBody:
    def test_url_constructed_correctly(self, monkeypatch):
        captured = _capture_request(monkeypatch)
        llm._generate("test", CFG)
        assert captured["url"] == "http://127.0.0.1:11434/api/generate"

    def test_url_strips_trailing_slash(self, monkeypatch):
        captured = _capture_request(monkeypatch)
        cfg = {**CFG, "llm": {**CFG["llm"], "base_url": "http://127.0.0.1:11434/"}}
        llm._generate("test", cfg)
        assert captured["url"] == "http://127.0.0.1:11434/api/generate"

    def test_method_is_post(self, monkeypatch):
        captured = _capture_request(monkeypatch)
        llm._generate("test", CFG)
        assert captured["method"] == "POST"

    def test_body_has_required_fields(self, monkeypatch):
        captured = _capture_request(monkeypatch)
        llm._generate("test prompt", CFG, temperature=0.5, num_predict=100)
        body = captured["body"]
        assert body["model"] == "gemma3:4b"
        assert body["prompt"] == "test prompt"
        assert body["stream"] is False
        assert body["think"] is False
        assert body["options"]["temperature"] == 0.5
        assert body["options"]["num_predict"] == 100

    def test_system_prompt_defaults_to_grounding(self, monkeypatch):
        captured = _capture_request(monkeypatch)
        llm._generate("test", CFG)
        assert captured["body"]["system"] == llm._GROUNDING

    def test_custom_system_prompt(self, monkeypatch):
        captured = _capture_request(monkeypatch)
        llm._generate("test", CFG, system="Custom system")
        assert captured["body"]["system"] == "Custom system"

    def test_format_json_included_when_specified(self, monkeypatch):
        captured = _capture_request(monkeypatch)
        llm._generate("test", CFG, fmt="json")
        assert captured["body"]["format"] == "json"

    def test_format_not_included_when_none(self, monkeypatch):
        captured = _capture_request(monkeypatch)
        llm._generate("test", CFG)
        assert "format" not in captured["body"]

    def test_timeout_from_config(self, monkeypatch):
        captured = _capture_request(monkeypatch)
        llm._generate("test", CFG)
        assert captured["timeout"] == 10.0

    def test_default_timeout(self, monkeypatch):
        captured = _capture_request(monkeypatch)
        cfg = {"llm": {"enabled": True}}
        llm._generate("test", cfg)
        assert captured["timeout"] == 60.0

    def test_default_model(self, monkeypatch):
        captured = _capture_request(monkeypatch)
        cfg = {"llm": {"enabled": True}}
        llm._generate("test", cfg)
        assert captured["body"]["model"] == "qwen3:8b"


# ══════════════════════════════════════════════════════════════════════════
# Luồng đầy đủ: write_diagnosis
# ══════════════════════════════════════════════════════════════════════════
class TestWriteDiagnosisIntegration:
    def test_full_flow_returns_diagnosis(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: _make_ollama_response(
                "Học viên vắng 2 buổi trong 5 buổi gần nhất, cần theo dõi."
            ),
        )
        trace = {
            "level": "watch", "as_of": "2026-07-30",
            "counts": {"absent": 2, "late": 0, "sessions_considered": 5},
            "signals": [], "history": [],
        }
        result = llm.write_diagnosis(trace, CFG)
        assert result is not None
        assert "vắng" in result.lower() or "Học viên" in result

    def test_returns_none_when_disabled(self):
        cfg = {"llm": {"enabled": False}, "checkin": {"late_after_min": 10}}
        trace = {"level": "ok", "counts": {"absent": 0, "late": 0, "sessions_considered": 5}}
        assert llm.write_diagnosis(trace, cfg) is None

    def test_think_block_stripped_in_diagnosis(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: _make_ollama_response(
                "<think>phân tích dài dòng</think>Học viên có 2 buổi vắng."
            ),
        )
        trace = {
            "level": "watch", "as_of": "2026-07-30",
            "counts": {"absent": 2, "late": 0, "sessions_considered": 5},
            "signals": [], "history": [],
        }
        result = llm.write_diagnosis(trace, CFG)
        assert "phân tích dài dòng" not in result
        assert "Học viên có 2 buổi vắng" in result


# ══════════════════════════════════════════════════════════════════════════
# Luồng đầy đủ: draft_message
# ══════════════════════════════════════════════════════════════════════════
class TestDraftMessageIntegration:
    def test_full_flow_returns_message(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: _make_ollama_response(
                "Em ơi, thầy thấy em vắng 2 buổi gần đây. Em có gặp khó khăn gì không?"
            ),
        )
        trace = {
            "level": "watch", "as_of": "2026-07-30",
            "counts": {"absent": 2, "late": 0, "sessions_considered": 5},
            "signals": [], "history": [],
        }
        result = llm.draft_message(trace, "Nguyễn Văn A", CFG)
        assert result is not None
        assert "?" in result  # tin nhắn phải kết thúc bằng câu hỏi

    def test_returns_none_when_ollama_down(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: (_ for _ in ()).throw(
                urllib.error.URLError("Connection refused")
            ),
        )
        trace = {
            "level": "watch", "as_of": "2026-07-30",
            "counts": {"absent": 2, "late": 0, "sessions_considered": 5},
            "signals": [], "history": [],
        }
        assert llm.draft_message(trace, "Nguyễn Văn A", CFG) is None


# ══════════════════════════════════════════════════════════════════════════
# Luồng đầy đủ: ask_sql
# ══════════════════════════════════════════════════════════════════════════
class TestAskSqlIntegration:
    def test_full_flow_returns_clean_sql(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: _make_ollama_response(
                "```sql\nSELECT name FROM students WHERE active = 1 LIMIT 10\n```"
            ),
        )
        result = llm.ask_sql("liệt kê học viên đang học", CFG)
        assert result == "SELECT name FROM students WHERE active = 1 LIMIT 10"

    def test_strips_think_and_markdown(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: _make_ollama_response(
                "<think>tôi cần join bảng students</think>"
                "```sql\nSELECT COUNT(*) FROM students LIMIT 1\n```"
            ),
        )
        result = llm.ask_sql("bao nhiêu học viên", CFG)
        assert result == "SELECT COUNT(*) FROM students LIMIT 1"
        assert "think" not in result

    def test_returns_none_when_timeout(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: (_ for _ in ()).throw(TimeoutError()),
        )
        assert llm.ask_sql("test", CFG) is None


# ══════════════════════════════════════════════════════════════════════════
# Luồng đầy đủ: parse_leave_request
# ══════════════════════════════════════════════════════════════════════════
class TestParseLeaveIntegration:
    def test_full_flow_returns_structured_data(self, monkeypatch):
        response = json.dumps({
            "student_id": "K4001",
            "student_name": "Nguyễn Văn A",
            "dates": ["2026-08-01"],
            "category": "ốm",
            "reason_text": "em bị sốt",
            "has_evidence": False,
            "confidence": 0.9,
            "missing": [],
        })
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: _make_ollama_response(response),
        )
        result = llm.parse_leave_request(
            "Em K4001 Nguyễn Văn A xin nghỉ ngày mai vì bị sốt",
            CFG, today="2026-07-31",
        )
        assert result is not None
        assert result["student_id"] == "K4001"
        assert result["dates"] == ["2026-08-01"]
        assert result["category"] == "ốm"
        assert result["reason_text"] == "em bị sốt"
        assert result["missing"] == []
        assert "date_warnings" in result

    def test_end_to_end_with_category_normalization(self, monkeypatch):
        response = json.dumps({
            "dates": ["2026-08-01"],
            "category": "tự bịa",
            "reason_text": "test",
        })
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: _make_ollama_response(response),
        )
        result = llm.parse_leave_request("test", CFG, today="2026-07-31")
        assert result["category"] == "khác"

    def test_end_to_end_with_date_warning(self, monkeypatch):
        """Đơn nhắc thứ 3, model trả ngày thứ Hai → cảnh báo."""
        response = json.dumps({
            "dates": ["2026-08-03"],  # 2026-08-03 = thứ Hai
            "category": "ốm",
            "reason_text": "sốt",
        })
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: _make_ollama_response(response),
        )
        result = llm.parse_leave_request(
            "em xin nghỉ thứ 3 tuần sau", CFG, today="2026-07-31"
        )
        assert len(result["date_warnings"]) == 1

    def test_returns_none_when_ollama_returns_prose(self, monkeypatch):
        """Model phớt lờ yêu cầu trả JSON, trả văn xuôi."""
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: _make_ollama_response("Chào bạn, đơn xin nghỉ rất rõ ràng."),
        )
        assert llm.parse_leave_request("...", CFG, today="2026-07-31") is None

    def test_returns_none_when_connection_refused(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: (_ for _ in ()).throw(
                urllib.error.URLError("Connection refused")
            ),
        )
        assert llm.parse_leave_request("...", CFG, today="2026-07-31") is None


# ══════════════════════════════════════════════════════════════════════════
# Schema constants — regression
# ══════════════════════════════════════════════════════════════════════════
class TestSchemaConstants:
    def test_sql_schema_has_all_tables(self):
        for table in ("students", "sessions", "attendance", "anomaly_flags", "risk_snapshots"):
            assert table in llm.SQL_SCHEMA_HINT, f"bảng {table} thiếu trong schema hint"

    def test_sql_schema_does_not_leak_admin_tables(self):
        """Schema hint không được chứa bảng nhạy cảm."""
        for secret_table in ("admin_users", "admins", "sessions_auth", "qr_tokens"):
            assert secret_table not in llm.SQL_SCHEMA_HINT, \
                f"bảng nhạy cảm {secret_table} lọt vào schema hint"

    def test_sql_examples_demonstrate_not_exists(self):
        """Ví dụ SQL phải dùng NOT EXISTS cho câu hỏi vắng."""
        assert "NOT EXISTS" in llm.SQL_EXAMPLES

    def test_leave_categories_complete(self):
        expected = ["ốm", "việc gia đình", "lịch trùng", "đi lại", "khác"]
        assert llm.LEAVE_CATEGORIES == expected

    def test_grounding_mentions_tieng_viet(self):
        assert "tiếng Việt" in llm._GROUNDING

    def test_grounding_forbids_guessing(self):
        assert "không suy đoán" in llm._GROUNDING.lower() or "Không suy đoán" in llm._GROUNDING
