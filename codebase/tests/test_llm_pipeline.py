"""Pipeline kiểm tra logic nội bộ của tầng mô hình ngôn ngữ.

Không test nào ở đây gọi Ollama. Mục đích là kiểm tra:
- Mọi hàm helper (``_strip_thinking``, ``_day``, ``_date_table``, ``_weekday_vi``,
  ``_weekday_mismatches``) cho kết quả đúng với mọi đầu vào biên.
- Bảng dữ kiện ``_facts()`` không bao giờ tự mâu thuẫn — đây là nguyên nhân gốc
  của lỗi "mô hình bịa" (§7.2): bảng dữ kiện mâu thuẫn thì mô hình hoà giải
  mâu thuẫn bằng cách bịa.
- ``ask_sql()`` dọn markdown và từ chối SQL không phải SELECT/WITH.
- ``parse_leave_request()`` chuẩn hoá mọi biến thể đầu ra của mô hình.
- ``health()`` trả đúng schema trong mọi trạng thái.
- Prompt được xây với đúng tham số (temperature, num_predict) — regression test.

Mỗi nhóm test đặt trong class riêng để ``pytest -k ClassName`` chạy từng nhóm.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import llm


# ══════════════════════════════════════════════════════════════════════════
# _strip_thinking
# ══════════════════════════════════════════════════════════════════════════
class TestStripThinking:
    def test_removes_single_think_block(self):
        text = "<think>nội tâm</think>Câu trả lời."
        assert llm._strip_thinking(text) == "Câu trả lời."

    def test_removes_multiline_think_block(self):
        text = "<think>\ndòng 1\ndòng 2\n</think>\nKết quả."
        assert llm._strip_thinking(text) == "Kết quả."

    def test_removes_multiple_think_blocks(self):
        text = "<think>a</think>Trước <think>b</think>Sau"
        assert llm._strip_thinking(text) == "Trước Sau"

    def test_no_think_block_returns_original(self):
        text = "Không có gì đặc biệt."
        assert llm._strip_thinking(text) == text

    def test_empty_think_block(self):
        text = "<think></think>OK"
        assert llm._strip_thinking(text) == "OK"

    def test_only_think_block_returns_empty(self):
        assert llm._strip_thinking("<think>chỉ có suy nghĩ</think>") == ""

    def test_preserves_surrounding_whitespace_after_strip(self):
        text = "  <think>x</think>  Đáp án  "
        assert llm._strip_thinking(text) == "Đáp án"


# ══════════════════════════════════════════════════════════════════════════
# _day — chuyển ISO sang dd/MM
# ══════════════════════════════════════════════════════════════════════════
class TestDayConversion:
    def test_standard_iso_date(self):
        assert llm._day("2026-07-30") == "30/07"

    def test_january_date(self):
        assert llm._day("2026-01-05") == "05/01"

    def test_none_input(self):
        assert llm._day(None) == "None"

    def test_short_string(self):
        assert llm._day("abc") == "abc"

    def test_empty_string(self):
        assert llm._day("") == ""

    def test_full_iso_datetime(self):
        # Chỉ cắt 10 ký tự đầu, phần sau bị bỏ qua
        assert llm._day("2026-12-25T10:00:00") == "25/12"


# ══════════════════════════════════════════════════════════════════════════
# is_enabled / _cfg
# ══════════════════════════════════════════════════════════════════════════
class TestConfigHelpers:
    def test_enabled_when_true(self):
        assert llm.is_enabled({"llm": {"enabled": True}}) is True

    def test_disabled_when_false(self):
        assert llm.is_enabled({"llm": {"enabled": False}}) is False

    def test_disabled_when_key_missing(self):
        assert llm.is_enabled({}) is False

    def test_disabled_when_llm_key_empty(self):
        assert llm.is_enabled({"llm": {}}) is False

    def test_cfg_returns_value(self):
        assert llm._cfg({"llm": {"model": "gemma3:4b"}}, "model", "default") == "gemma3:4b"

    def test_cfg_returns_default_when_missing(self):
        assert llm._cfg({}, "model", "qwen3:8b") == "qwen3:8b"

    def test_cfg_returns_default_when_llm_key_empty(self):
        assert llm._cfg({"llm": {}}, "timeout_sec", 60) == 60


# ══════════════════════════════════════════════════════════════════════════
# _facts — bảng dữ kiện đưa cho mô hình
#
# Bảng dữ kiện nhất quán là điều kiện tiên quyết để mô hình không bịa.
# ══════════════════════════════════════════════════════════════════════════
class TestFacts:
    """Test tính nhất quán nội bộ của bảng dữ kiện."""

    @staticmethod
    def _base_trace(**overrides: Any) -> dict[str, Any]:
        trace: dict[str, Any] = {
            "level": "ok",
            "as_of": "2026-07-30",
            "counts": {"absent": 0, "late": 0, "sessions_considered": 5},
            "signals": [],
            "history": [],
        }
        trace.update(overrides)
        return trace

    def test_empty_history(self):
        facts = llm._facts(self._base_trace(history=[]), late_after_min=10)
        assert "0 buổi vắng" in facts or "Số buổi vắng: 0" in facts

    def test_all_present_on_time(self):
        history = [
            {"date": f"2026-07-{24 + i}", "status": "present", "late_min": 0}
            for i in range(5)
        ]
        trace = self._base_trace(
            history=history,
            counts={"absent": 0, "late": 0, "sessions_considered": 5},
        )
        facts = llm._facts(trace, late_after_min=10)
        assert "đúng giờ" in facts
        assert "Số buổi vắng: 0" in facts

    def test_sub_threshold_lateness_marked_as_not_counted(self):
        """Trễ dưới ngưỡng phải nói rõ 'không tính là đi muộn'."""
        trace = self._base_trace(
            history=[
                {"date": "2026-07-28", "status": "present", "late_min": 8},
                {"date": "2026-07-29", "status": "present", "late_min": 0},
            ],
            counts={"absent": 0, "late": 0, "sessions_considered": 2},
        )
        facts = llm._facts(trace, late_after_min=10)
        assert "dưới ngưỡng nên không tính là đi muộn" in facts
        assert "từ 10 phút trở lên" in facts

    def test_late_above_threshold_shows_minutes(self):
        trace = self._base_trace(
            history=[
                {"date": "2026-07-28", "status": "late", "late_min": 15},
            ],
            counts={"absent": 0, "late": 1, "sessions_considered": 1},
        )
        facts = llm._facts(trace, late_after_min=10)
        assert "đi muộn 15 phút" in facts

    def test_absent_count_consistency(self):
        """Số buổi vắng trong counts phải khớp với history."""
        trace = self._base_trace(
            history=[
                {"date": "2026-07-24", "status": "absent", "late_min": None},
                {"date": "2026-07-25", "status": "present", "late_min": 0},
                {"date": "2026-07-28", "status": "absent", "late_min": None},
            ],
            counts={"absent": 2, "late": 0, "sessions_considered": 3},
        )
        facts = llm._facts(trace, late_after_min=10)
        assert "Số buổi vắng: 2" in facts

    def test_streak_equals_total_shows_lien_nhau(self):
        """Vắng 3 buổi, streak 3 → 'LIỀN NHAU'."""
        trace = self._base_trace(
            absence_streak=3,
            counts={"absent": 3, "late": 0, "sessions_considered": 5},
        )
        facts = llm._facts(trace, late_after_min=10)
        assert "LIỀN NHAU" in facts

    def test_streak_less_than_total_shows_not_all_consecutive(self):
        """Vắng 3 buổi, streak 2 → 'KHÔNG liền nhau hết'."""
        trace = self._base_trace(
            absence_streak=2,
            counts={"absent": 3, "late": 0, "sessions_considered": 5},
        )
        facts = llm._facts(trace, late_after_min=10)
        assert "KHÔNG liền nhau hết" in facts

    def test_streak_zero_shows_rai_rac(self):
        """Vắng 2 buổi, streak 0 → 'RẢI RÁC'."""
        trace = self._base_trace(
            absence_streak=0,
            counts={"absent": 2, "late": 0, "sessions_considered": 5},
        )
        facts = llm._facts(trace, late_after_min=10)
        assert "RẢI RÁC" in facts

    def test_single_absence_with_streak(self):
        """Vắng 1 buổi, streak 1 → dòng đơn."""
        trace = self._base_trace(
            absence_streak=1,
            counts={"absent": 1, "late": 0, "sessions_considered": 5},
        )
        facts = llm._facts(trace, late_after_min=10)
        assert "Vắng liên tiếp tính đến buổi cuối: 1 buổi" in facts
        # Không nên có "LIỀN NHAU" hay "RẢI RÁC" cho 1 buổi
        assert "LIỀN NHAU" not in facts
        assert "RẢI RÁC" not in facts

    def test_increasing_lateness_streak_with_minutes(self):
        """Chuỗi trễ tăng dần >= 2 → liệt kê từng con số."""
        trace = self._base_trace(
            increasing_lateness_streak=3,
            history=[
                {"date": "2026-07-24", "status": "late", "late_min": 5, "source": "web"},
                {"date": "2026-07-25", "status": "late", "late_min": 10, "source": "web"},
                {"date": "2026-07-28", "status": "late", "late_min": 15, "source": "web"},
            ],
            counts={"absent": 0, "late": 3, "sessions_considered": 3},
        )
        facts = llm._facts(trace, late_after_min=10)
        assert "tăng dần" in facts
        assert "3 buổi liên tiếp" in facts
        assert "trễ 5 phút ngày 24/07" in facts
        assert "trễ 10 phút ngày 25/07" in facts
        assert "trễ 15 phút ngày 28/07" in facts
        assert "KHÔNG được cộng" in facts

    def test_increasing_lateness_streak_of_1_no_minute_list(self):
        """Chuỗi dài 1 buổi → không liệt kê danh sách phút."""
        trace = self._base_trace(
            increasing_lateness_streak=1,
            history=[
                {"date": "2026-07-28", "status": "late", "late_min": 12, "source": "web"},
            ],
            counts={"absent": 0, "late": 1, "sessions_considered": 1},
        )
        facts = llm._facts(trace, late_after_min=10)
        assert "1 buổi liên tiếp" in facts
        # Danh sách phút trễ chỉ xuất hiện khi streak >= 2
        assert "KHÔNG được cộng" not in facts

    def test_manual_source_excludes_late_minutes_from_list(self):
        """Bản ghi tay không đưa vào danh sách phút trễ."""
        trace = self._base_trace(
            increasing_lateness_streak=2,
            history=[
                {"date": "2026-07-24", "status": "late", "late_min": 5, "source": "web"},
                {"date": "2026-07-25", "status": "present", "late_min": 922, "source": "manual"},
                {"date": "2026-07-28", "status": "late", "late_min": 15, "source": "web"},
            ],
            counts={"absent": 0, "late": 2, "sessions_considered": 3},
        )
        facts = llm._facts(trace, late_after_min=10)
        # 922 phút (giờ Labcoach bấm) không được xuất hiện
        assert "922" not in facts

    def test_manual_source_history_note(self):
        """Bản ghi tay trong lịch sử phải ghi rõ 'thủ công'."""
        trace = self._base_trace(
            history=[
                {"date": "2026-07-28", "status": "present", "late_min": 500, "source": "manual"},
            ],
            counts={"absent": 0, "late": 0, "sessions_considered": 1},
        )
        facts = llm._facts(trace, late_after_min=10)
        assert "thủ công" in facts
        # Không được nói trễ 500 phút
        assert "500 phút" not in facts

    def test_early_departure_flags(self):
        trace = self._base_trace(early_departure_flags=3)
        facts = llm._facts(trace, late_after_min=10)
        assert "3" in facts
        assert "lượt điểm danh thứ hai" in facts

    def test_signals_with_tier_filtering(self):
        """Chỉ hiện tín hiệu quyết định (cùng tier với level)."""
        trace = self._base_trace(
            level="at_risk",
            signals=[
                {"code": "ABSENT_GTE", "value": 3, "threshold": 3,
                 "note": "Vắng 3 buổi trong 5 buổi gần nhất", "tier": "at_risk"},
                {"code": "ABSENT_WATCH", "value": 3, "threshold": 2,
                 "note": "Vắng 3 buổi", "tier": "watch"},
            ],
            counts={"absent": 3, "late": 0, "sessions_considered": 5},
        )
        facts = llm._facts(trace, late_after_min=10)
        # Tín hiệu at_risk phải có
        assert "Vắng 3 buổi trong 5 buổi gần nhất" in facts

    def test_no_raw_rule_codes_in_facts(self):
        """Bảng dữ kiện không bao giờ chứa mã rule tiếng Anh."""
        trace = self._base_trace(
            level="at_risk",
            early_departure_flags=2,
            signals=[
                {"code": "EARLY_DEPARTURE_REPEATED", "value": 2, "threshold": 2,
                 "note": "Vắng ở lượt điểm danh thứ hai 2 lần", "tier": "at_risk"},
            ],
            counts={"absent": 1, "late": 0, "sessions_considered": 5},
            history=[],
        )
        facts = llm._facts(trace, late_after_min=10)
        for code in ("EARLY_DEPARTURE", "DEVICE_REUSE", "IP_RATE_SPIKE",
                      "TOKEN_GRACE_USED", "DEVICE_MISMATCH", "FINGERPRINT_MATCH"):
            assert code not in facts, f"mã rule {code} lọt vào bảng dữ kiện"

    def test_level_vi_translation(self):
        """Mức rủi ro phải hiện bằng tiếng Việt."""
        for level, vi in [("ok", "ổn"), ("watch", "cần theo dõi"), ("at_risk", "nguy cơ rời lớp")]:
            trace = self._base_trace(level=level)
            facts = llm._facts(trace, late_after_min=10)
            assert vi in facts

    def test_history_order_old_to_new(self):
        """Lịch sử phải ghi 'cũ nhất trước'."""
        trace = self._base_trace(
            history=[
                {"date": "2026-07-24", "status": "present", "late_min": 0},
                {"date": "2026-07-25", "status": "absent", "late_min": None},
                {"date": "2026-07-28", "status": "present", "late_min": 0},
            ],
            counts={"absent": 1, "late": 0, "sessions_considered": 3},
        )
        facts = llm._facts(trace, late_after_min=10)
        assert "cũ nhất trước" in facts
        # 24/07 phải xuất hiện trước 28/07
        pos_24 = facts.index("24/07")
        pos_28 = facts.index("28/07")
        assert pos_24 < pos_28


# ══════════════════════════════════════════════════════════════════════════
# _date_table
# ══════════════════════════════════════════════════════════════════════════
class TestDateTable:
    def test_friday_date_table(self):
        table = llm._date_table("2026-07-31")  # thứ Sáu
        assert "mai = 2026-08-01" in table
        assert "ngày kia = 2026-08-02" in table
        assert "thứ 3 = thứ Ba kế tiếp = 2026-08-04" in table
        assert "thứ 5 = thứ Năm kế tiếp = 2026-08-06" in table

    def test_monday_date_table(self):
        table = llm._date_table("2026-07-27")  # thứ Hai
        assert "mai = 2026-07-28" in table
        assert "ngày kia = 2026-07-29" in table

    def test_table_not_too_long(self):
        """Bảng quá dài → model chép cả bảng vào câu trả lời."""
        for day in range(27, 34):
            date_str = f"2026-07-{day:02d}" if day <= 31 else f"2026-08-{day - 31:02d}"
            table = llm._date_table(date_str)
            assert table.count("\n") <= 12, f"bảng cho {date_str} quá dài"

    def test_table_contains_lookup_warning(self):
        """Phải dặn model chỉ dùng để tra cứu."""
        table = llm._date_table("2026-07-31")
        assert "TRA CỨU" in table
        assert "không chép" in table.lower() or "không chép" in table

    def test_all_seven_weekdays_present(self):
        """Bảng phải chứa đủ 7 ngày trong tuần kế tiếp."""
        table = llm._date_table("2026-07-31")
        for dow in llm._DOW_NUM_VI:
            assert dow in table, f"{dow} không có trong bảng"


# ══════════════════════════════════════════════════════════════════════════
# _weekday_vi
# ══════════════════════════════════════════════════════════════════════════
class TestWeekdayVi:
    def test_monday(self):
        assert llm._weekday_vi("2026-07-27") == "thứ Hai"

    def test_friday(self):
        assert llm._weekday_vi("2026-07-31") == "thứ Sáu"

    def test_sunday(self):
        assert llm._weekday_vi("2026-08-02") == "Chủ Nhật"


# ══════════════════════════════════════════════════════════════════════════
# _weekday_mismatches
# ══════════════════════════════════════════════════════════════════════════
class TestWeekdayMismatches:
    def test_mismatch_detected(self):
        """Đơn nhắc thứ 3, ngày trả về là thứ Hai → cảnh báo."""
        # 2026-08-03 là thứ Hai
        warnings = llm._weekday_mismatches("em xin nghỉ thứ 3", ["2026-08-03"])
        assert len(warnings) == 1
        assert "thứ 2" in warnings[0]  # thứ Hai = thứ 2

    def test_no_mismatch(self):
        """Đơn nhắc thứ 2, ngày đúng là thứ Hai → không cảnh báo."""
        # 2026-08-03 là thứ Hai
        warnings = llm._weekday_mismatches("em xin nghỉ thứ 2 tuần tới", ["2026-08-03"])
        assert warnings == []

    def test_no_weekday_in_text(self):
        """Đơn không nhắc thứ → không có gì để kiểm."""
        warnings = llm._weekday_mismatches("mai em xin nghỉ ạ", ["2026-08-01"])
        assert warnings == []

    def test_multiple_mismatches(self):
        """Nhắc thứ 3 và thứ 5 nhưng ngày trả về lệch cả hai."""
        # 2026-08-03=thứ Hai, 2026-08-05=thứ Tư
        warnings = llm._weekday_mismatches(
            "em xin nghỉ thứ 3 với thứ 5", ["2026-08-03", "2026-08-05"]
        )
        assert len(warnings) == 2

    def test_text_with_vietnamese_name_style(self):
        """Đơn viết 'thứ Ba' bằng chữ thay vì 'thứ 3'."""
        # 2026-08-04 là thứ Ba
        warnings = llm._weekday_mismatches("em xin nghỉ thứ Ba tuần sau", ["2026-08-04"])
        assert warnings == []

    def test_invalid_date_skipped(self):
        """Ngày không hợp lệ → bỏ qua, không nổ."""
        warnings = llm._weekday_mismatches("em xin nghỉ thứ 3", ["not-a-date"])
        assert warnings == []

    def test_chủ_nhật_detection(self):
        """'chủ nhật' trong text, ngày đúng là Chủ Nhật."""
        # 2026-08-02 là Chủ Nhật
        warnings = llm._weekday_mismatches("em xin nghỉ chủ nhật", ["2026-08-02"])
        assert warnings == []


# ══════════════════════════════════════════════════════════════════════════
# ask_sql — post-processing
# ══════════════════════════════════════════════════════════════════════════
class TestAskSqlPostProcessing:
    """Test dọn đầu ra của ask_sql mà không gọi Ollama."""

    def test_strips_markdown_fenced_sql(self, monkeypatch):
        cfg = {"llm": {"enabled": True}}
        monkeypatch.setattr(
            llm, "_generate",
            lambda *a, **k: "```sql\nSELECT name FROM students LIMIT 5\n```",
        )
        result = llm.ask_sql("ai đang học", cfg)
        assert result == "SELECT name FROM students LIMIT 5"

    def test_strips_markdown_fenced_no_lang(self, monkeypatch):
        cfg = {"llm": {"enabled": True}}
        monkeypatch.setattr(
            llm, "_generate",
            lambda *a, **k: "```\nSELECT 1\n```",
        )
        result = llm.ask_sql("test", cfg)
        assert result == "SELECT 1"

    def test_returns_none_when_empty(self, monkeypatch):
        cfg = {"llm": {"enabled": True}}
        monkeypatch.setattr(llm, "_generate", lambda *a, **k: "```sql\n\n```")
        assert llm.ask_sql("test", cfg) is None

    def test_returns_none_when_model_silent(self, monkeypatch):
        cfg = {"llm": {"enabled": True}}
        monkeypatch.setattr(llm, "_generate", lambda *a, **k: None)
        assert llm.ask_sql("test", cfg) is None

    def test_plain_sql_passes_through(self, monkeypatch):
        cfg = {"llm": {"enabled": True}}
        monkeypatch.setattr(
            llm, "_generate",
            lambda *a, **k: "SELECT COUNT(*) FROM attendance LIMIT 10",
        )
        result = llm.ask_sql("bao nhiêu bản ghi", cfg)
        assert result == "SELECT COUNT(*) FROM attendance LIMIT 10"

    def test_sql_with_leading_trailing_whitespace(self, monkeypatch):
        cfg = {"llm": {"enabled": True}}
        monkeypatch.setattr(
            llm, "_generate",
            lambda *a, **k: "  \n SELECT 1 LIMIT 1 \n  ",
        )
        result = llm.ask_sql("test", cfg)
        assert result == "SELECT 1 LIMIT 1"


# ══════════════════════════════════════════════════════════════════════════
# parse_leave_request — chuẩn hoá đầu ra
# ══════════════════════════════════════════════════════════════════════════
class TestParseLeaveNormalization:
    CFG = {"llm": {"enabled": True}}

    def test_category_unknown_becomes_khac(self, monkeypatch):
        monkeypatch.setattr(
            llm, "_generate",
            lambda *a, **k: json.dumps({
                "student_id": "K4001", "dates": ["2026-08-03"],
                "category": "tự nghĩ ra", "reason_text": "ốm"
            }),
        )
        out = llm.parse_leave_request("...", self.CFG, today="2026-08-01")
        assert out["category"] == "khác"

    def test_valid_categories_preserved(self, monkeypatch):
        for cat in llm.LEAVE_CATEGORIES:
            monkeypatch.setattr(
                llm, "_generate",
                lambda *a, cat=cat, **k: json.dumps({
                    "dates": ["2026-08-03"], "category": cat, "reason_text": "test"
                }),
            )
            out = llm.parse_leave_request("...", self.CFG, today="2026-08-01")
            assert out["category"] == cat

    def test_dates_string_becomes_list(self, monkeypatch):
        monkeypatch.setattr(
            llm, "_generate",
            lambda *a, **k: '{"dates":"2026-08-03","category":"ốm","reason_text":"ốm"}',
        )
        out = llm.parse_leave_request("...", self.CFG, today="2026-08-01")
        assert out["dates"] == ["2026-08-03"]

    def test_invalid_dates_dropped(self, monkeypatch):
        monkeypatch.setattr(
            llm, "_generate",
            lambda *a, **k: json.dumps({
                "dates": ["mai", "2026-08-03", "thứ ba", "99-99-99"],
                "category": "ốm", "reason_text": "ốm"
            }),
        )
        out = llm.parse_leave_request("...", self.CFG, today="2026-08-01")
        assert out["dates"] == ["2026-08-03"]

    def test_missing_recalculated_by_code(self, monkeypatch):
        """missing phải do code tính, không dùng giá trị model trả."""
        monkeypatch.setattr(
            llm, "_generate",
            lambda *a, **k: json.dumps({
                "student_id": "K4001", "student_name": None,
                "dates": ["2026-08-03"], "category": "ốm",
                "reason_text": "sốt", "missing": ["hoàn toàn sai"]
            }),
        )
        out = llm.parse_leave_request("...", self.CFG, today="2026-08-01")
        assert "student_name" in out["missing"]
        assert "hoàn toàn sai" not in out["missing"]
        assert "student_id" not in out["missing"]  # có student_id rồi

    def test_all_fields_missing(self, monkeypatch):
        monkeypatch.setattr(
            llm, "_generate",
            lambda *a, **k: json.dumps({
                "student_id": None, "student_name": None,
                "dates": [], "category": "ốm", "reason_text": None
            }),
        )
        out = llm.parse_leave_request("...", self.CFG, today="2026-08-01")
        assert set(out["missing"]) == {"student_id", "student_name", "dates", "reason_text"}

    def test_returns_none_for_non_dict_json(self, monkeypatch):
        monkeypatch.setattr(llm, "_generate", lambda *a, **k: "[1, 2, 3]")
        assert llm.parse_leave_request("...", self.CFG, today="2026-08-01") is None

    def test_returns_none_for_invalid_json(self, monkeypatch):
        monkeypatch.setattr(llm, "_generate", lambda *a, **k: "Đây không phải JSON")
        assert llm.parse_leave_request("...", self.CFG, today="2026-08-01") is None

    def test_returns_none_when_model_silent(self, monkeypatch):
        monkeypatch.setattr(llm, "_generate", lambda *a, **k: None)
        assert llm.parse_leave_request("...", self.CFG, today="2026-08-01") is None

    def test_date_warnings_attached(self, monkeypatch):
        """date_warnings phải luôn có mặt trong output."""
        monkeypatch.setattr(
            llm, "_generate",
            lambda *a, **k: json.dumps({
                "dates": ["2026-08-03"], "category": "ốm", "reason_text": "ốm"
            }),
        )
        out = llm.parse_leave_request("mai em xin nghỉ", self.CFG, today="2026-08-01")
        assert "date_warnings" in out
        assert isinstance(out["date_warnings"], list)

    def test_dates_none_handled(self, monkeypatch):
        """dates là null → chuyển thành list rỗng."""
        monkeypatch.setattr(
            llm, "_generate",
            lambda *a, **k: '{"dates":null,"category":"ốm","reason_text":"ốm"}',
        )
        out = llm.parse_leave_request("...", self.CFG, today="2026-08-01")
        assert out["dates"] == []

    def test_known_student_ids_in_prompt(self, monkeypatch):
        """Khi có danh sách mã học viên, nó phải xuất hiện trong prompt."""
        captured = {}

        def fake_generate(prompt, *a, **k):
            captured["prompt"] = prompt
            return json.dumps({"dates": ["2026-08-03"], "category": "ốm", "reason_text": "ốm"})

        monkeypatch.setattr(llm, "_generate", fake_generate)
        llm.parse_leave_request(
            "em xin nghỉ", self.CFG, today="2026-08-01",
            known_student_ids=["K4001", "K4002"],
        )
        assert "K4001" in captured["prompt"]
        assert "K4002" in captured["prompt"]


# ══════════════════════════════════════════════════════════════════════════
# health
# ══════════════════════════════════════════════════════════════════════════
class TestHealth:
    def test_disabled(self):
        result = llm.health({"llm": {"enabled": False}})
        assert result == {"enabled": False, "reachable": False, "model_ready": False, "model": None}

    def test_disabled_when_no_llm_key(self):
        result = llm.health({})
        assert result["enabled"] is False

    def test_unreachable(self, monkeypatch):
        """Ollama không chạy → reachable=False."""
        cfg = {"llm": {"enabled": True, "base_url": "http://127.0.0.1:99999", "model": "test:1b"}}
        # urlopen sẽ thất bại vì port không hợp lệ
        import urllib.error
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("refused")),
        )
        result = llm.health(cfg)
        assert result["enabled"] is True
        assert result["reachable"] is False
        assert result["model_ready"] is False

    def test_reachable_model_ready(self, monkeypatch):
        """Ollama chạy, model đã tải."""
        cfg = {"llm": {"enabled": True, "model": "gemma3:4b"}}

        class FakeResponse:
            def read(self):
                return json.dumps({"models": [{"name": "gemma3:4b"}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResponse())
        result = llm.health(cfg)
        assert result == {
            "enabled": True, "reachable": True, "model_ready": True, "model": "gemma3:4b"
        }

    def test_reachable_model_not_loaded(self, monkeypatch):
        """Ollama chạy nhưng model chưa pull."""
        cfg = {"llm": {"enabled": True, "model": "llama3:8b"}}

        class FakeResponse:
            def read(self):
                return json.dumps({"models": [{"name": "gemma3:4b"}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResponse())
        result = llm.health(cfg)
        assert result["reachable"] is True
        assert result["model_ready"] is False

    def test_model_latest_suffix_matched(self, monkeypatch):
        """Ollama liệt kê 'model:latest', config ghi 'model' → vẫn ready."""
        cfg = {"llm": {"enabled": True, "model": "qwen3:8b"}}

        class FakeResponse:
            def read(self):
                return json.dumps({"models": [{"name": "qwen3:8b:latest"}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResponse())
        result = llm.health(cfg)
        assert result["model_ready"] is True


# ══════════════════════════════════════════════════════════════════════════
# Prompt construction — regression tests
#
# Kiểm tra rằng mỗi entrypoint gọi _generate với đúng tham số, đặc biệt
# temperature. Sai temperature = sai hẳn tính chất đầu ra.
# ══════════════════════════════════════════════════════════════════════════
class TestPromptConstruction:
    @staticmethod
    def _capture_generate(monkeypatch) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        def fake_generate(prompt, cfg, *, system=llm._GROUNDING, temperature=0.2,
                          num_predict=320, fmt=None):
            captured.update(
                prompt=prompt, temperature=temperature,
                num_predict=num_predict, fmt=fmt, system=system,
            )
            return None

        monkeypatch.setattr(llm, "_generate", fake_generate)
        return captured

    def test_write_diagnosis_temperature_zero(self, monkeypatch):
        captured = self._capture_generate(monkeypatch)
        cfg = {"llm": {"enabled": True}, "checkin": {"late_after_min": 10}}
        trace = {"level": "ok", "counts": {"absent": 0, "late": 0, "sessions_considered": 5},
                 "as_of": "2026-07-30", "signals": [], "history": []}
        llm.write_diagnosis(trace, cfg)
        assert captured["temperature"] == 0.0
        assert captured["num_predict"] == 200

    def test_draft_message_temperature(self, monkeypatch):
        captured = self._capture_generate(monkeypatch)
        cfg = {"llm": {"enabled": True}, "checkin": {"late_after_min": 10}}
        trace = {"level": "watch", "counts": {"absent": 2, "late": 0, "sessions_considered": 5},
                 "as_of": "2026-07-30", "signals": [], "history": []}
        llm.draft_message(trace, "Nguyễn Văn A", cfg)
        assert captured["temperature"] == 0.25
        assert captured["num_predict"] == 400

    def test_draft_message_contains_student_name(self, monkeypatch):
        captured = self._capture_generate(monkeypatch)
        cfg = {"llm": {"enabled": True}, "checkin": {"late_after_min": 10}}
        trace = {"level": "ok", "counts": {"absent": 0, "late": 0, "sessions_considered": 5},
                 "as_of": "2026-07-30", "signals": [], "history": []}
        llm.draft_message(trace, "Trần Thị B", cfg)
        assert "Trần Thị B" in captured["prompt"]

    def test_ask_sql_temperature_zero(self, monkeypatch):
        captured = self._capture_generate(monkeypatch)
        cfg = {"llm": {"enabled": True}}
        llm.ask_sql("ai vắng nhiều nhất", cfg)
        assert captured["temperature"] == 0.0
        assert captured["num_predict"] == 300

    def test_ask_sql_contains_question(self, monkeypatch):
        captured = self._capture_generate(monkeypatch)
        cfg = {"llm": {"enabled": True}}
        llm.ask_sql("ai đi muộn nhiều nhất trong tháng 7", cfg)
        assert "ai đi muộn nhiều nhất trong tháng 7" in captured["prompt"]

    def test_ask_sql_contains_schema_and_examples(self, monkeypatch):
        captured = self._capture_generate(monkeypatch)
        cfg = {"llm": {"enabled": True}}
        llm.ask_sql("test", cfg)
        assert llm.SQL_SCHEMA_HINT in captured["prompt"]
        assert "VÍ DỤ 1" in captured["prompt"]
        assert "NOT EXISTS" in captured["prompt"]

    def test_parse_leave_temperature_zero(self, monkeypatch):
        captured = self._capture_generate(monkeypatch)
        cfg = {"llm": {"enabled": True}}
        llm.parse_leave_request("em xin nghỉ mai", cfg, today="2026-07-31")
        assert captured["temperature"] == 0.0
        assert captured["fmt"] == "json"

    def test_write_diagnosis_prompt_has_grounding(self, monkeypatch):
        captured = self._capture_generate(monkeypatch)
        cfg = {"llm": {"enabled": True}, "checkin": {"late_after_min": 10}}
        trace = {"level": "ok", "counts": {"absent": 0, "late": 0, "sessions_considered": 5},
                 "as_of": "2026-07-30", "signals": [], "history": []}
        llm.write_diagnosis(trace, cfg)
        assert captured["system"] == llm._GROUNDING
