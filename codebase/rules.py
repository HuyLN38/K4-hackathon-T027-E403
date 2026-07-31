"""Rule engine: phát hiện bất thường (§4.6) và xếp mức rủi ro (§4.7).

Toàn bộ file này là deterministic. Không có lời gọi mô hình nào, và đó là điều
kiện để một bản ghi chuyên cần chịu được khiếu nại: mỗi giá trị `risk_level` đều
truy về được một rule cụ thể qua `rule_trace`.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from db import audit, now_ms

SEV_LOW, SEV_MED, SEV_HIGH = "low", "med", "high"

RULE_SEVERITY = {
    "DEVICE_REUSE": SEV_HIGH,
    "IP_RATE_SPIKE": SEV_MED,
    "DEVICE_MISMATCH": SEV_MED,
    "EARLY_DEPARTURE": SEV_HIGH,
    "TOKEN_GRACE_USED": SEV_LOW,
    "FINGERPRINT_MATCH": SEV_MED,
}

RULE_LABEL_VI = {
    "DEVICE_REUSE": "Một thiết bị ghi nhận cho nhiều học viên",
    "IP_RATE_SPIKE": "Nhiều lượt ghi nhận dồn dập từ cùng một địa chỉ IP",
    "DEVICE_MISMATCH": "Thiết bị không khớp thiết bị đã đăng ký",
    "EARLY_DEPARTURE": "Vắng mặt ở lượt điểm danh thứ hai",
    "TOKEN_GRACE_USED": "Mã QR dùng sau hạn xoay vòng, trong khoảng gia hạn",
    "FINGERPRINT_MATCH": "Hai học viên có dấu vết thiết bị trùng nhau trong cùng buổi",
}

# Nhãn ngắn cho cột bảng. Câu đầy đủ ở trên dài 40-60 ký tự; nhét vào một cột của
# bảng 8 cột thì hoặc bảng phải kéo ngang, hoặc chữ bị cắt bằng "…" - mà 17 dòng
# cùng cắt ở đúng một chỗ thì cả cột không còn phân biệt được dòng nào với dòng
# nào. Cột hiện nhãn ngắn, câu đầy đủ nằm ở tooltip và ở ô thống kê phía trên.
RULE_LABEL_SHORT_VI = {
    "DEVICE_REUSE": "Thiết bị dùng chung",
    "IP_RATE_SPIKE": "Dồn dập cùng IP",
    "DEVICE_MISMATCH": "Sai thiết bị",
    "EARLY_DEPARTURE": "Vắng lượt 2",
    "TOKEN_GRACE_USED": "Mã quá hạn",
    "FINGERPRINT_MATCH": "Trùng dấu vết máy",
}

LEVEL_OK, LEVEL_WATCH, LEVEL_AT_RISK = "ok", "watch", "at_risk"


# --------------------------------------------------------------------------
# Thời gian buổi học
# --------------------------------------------------------------------------
def session_start_ms(date: str, start_time: str) -> int:
    return int(datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M").timestamp() * 1000)


def lateness_minutes(session_row: sqlite3.Row, checkin_ts_ms: int) -> int:
    delta = checkin_ts_ms - session_start_ms(session_row["date"], session_row["start_time"])
    return max(0, int(delta // 60000))


def classify_status(session_row: sqlite3.Row, checkin_ts_ms: int, late_after_min: int) -> str:
    return "late" if lateness_minutes(session_row, checkin_ts_ms) >= late_after_min else "present"


# --------------------------------------------------------------------------
# Ghi flag
# --------------------------------------------------------------------------
def raise_flag(
    conn: sqlite3.Connection,
    attendance_id: int | None,
    session_id: int | None,
    student_id: str | None,
    rule_code: str,
    detail: str,
) -> bool:
    """Ghi một flag bất thường. Trả về True nếu là flag mới.

    Với flag không gắn vào bản ghi nào (`attendance_id` NULL - ví dụ check-in bị
    chặn nên không có dòng attendance), ràng buộc UNIQUE không chặn trùng được vì
    SQLite coi mỗi NULL là một giá trị khác nhau. Nên phải tự chống trùng theo
    (buổi, học viên, rule), nếu không mỗi lần học viên bấm lại là thêm một flag.
    """
    if attendance_id is None:
        existing = conn.execute(
            """SELECT 1 FROM anomaly_flags
               WHERE attendance_id IS NULL AND session_id IS ? AND student_id IS ?
                 AND rule_code = ? AND resolved = 0""",
            (session_id, student_id, rule_code),
        ).fetchone()
        if existing is not None:
            return False

    cur = conn.execute(
        """INSERT OR IGNORE INTO anomaly_flags
           (attendance_id, session_id, student_id, rule_code, severity, detail, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (
            attendance_id,
            session_id,
            student_id,
            rule_code,
            RULE_SEVERITY[rule_code],
            detail,
            now_ms(),
        ),
    )
    return cur.rowcount > 0


