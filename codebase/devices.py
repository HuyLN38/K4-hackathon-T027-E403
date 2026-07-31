"""Lớp 3 của xác thực hiện diện: một thiết bị chỉ điểm danh cho MỘT học viên.

Quy tắc, phát biểu đầy đủ:

1. Lần check-in đầu tiên buộc `student_id` với `device_hash` của máy đang dùng.
2. Học viên đã buộc mà dùng máy khác  -> chặn, flag `DEVICE_MISMATCH`.
3. Máy đã buộc cho người khác        -> chặn, flag `DEVICE_REUSE`.

Vế 3 là phần mới và là phần khoá lại lỗ hổng thật: trước đây một học viên **chưa**
buộc thiết bị có thể mượn máy của bạn để điểm danh, hệ thống ghi nhận rồi mới gắn
flag. Ghi nhận xong mới gắn flag nghĩa là dữ liệu đã sai trước khi có người xem - đúng
thứ §1 gọi là "số liệu không đáng tin".

Hai vế đều chặn được thì cần đường thoát, vì hỏng điện thoại là chuyện thật:

- `release()` — Labcoach nhả thiết bị của một mã học viên. Nhả xong cả hai phía
  đều tự do: học viên buộc được máy mới, máy cũ buộc được cho người khác.
- Điểm danh tay (`source='manual'` trong app.py) — dùng khi mất máy giữa buổi,
  không kịp xử lý thiết bị.

Mọi lần buộc và nhả đều vào `device_bindings` kèm người thực hiện và lý do. Học
viên bị chặn một buổi có quyền hỏi vì sao, và câu trả lời phải là dữ liệu.
"""
from __future__ import annotations

import sqlite3

from db import audit, now_ms


def owner_of(conn: sqlite3.Connection, device_hash: str) -> str | None:
    """Mã học viên đang giữ thiết bị này, hoặc None nếu chưa ai giữ."""
    row = conn.execute(
        "SELECT student_id FROM students WHERE device_hash = ?", (device_hash,)
    ).fetchone()
    return row["student_id"] if row else None


def bind(conn: sqlite3.Connection, student_id: str, device_hash: str) -> None:
    """Buộc thiết bị cho học viên. Gọi trong cùng transaction ghi attendance.

    Không tự kiểm tra tranh chấp - việc đó thuộc luồng check-in, nơi còn biết
    session nào để gắn flag. Nếu có đường ghi nào lọt qua, index UNIQUE trên
    `students.device_hash` sẽ chặn ở tầng database.
    """
    ts = now_ms()
    conn.execute(
        "UPDATE students SET device_hash = ?, device_locked_at = ? WHERE student_id = ?",
        (device_hash, ts, student_id),
    )
    conn.execute(
        """INSERT INTO device_bindings (student_id, device_hash, bound_at)
           VALUES (?,?,?)""",
        (student_id, device_hash, ts),
    )


def release(
    conn: sqlite3.Connection, student_id: str, actor: str, note: str, ip: str | None = None
) -> dict[str, object]:
    """Nhả thiết bị của một mã học viên - "xóa dữ liệu máy" của người đó.

    Dùng khi: mất điện thoại, đổi máy, máy hỏng, hoặc buộc sai người.

    Sau khi nhả:
      - học viên buộc được máy mới ở lần check-in kế tiếp;
      - máy vừa nhả buộc được cho học viên khác (trường hợp máy mượn của lớp);
      - các flag DEVICE_MISMATCH / DEVICE_REUSE còn treo của học viên này được đóng lại,
        vì chúng đã có người xử lý - chính thao tác này.

    Trả về thông tin đã nhả để giao diện hiện lại cho Labcoach xác nhận.
    """
    student = conn.execute(
        "SELECT student_id, name, device_hash, device_locked_at FROM students WHERE student_id = ?",
        (student_id,),
    ).fetchone()
    if student is None:
        raise KeyError(student_id)

    previous = student["device_hash"]
    ts = now_ms()

    if previous is not None:
        conn.execute(
            """UPDATE device_bindings SET released_at = ?, released_by = ?, release_note = ?
               WHERE student_id = ? AND device_hash = ? AND released_at IS NULL""",
            (ts, actor, note, student_id, previous),
        )
        conn.execute(
            "UPDATE students SET device_hash = NULL, device_locked_at = NULL WHERE student_id = ?",
            (student_id,),
        )

    closed = conn.execute(
        """UPDATE anomaly_flags SET resolved = 1, resolved_by = ?, resolved_note = ?
           WHERE student_id = ? AND resolved = 0
             AND rule_code IN ('DEVICE_MISMATCH', 'DEVICE_REUSE')""",
        (actor, f"Nhả thiết bị: {note}" if note else "Nhả thiết bị", student_id),
    ).rowcount

    audit(
        conn,
        actor,
        "release_device",
        target=student_id,
        detail=f"device={short(previous)};flags_closed={closed};{note}",
        ip=ip,
    )

    return {
        "student_id": student_id,
        "name": student["name"],
        "released_device": short(previous),
        "had_device": previous is not None,
        "flags_closed": closed,
    }


def binding_history(conn: sqlite3.Connection, student_id: str, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """SELECT device_hash, bound_at, released_at, released_by, release_note
           FROM device_bindings WHERE student_id = ?
           ORDER BY bound_at DESC LIMIT ?""",
        (student_id, limit),
    ).fetchall()
    return [
        {
            "device_short": short(r["device_hash"]),
            "bound_at": r["bound_at"],
            "released_at": r["released_at"],
            "released_by": r["released_by"],
            "release_note": r["release_note"],
            "active": r["released_at"] is None,
        }
        for r in rows
    ]


def short(device_hash: str | None) -> str | None:
    """8 ký tự đầu của hash - đủ để Labcoach đối chiếu hai thiết bị bằng mắt,
    không đủ để suy ra fingerprint gốc."""
    return device_hash[:8] if device_hash else None
