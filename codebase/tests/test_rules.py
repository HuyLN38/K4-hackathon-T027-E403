"""Kiểm thử phần xếp mức rủi ro (spec §4.7 + §7.2).

Chỉ tiêu của §7.2 cho hạng mục này là **100%**: phân loại rủi ro là deterministic,
sai một ca là bug code chứ không phải sai số của mô hình. Vì vậy các ca biên (chỉ
lệch một buổi vắng, một buổi muộn) được test riêng - đó là chỗ ngưỡng dễ lệch nhất.
"""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta

import pytest
import rules
from conftest import create_session
from db import load_config, now_ms
from rules import session_start_ms

CFG = load_config()
AS_OF = "2026-08-01"
FIRST_DAY = date(2026, 7, 20)


def build_history(conn, student_id: str, pattern: list[tuple[str, int]]) -> list[int]:
    """Dựng N buổi đã đóng với hành vi cho trước của một học viên.

    `pattern` theo thứ tự thời gian: ('present'|'late'|'absent', số_phút_trễ).
    Buổi học dùng chung giữa các học viên - gọi nhiều lần với cùng dải ngày thì
    tái sử dụng buổi đã có, giống lớp thật (một buổi, nhiều người).
    """
    session_ids = []
    for offset, (status, late_min) in enumerate(pattern):
        day = (FIRST_DAY + timedelta(days=offset)).isoformat()
        existing = conn.execute(
            "SELECT session_id FROM sessions WHERE date = ? AND start_time = '09:00'", (day,)
        ).fetchone()
        session_id = (
            existing["session_id"]
            if existing
            else create_session(conn, day, start_time="09:00", late_after_min=10)
        )
        start_ms = session_start_ms(day, "09:00")

        if status != "absent":
            conn.execute(
                """INSERT INTO attendance
                   (student_id, session_id, checkin_ts_ms, call_index, ip, device_hash,
                    token_valid, token_id, status, source)
                   VALUES (?,?,?,1,'192.168.1.9','dev-hash',1,NULL,?,'web')""",
                (student_id, session_id, start_ms + late_min * 60_000, status),
            )
        conn.execute(
            """UPDATE sessions SET state='closed', opened_at=?, closed_at=?, second_call_ts=?
               WHERE session_id=?""",
            (start_ms, start_ms + 7_200_000, start_ms + 3_600_000, session_id),
        )
        session_ids.append(session_id)
    conn.commit()
    return session_ids


def level_of(conn, student_id: str, cfg=None) -> str:
    return rules.compute_risk(conn, student_id, cfg or CFG, AS_OF).level


# ==========================================================================
# Mức ok
# ==========================================================================
def test_full_attendance_is_ok(seeded):
    build_history(seeded, "K4001", [("present", 0)] * 5)
    assert level_of(seeded, "K4001") == "ok"


def test_one_absence_is_still_ok(seeded):
    build_history(seeded, "K4001", [("present", 0)] * 4 + [("absent", 0)])
    assert level_of(seeded, "K4001") == "ok"


def test_two_late_sessions_is_still_ok(seeded):
    """Ngưỡng watch là muộn >=3 buổi. Hai buổi chưa tới ngưỡng."""
    build_history(seeded, "K4001", [("late", 15), ("late", 15), ("present", 0), ("present", 0), ("present", 0)])
    assert level_of(seeded, "K4001") == "ok"


# ==========================================================================
# Mức watch
# ==========================================================================
def test_exactly_two_absences_is_watch(seeded):
    build_history(seeded, "K4001", [("absent", 0), ("present", 0), ("absent", 0), ("present", 0), ("present", 0)])
    result = rules.compute_risk(seeded, "K4001", CFG, AS_OF)
    assert result.level == "watch"
    assert any(s["code"] == "ABSENT_WATCH" for s in result.trace["signals"])


def test_three_late_sessions_is_watch(seeded):
    build_history(seeded, "K4001", [("late", 15), ("late", 20), ("late", 12), ("present", 0), ("present", 0)])
    result = rules.compute_risk(seeded, "K4001", CFG, AS_OF)
    assert result.level == "watch"
    assert any(s["code"] == "LATE_SESSIONS" for s in result.trace["signals"])


def test_increasing_lateness_three_in_a_row_is_watch(seeded):
    """Trễ tăng dần là tín hiệu riêng, khác với chỉ đếm số buổi muộn."""
    build_history(seeded, "K4001", [("present", 0), ("present", 4), ("late", 11), ("late", 19), ("present", 0)])
    result = rules.compute_risk(seeded, "K4001", CFG, AS_OF)
    assert result.level == "watch"
    assert any(s["code"] == "INCREASING_LATENESS" for s in result.trace["signals"])


def test_increasing_lateness_only_two_in_a_row_is_not_watch(seeded):
    """Trễ 0' -> 5' rồi về đúng giờ: chuỗi ngắn, chưa tới ngưỡng."""
    build_history(seeded, "K4001", [("present", 0), ("present", 5), ("present", 0), ("present", 0), ("present", 0)])
    result = rules.compute_risk(seeded, "K4001", CFG, AS_OF)
    assert result.trace["increasing_lateness_streak"] < CFG["risk"]["watch"]["increasing_lateness_streak"]
    assert result.level == "ok"