def evaluate_checkin(
    conn: sqlite3.Connection,
    attendance_id: int,
    cfg: dict[str, Any],
    token_in_grace: bool = False,
) -> list[str]:
    """Chạy các rule áp được ngay lúc check-in. Trả về danh sách mã rule đã kích hoạt."""
    row = conn.execute("SELECT * FROM attendance WHERE id = ?", (attendance_id,)).fetchone()
    if row is None:
        return []

    fired: list[str] = []
    session_id = row["session_id"]
    student_id = row["student_id"]

    # DEVICE_REUSE - một device_hash gắn với >=2 học viên trong cùng buổi
    if row["device_hash"]:
        others = conn.execute(
            """SELECT id, student_id FROM attendance
               WHERE session_id = ? AND device_hash = ? AND student_id != ?""",
            (session_id, row["device_hash"], student_id),
        ).fetchall()
        if others:
            names = ", ".join(sorted({o["student_id"] for o in others}))
            if raise_flag(
                conn, attendance_id, session_id, student_id, "DEVICE_REUSE",
                f"Cùng thiết bị với: {names}",
            ):
                fired.append("DEVICE_REUSE")
            # gắn flag cả các bản ghi trước đó để dashboard thấy đủ hai đầu
            for other in others:
                raise_flag(
                    conn, other["id"], session_id, other["student_id"], "DEVICE_REUSE",
                    f"Cùng thiết bị với: {student_id}",
                )

    # IP_RATE_SPIKE - >=N check-in từ cùng IP trong cửa sổ ngắn
    if row["ip"]:
        window_ms = int(cfg["anomaly"]["ip_rate_spike_window_sec"]) * 1000
        threshold = int(cfg["anomaly"]["ip_rate_spike_count"])
        recent_hits = conn.execute(
            """SELECT COUNT(*) AS n FROM attendance
               WHERE session_id = ? AND ip = ? AND checkin_ts_ms BETWEEN ? AND ?""",
            (session_id, row["ip"], row["checkin_ts_ms"] - window_ms, row["checkin_ts_ms"]),
        ).fetchone()["n"]
        if recent_hits >= threshold:
            if raise_flag(
                conn, attendance_id, session_id, student_id, "IP_RATE_SPIKE",
                f"{recent_hits} check-in từ {row['ip']} trong {cfg['anomaly']['ip_rate_spike_window_sec']}s",
            ):
                fired.append("IP_RATE_SPIKE")

    # DEVICE_MISMATCH - lệch với thiết bị đã khoá của học viên
    student = conn.execute(
        "SELECT device_hash FROM students WHERE student_id = ?", (student_id,)
    ).fetchone()
    if (
        student is not None
        and student["device_hash"]
        and row["device_hash"]
        and student["device_hash"] != row["device_hash"]
    ):
        if raise_flag(
            conn, attendance_id, session_id, student_id, "DEVICE_MISMATCH",
            "Thiết bị khác với thiết bị đã khoá; cần Labcoach mở lại thủ công",
        ):
            fired.append("DEVICE_MISMATCH")

    # FINGERPRINT_MATCH - hai học viên cùng dấu vết máy trong một buổi.
    #
    # Bắt được lỗ hở còn lại của lớp 3: mở hai cửa sổ ẩn danh trên một điện thoại
    # thì mỗi cửa sổ nhận một cookie riêng, nên device_hash khác nhau và luật "một
    # thiết bị một học viên" không thấy gì. Nhưng fingerprint thì vẫn giống.
    #
    # Chỉ **gắn flag**, không chặn: hai điện thoại cùng model, cùng hệ điều hành,
    # cùng cỡ màn hình cho fingerprint giống nhau, mà lớp học thì đầy máy giống
    # nhau. Chặn theo tín hiệu này là chặn oan bạn cùng lớp - hậu quả nặng hơn thứ
    # nó ngăn được. Để Labcoach xem hai người có ngồi cạnh nhau không rồi tự quyết.
    if row["fp_hash"]:
        twins = conn.execute(
            """SELECT student_id FROM attendance
               WHERE session_id = ? AND fp_hash = ? AND student_id != ?""",
            (session_id, row["fp_hash"], student_id),
        ).fetchall()
        if twins:
            names = ", ".join(sorted({t["student_id"] for t in twins}))
            if raise_flag(
                conn, attendance_id, session_id, student_id, "FINGERPRINT_MATCH",
                f"Dấu vết máy giống với: {names} (có thể cùng model, cần người xem)",
            ):
                fired.append("FINGERPRINT_MATCH")

    # TOKEN_GRACE_USED - mã QR dùng trong khoảng gia hạn
    if token_in_grace:
        if raise_flag(
            conn, attendance_id, session_id, student_id, "TOKEN_GRACE_USED",
            "Mã QR đã quá hạn xoay vòng, còn trong khoảng gia hạn",
        ):
            fired.append("TOKEN_GRACE_USED")

    return fired


