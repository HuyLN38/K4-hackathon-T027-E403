"""Lớp 2 của xác thực hiện diện: token QR xoay vòng trên máy chiếu.

Vì sao là token lưu server chứ không phải mã dẫn xuất từ thời gian:

- **Thu hồi được tức thì.** Labcoach thấy có người chụp màn hình gửi ra ngoài thì
  bấm xoay mã, token cũ chết ngay. Mã dẫn xuất từ thời gian không làm được.
- **Đếm được.** ``use_count`` cho biết một token được bao nhiêu người dùng, số này
  hiện trên dashboard.
- **Không đoán được.** 128 bit ngẫu nhiên, không có quan hệ nào giữa hai token
  liên tiếp, nên không thể dựng lại chuỗi mã từ một mẫu bắt được.

Token chỉ chứng minh *người quét đang nhìn thấy màn hình lớp tại thời điểm đó*.
Nó không chứng minh danh tính - việc đó là của lớp 3 (device binding).
"""
from __future__ import annotations

import secrets
import sqlite3
from typing import Any

from db import now_ms

# Lý do từ chối, trả nguyên văn cho client để hiện thông báo đúng.
REASON_UNKNOWN = "token_unknown"
REASON_REVOKED = "token_revoked"
REASON_EXPIRED = "token_expired"
REASON_WRONG_SESSION = "token_wrong_session"
REASON_WRONG_CALL = "token_wrong_call"
REASON_REPLAY = "token_replay"


def _new_token_string() -> str:
    return secrets.token_urlsafe(16)  # 128 bit


def issue_token(
    conn: sqlite3.Connection, session_id: int, call_index: int, rotate_sec: int
) -> sqlite3.Row:
    ts = now_ms()
    token = _new_token_string()
    cur = conn.execute(
        """INSERT INTO qr_tokens (session_id, token, call_index, issued_at, expires_at)
           VALUES (?,?,?,?,?)""",
        (session_id, token, call_index, ts, ts + rotate_sec * 1000),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM qr_tokens WHERE token_id = ?", (cur.lastrowid,)
    ).fetchone()


def active_token(
    conn: sqlite3.Connection, session_id: int, call_index: int, cfg: dict[str, Any]
) -> sqlite3.Row:
    """Token đang hiển thị trên máy chiếu; tự phát mã mới khi mã cũ hết hạn."""
    rotate_sec = int(cfg["qr"]["rotate_sec"])
    ts = now_ms()
    row = conn.execute(
        """SELECT * FROM qr_tokens
           WHERE session_id = ? AND call_index = ? AND revoked = 0 AND expires_at > ?
           ORDER BY issued_at DESC LIMIT 1""",
        (session_id, call_index, ts),
    ).fetchone()
    if row is not None:
        return row
    return issue_token(conn, session_id, call_index, rotate_sec)


def rotate_now(
    conn: sqlite3.Connection, session_id: int, call_index: int, cfg: dict[str, Any]
) -> sqlite3.Row:
    """Thu hồi mọi token đang sống của lượt này rồi phát mã mới.

    Dùng khi Labcoach nghi mã đã bị chụp gửi ra ngoài.
    """
    conn.execute(
        "UPDATE qr_tokens SET revoked = 1 WHERE session_id = ? AND call_index = ? AND revoked = 0",
        (session_id, call_index),
    )
    conn.commit()
    return issue_token(conn, session_id, call_index, int(cfg["qr"]["rotate_sec"]))


def revoke_all(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute(
        "UPDATE qr_tokens SET revoked = 1 WHERE session_id = ? AND revoked = 0", (session_id,)
    )
    conn.commit()


def verify(
    conn: sqlite3.Connection,
    token: str,
    session_id: int,
    call_index: int,
    student_id: str,
    cfg: dict[str, Any],
) -> tuple[bool, sqlite3.Row | None, bool, str | None]:
    """Kiểm tra token học viên vừa quét.

    Trả về ``(hợp_lệ, dòng_token, dùng_trong_gia_hạn, lý_do_từ_chối)``.

    ``dùng_trong_gia_hạn`` = token đã quá ``rotate_sec`` nhưng còn trong ``grace_sec``.
    Vẫn nhận (bù thời gian quét + mạng chậm) nhưng gắn flag TOKEN_GRACE_USED.
    """
    token = (token or "").strip()
    if not token:
        return False, None, False, REASON_UNKNOWN

    row = conn.execute("SELECT * FROM qr_tokens WHERE token = ?", (token,)).fetchone()
    if row is None:
        return False, None, False, REASON_UNKNOWN
    if row["session_id"] != session_id:
        return False, row, False, REASON_WRONG_SESSION
    if row["call_index"] != call_index:
        return False, row, False, REASON_WRONG_CALL
    if row["revoked"]:
        return False, row, False, REASON_REVOKED

    ts = now_ms()
    grace_ms = int(cfg["qr"]["grace_sec"]) * 1000
    if ts > row["expires_at"] + grace_ms:
        return False, row, False, REASON_EXPIRED

    already = conn.execute(
        "SELECT 1 FROM token_usage WHERE token_id = ? AND student_id = ?",
        (row["token_id"], student_id),
    ).fetchone()
    if already is not None:
        return False, row, False, REASON_REPLAY

    in_grace = ts > row["expires_at"]
    return True, row, in_grace, None


def consume(conn: sqlite3.Connection, token_id: int, student_id: str) -> None:
    """Đánh dấu token đã được học viên này dùng. Gọi trong cùng transaction ghi attendance."""
    conn.execute(
        "INSERT OR IGNORE INTO token_usage (token_id, student_id, used_at) VALUES (?,?,?)",
        (token_id, student_id, now_ms()),
    )
    conn.execute("UPDATE qr_tokens SET use_count = use_count + 1 WHERE token_id = ?", (token_id,))