def test_small_lateness_drift_is_not_a_signal(seeded):
    """1' -> 3' -> 7' là dao động bình thường, không phải người đang rời lớp.

    Chuỗi tăng dần chỉ tính khi kết thúc ở mức muộn thật. Không có sàn này thì
    trên lớp 40 người có 11 người bị xếp watch oan.
    """
    build_history(seeded, "K4001", [("present", 1), ("present", 3), ("present", 7), ("present", 0), ("present", 0)])
    result = rules.compute_risk(seeded, "K4001", CFG, AS_OF)
    assert result.trace["increasing_lateness_streak"] == 0
    assert result.level == "ok"


def test_absence_breaks_the_increasing_lateness_streak(seeded):
    """Vắng không phải là "trễ hơn" - để chuỗi đi qua buổi vắng thì tín hiệu vô nghĩa."""
    build_history(seeded, "K4001", [("present", 3), ("present", 6), ("absent", 0), ("present", 9), ("present", 0)])
    result = rules.compute_risk(seeded, "K4001", CFG, AS_OF)
    assert result.trace["increasing_lateness_streak"] < 3


# ==========================================================================
# Mức at_risk
# ==========================================================================
def test_three_absences_is_at_risk(seeded):
    build_history(seeded, "K4001", [("absent", 0), ("present", 0), ("absent", 0), ("present", 0), ("absent", 0)])
    result = rules.compute_risk(seeded, "K4001", CFG, AS_OF)
    assert result.level == "at_risk"
    assert any(s["code"] == "ABSENT_GTE" for s in result.trace["signals"])


def test_golden_case_g07_increasing_lateness_then_silence(seeded):
    """Ca G07 trong spec §7.1.

    buổi 11 muộn 6' · buổi 12 muộn 14' · buổi 13 muộn 21' · buổi 14 vắng · buổi 15 vắng
    -> at_risk, và chẩn đoán phải nêu được cả hai tín hiệu.
    """
    build_history(seeded, "K4001", [("present", 6), ("late", 14), ("late", 21), ("absent", 0), ("absent", 0)])
    result = rules.compute_risk(seeded, "K4001", CFG, AS_OF)

    assert result.level == "at_risk"
    codes = {s["code"] for s in result.trace["signals"]}
    assert "SILENT_AFTER_LATENESS" in codes
    assert "INCREASING_LATENESS" in codes
    assert result.trace["absence_streak"] == 2
    assert result.trace["increasing_lateness_streak"] == 3


def test_silence_without_prior_lateness_is_not_at_risk_by_that_rule(seeded):
    """Hai buổi vắng liên tiếp nhưng trước đó không đi muộn -> chỉ là watch (vắng 2)."""
    build_history(seeded, "K4001", [("present", 0), ("present", 0), ("present", 0), ("absent", 0), ("absent", 0)])
    result = rules.compute_risk(seeded, "K4001", CFG, AS_OF)
    codes = {s["code"] for s in result.trace["signals"]}
    assert "SILENT_AFTER_LATENESS" not in codes
    assert result.level == "watch"


def test_repeated_early_departure_flags_make_at_risk(seeded):
    sessions = build_history(seeded, "K4001", [("present", 0)] * 5)
    for session_id in sessions[:2]:
        rules.raise_flag(seeded, None, session_id, "K4001", "EARLY_DEPARTURE", "test")
    seeded.commit()

    result = rules.compute_risk(seeded, "K4001", CFG, AS_OF)
    assert result.level == "at_risk"
    assert any(s["code"] == "EARLY_DEPARTURE_REPEATED" for s in result.trace["signals"])


def test_single_early_departure_flag_is_not_at_risk(seeded):
    sessions = build_history(seeded, "K4001", [("present", 0)] * 5)
    rules.raise_flag(seeded, None, sessions[0], "K4001", "EARLY_DEPARTURE", "test")
    seeded.commit()
    assert level_of(seeded, "K4001") == "watch"  # còn flag high chưa xử lý


def test_resolved_flags_stop_counting(seeded):
    """Flag đã được Labcoach xử lý thì không tính vào rủi ro nữa."""
    sessions = build_history(seeded, "K4001", [("present", 0)] * 5)
    for session_id in sessions[:2]:
        rules.raise_flag(seeded, None, session_id, "K4001", "EARLY_DEPARTURE", "test")
    seeded.execute("UPDATE anomaly_flags SET resolved = 1 WHERE student_id = 'K4001'")
    seeded.commit()
    assert level_of(seeded, "K4001") == "ok"