def detect_early_departures(conn: sqlite3.Connection, session_id: int) -> list[str]:
    """EARLY_DEPARTURE: có mặt ở lượt 1 nhưng vắng ở lượt 2.

    Chỉ chạy được sau khi lượt 2 đã đóng - trước đó "chưa check-in" và "vắng"
    là hai chuyện khác nhau, gắn flag sớm là vu oan.
    """
    session = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if session is None or session["second_call_ts"] is None:
        return []

    early_departures = conn.execute(
        """SELECT a1.id, a1.student_id FROM attendance a1
           WHERE a1.session_id = ? AND a1.call_index = 1 AND a1.status != 'absent'
             AND NOT EXISTS (
                SELECT 1 FROM attendance a2
                WHERE a2.session_id = a1.session_id AND a2.student_id = a1.student_id
                  AND a2.call_index = 2 AND a2.status != 'absent')""",
        (session_id,),
    ).fetchall()

    fired = []
    for row in early_departures:
        if raise_flag(
            conn, row["id"], session_id, row["student_id"], "EARLY_DEPARTURE",
            "Ghi nhận đầu giờ nhưng không có mặt ở lượt điểm danh thứ hai",
        ):
            fired.append(row["student_id"])
    return fired


# --------------------------------------------------------------------------
# Mức rủi ro
# --------------------------------------------------------------------------
@dataclass
class RiskResult:
    student_id: str
    level: str
    trace: dict[str, Any]


def _history(
    conn: sqlite3.Connection, student_id: str, window: int, as_of_date: str
) -> list[dict[str, Any]]:
    """Lịch sử N buổi gần nhất, tính cả buổi vắng (vắng = không có bản ghi)."""
    sessions = conn.execute(
        """SELECT * FROM sessions
           WHERE date <= ? AND state = 'closed'
           ORDER BY date DESC, start_time DESC LIMIT ?""",
        (as_of_date, window),
    ).fetchall()

    history = []
    for session in reversed(sessions):  # thứ tự thời gian tăng
        row = conn.execute(
            """SELECT * FROM attendance
               WHERE student_id = ? AND session_id = ? AND call_index = 1""",
            (student_id, session["session_id"]),
        ).fetchone()
        if row is None or row["status"] == "absent":
            history.append(
                {
                    "session_id": session["session_id"],
                    "date": session["date"],
                    "status": "absent",
                    "late_min": None,
                    "source": None,
                }
            )
        else:
            history.append(
                {
                    "session_id": session["session_id"],
                    "date": session["date"],
                    "status": row["status"],
                    "late_min": lateness_minutes(session, row["checkin_ts_ms"]),
                    # `source` đi kèm vì `late_min` của bản ghi tay KHÔNG phải giờ
                    # học viên đến: nó là lúc Labcoach bấm nút. Labcoach điểm danh
                    # bù lúc nửa đêm cho buổi sáng thì ra "trễ 922 phút" - con số
                    # đó không mô tả học viên. Ai đọc `late_min` phải nhìn được nó
                    # đến từ đâu.
                    "source": row["source"],
                }
            )
    return history