# ==========================================================================
# rule_trace - điều kiện để giải thích được (§6)
# ==========================================================================
def test_non_ok_level_always_has_at_least_one_signal(seeded):
    patterns = [
        [("absent", 0), ("absent", 0), ("present", 0), ("present", 0), ("present", 0)],
        [("late", 15), ("late", 15), ("late", 15), ("present", 0), ("present", 0)],
        [("absent", 0), ("absent", 0), ("absent", 0), ("present", 0), ("present", 0)],
        [("present", 6), ("late", 14), ("late", 21), ("absent", 0), ("absent", 0)],
    ]
    for i, pattern in enumerate(patterns):
        student = f"K400{i + 1}"
        build_history(seeded, student, pattern)
        result = rules.compute_risk(seeded, student, CFG, AS_OF)
        if result.level != "ok":
            assert result.trace["signals"], f"{student} thiếu tín hiệu giải thích"
            for signal in result.trace["signals"]:
                assert signal["note"], "tín hiệu phải có câu giải thích cho người đọc"
                assert "value" in signal and "threshold" in signal


def test_trace_is_json_serialisable_and_stored(seeded):
    build_history(seeded, "K4001", [("absent", 0), ("absent", 0), ("absent", 0), ("present", 0), ("present", 0)])
    top = rules.build_briefing(seeded, CFG, AS_OF, actor="test")
    assert top

    row = seeded.execute(
        "SELECT rule_trace, risk_level, llm_diagnosis, llm_message FROM risk_snapshots WHERE student_id='K4001'"
    ).fetchone()
    trace = json.loads(row["rule_trace"])
    assert trace["level"] == row["risk_level"]
    assert trace["history"]
    # tầng mô hình tắt -> hai cột này rỗng, và dashboard vẫn phải chạy được
    assert row["llm_diagnosis"] is None and row["llm_message"] is None


def test_history_window_respects_config(seeded):
    build_history(seeded, "K4001", [("absent", 0)] * 3 + [("present", 0)] * 5)
    result = rules.compute_risk(seeded, "K4001", CFG, AS_OF)
    assert result.trace["counts"]["sessions_considered"] == CFG["risk"]["window_sessions"]
    assert result.level == "ok"  # ba buổi vắng đã rơi ra khỏi cửa sổ


def test_thresholds_come_from_config_not_hardcoded(seeded):
    """Đổi ngưỡng trong config phải đổi kết quả - nếu không thì ngưỡng bị chôn trong code."""
    build_history(seeded, "K4001", [("absent", 0), ("absent", 0), ("present", 0), ("present", 0), ("present", 0)])
    assert level_of(seeded, "K4001") == "watch"

    strict = copy.deepcopy(CFG)
    strict["risk"]["at_risk"]["absent_gte"] = 2
    assert level_of(seeded, "K4001", strict) == "at_risk"

    lax = copy.deepcopy(CFG)
    lax["risk"]["watch"]["absent_gte"] = 99
    lax["risk"]["at_risk"]["absent_gte"] = 99
    assert level_of(seeded, "K4001", lax) == "ok"


# ==========================================================================
# Bản tin đầu ngày
# ==========================================================================
def test_briefing_is_capped_and_ordered(seeded):
    """Trần 5 ca là ràng buộc sản phẩm: danh sách dài thì không ai đọc (§1)."""
    for i in range(1, 6):
        build_history(seeded, f"K400{i}", [("absent", 0)] * 3 + [("present", 0)] * 2)

    top = rules.build_briefing(seeded, CFG, AS_OF, actor="test")
    assert len(top) <= CFG["risk"]["briefing_max_cases"]
    levels = [case.level for case in top]
    assert levels == sorted(levels, key=lambda l: {"at_risk": 0, "watch": 1}[l])
    assert all(case.level != "ok" for case in top)


def test_briefing_excludes_ok_students(seeded):
    build_history(seeded, "K4001", [("present", 0)] * 5)
    top = rules.build_briefing(seeded, CFG, AS_OF, actor="test")
    assert "K4001" not in [case.student_id for case in top]


def test_briefing_is_idempotent(seeded):
    build_history(seeded, "K4001", [("absent", 0)] * 3 + [("present", 0)] * 2)
    first = rules.build_briefing(seeded, CFG, AS_OF, actor="test")
    second = rules.build_briefing(seeded, CFG, AS_OF, actor="test")
    assert [c.student_id for c in first] == [c.student_id for c in second]
    count = seeded.execute(
        "SELECT COUNT(*) AS n FROM risk_snapshots WHERE date = ?", (AS_OF,)
    ).fetchone()["n"]
    assert count == 5  # một snapshot cho mỗi học viên, không nhân bản


# ==========================================================================
# Phân loại muộn
# ==========================================================================
@pytest.mark.parametrize(
    "minutes,expected",
    [(0, "present"), (5, "present"), (9, "present"), (10, "late"), (30, "late")],
)
def test_late_boundary(seeded, minutes, expected):
    day = "2026-07-20"
    session_id = create_session(seeded, day, start_time="09:00", late_after_min=10)
    row = seeded.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    ts = session_start_ms(day, "09:00") + minutes * 60_000
    assert rules.classify_status(row, ts, 10) == expected


def test_arriving_early_is_not_negative_lateness(seeded):
    day = "2026-07-20"
    session_id = create_session(seeded, day)
    row = seeded.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    ts = session_start_ms(day, "09:00") - 15 * 60_000
    assert rules.lateness_minutes(row, ts) == 0