def _longest_increasing_lateness(history: list[dict[str, Any]], min_end_minutes: int) -> int:
    """Chuỗi dài nhất các buổi liền nhau có số phút trễ tăng dần.

    Hai điều kiện, cả hai đều cần thiết:

    - **Một buổi vắng làm đứt chuỗi.** Vắng không phải là "trễ hơn".
    - **Chuỗi phải kết thúc ở mức muộn thật** (>= ``min_end_minutes``). Không có
      điều kiện này thì 1' -> 3' -> 7' cũng thành tín hiệu, và đó là dao động bình
      thường của người đi đúng giờ chứ không phải người đang rời khỏi lớp. Trên dữ
      liệu 40 học viên, thiếu ngưỡng sàn làm 11 người bị xếp watch oan.
      Ca G07 trong spec (6' -> 14' -> 21') vẫn kích hoạt vì kết thúc ở 21'.
    """
    best = run = 0
    prev: int | None = None
    for entry in history:
        late = entry["late_min"]
        if late is None:
            prev, run = None, 0
            continue
        if prev is not None and late > prev:
            run = 2 if run < 2 else run + 1
        else:
            run = 1
        prev = late
        if late >= min_end_minutes:
            best = max(best, run)
    return best


def _trailing_absence_streak(history: list[dict[str, Any]]) -> int:
    streak = 0
    for entry in reversed(history):
        if entry["status"] == "absent":
            streak += 1
        else:
            break
    return streak


def compute_risk(
    conn: sqlite3.Connection, student_id: str, cfg: dict[str, Any], as_of_date: str
) -> RiskResult:
    risk_cfg = cfg["risk"]
    window = int(risk_cfg["window_sessions"])
    history = _history(conn, student_id, window, as_of_date)

    absent = sum(1 for h in history if h["status"] == "absent")
    late = sum(1 for h in history if h["status"] == "late")
    session_ids = [h["session_id"] for h in history]

    high_flags: list[dict[str, Any]] = []
    early_departure_count = 0
    if session_ids:
        placeholders = ",".join("?" * len(session_ids))
        rows = conn.execute(
            f"""SELECT rule_code, severity, session_id, detail FROM anomaly_flags
                WHERE student_id = ? AND resolved = 0 AND session_id IN ({placeholders})""",
            (student_id, *session_ids),
        ).fetchall()
        for row in rows:
            if row["severity"] == SEV_HIGH:
                high_flags.append({"rule_code": row["rule_code"], "session_id": row["session_id"]})
            if row["rule_code"] == "EARLY_DEPARTURE":
                early_departure_count += 1

    increasing = _longest_increasing_lateness(
        history, int(risk_cfg["watch"]["increasing_lateness_min_end_min"])
    )
    absence_streak = _trailing_absence_streak(history)
    had_lateness_before_streak = any(
        h["status"] == "late" for h in history[: len(history) - absence_streak]
    )

    signals: list[dict[str, Any]] = []

    def signal(code: str, value: Any, threshold: Any, note: str, tier: str) -> None:
        """`tier` = mức mà tín hiệu này thuộc về.

        Cần vì một hồ sơ vắng 3 buổi kích hoạt cả ABSENT_GTE (at_risk) lẫn
        ABSENT_WATCH (watch) - hai câu gần như trùng nhau. Giữ cả hai trong
        `rule_trace` để audit đầy đủ, nhưng giao diện chỉ cần làm nổi tín hiệu
        *quyết định ra mức*, phần còn lại thu lại cho đỡ nhiễu.
        """
        signals.append(
            {"code": code, "value": value, "threshold": threshold, "note": note, "tier": tier}
        )

    # --- at_risk ---
    at_cfg = risk_cfg["at_risk"]
    if absent >= int(at_cfg["absent_gte"]):
        signal("ABSENT_GTE", absent, at_cfg["absent_gte"],
               f"Vắng {absent} buổi trong {window} buổi gần nhất", LEVEL_AT_RISK)
    if absence_streak >= int(at_cfg["silent_streak_after_lateness"]) and had_lateness_before_streak:
        signal(
            "SILENT_AFTER_LATENESS",
            absence_streak,
            at_cfg["silent_streak_after_lateness"],
            f"Im lặng {absence_streak} buổi liên tiếp sau chuỗi đi muộn",
            LEVEL_AT_RISK,
        )
    if early_departure_count >= int(at_cfg["early_departure_flags_gte"]):
        # Câu này hiện thẳng trên dashboard và được đưa cho tầng mô hình làm dữ kiện,
        # nên viết bằng tiếng Việt chứ không nhắc mã rule: mã nằm ở trường `code`.
        signal("EARLY_DEPARTURE_REPEATED", early_departure_count, at_cfg["early_departure_flags_gte"],
               f"Vắng ở lượt điểm danh thứ hai {early_departure_count} lần", LEVEL_AT_RISK)

    at_risk_signals = list(signals)

    # --- watch ---
    # Dùng ">=" chứ không phải "==" cho số buổi vắng: at_risk đã được xét trước nên
    # ">=" không lấn sang mức cao hơn, mà lại bịt được lỗ hổng khi ai đó sửa config
    # thành watch=2 / at_risk=5 - lúc đó vắng 3 buổi sẽ không rơi vào mức nào cả.
    watch_cfg = risk_cfg["watch"]
    if absent >= int(watch_cfg["absent_gte"]):
        signal("ABSENT_WATCH", absent, watch_cfg["absent_gte"], f"Vắng {absent} buổi", LEVEL_WATCH)
    if late >= int(watch_cfg["late_sessions_gte"]):
        signal("LATE_SESSIONS", late, watch_cfg["late_sessions_gte"], f"Đi muộn {late} buổi", LEVEL_WATCH)
    if increasing >= int(watch_cfg["increasing_lateness_streak"]):
        signal(
            "INCREASING_LATENESS",
            increasing,
            watch_cfg["increasing_lateness_streak"],
            f"Số phút trễ tăng dần {increasing} buổi liên tiếp",
            LEVEL_WATCH,
        )

    watch_signals = [s for s in signals if s not in at_risk_signals]

    if at_risk_signals:
        level = LEVEL_AT_RISK
    elif watch_signals:
        level = LEVEL_WATCH
    elif high_flags:
        # Chưa vượt ngưỡng chuyên cần nào, nhưng hồ sơ còn flag mức high chưa xử lý
        # thì không được báo "ok" - báo ok lúc này là che mất việc cần làm.
        level = LEVEL_WATCH
        signal("UNRESOLVED_HIGH_FLAG", len(high_flags), 1, "Còn flag mức high chưa xử lý", LEVEL_WATCH)
    else:
        level = LEVEL_OK

    trace = {
        "as_of": as_of_date,
        "window_sessions": window,
        "level": level,
        "counts": {"absent": absent, "late": late, "sessions_considered": len(history)},
        "absence_streak": absence_streak,
        "increasing_lateness_streak": increasing,
        "early_departure_flags": early_departure_count,
        "high_flags": high_flags,
        "signals": signals,
        "history": history,
    }
    return RiskResult(student_id=student_id, level=level, trace=trace)


def build_briefing(
    conn: sqlite3.Connection, cfg: dict[str, Any], as_of_date: str, actor: str = "system"
) -> list[RiskResult]:
    """Tính rủi ro cho toàn lớp, lưu snapshot, trả về danh sách ưu tiên.

    Bản tin đầu ngày = việc duy nhất của Labcoach trong lát cắt (§4.1). Cắt còn
    tối đa `briefing_max_cases` ca để danh sách còn dùng được thật, không thành
    một bảng dài không ai đọc - đúng ma sát mà §1 mô tả.
    """
    students = conn.execute(
        "SELECT student_id FROM students WHERE active = 1 ORDER BY student_id"
    ).fetchall()

    results = [compute_risk(conn, s["student_id"], cfg, as_of_date) for s in students]

    ts = now_ms()
    for result in results:
        conn.execute(
            """INSERT INTO risk_snapshots (student_id, date, risk_level, rule_trace, created_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(student_id, date) DO UPDATE SET
                   risk_level = excluded.risk_level,
                   rule_trace = excluded.rule_trace,
                   created_at = excluded.created_at""",
            (result.student_id, as_of_date, result.level, json.dumps(result.trace, ensure_ascii=False), ts),
        )

    order = {LEVEL_AT_RISK: 0, LEVEL_WATCH: 1, LEVEL_OK: 2}
    flagged = [r for r in results if r.level != LEVEL_OK]
    flagged.sort(
        key=lambda r: (
            order[r.level],
            -r.trace["counts"]["absent"],
            -len(r.trace["signals"]),
            r.student_id,
        )
    )
    top = flagged[: int(cfg["risk"]["briefing_max_cases"])]

    audit(
        conn,
        actor,
        "build_briefing",
        target=as_of_date,
        detail=f"{len(flagged)} ca cần chú ý, hiện {len(top)}",
    )
    conn.commit()
    return top
