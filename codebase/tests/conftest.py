"""Hạ tầng test: database riêng cho từng test, config riêng cho cả phiên.

`ATTENDANCE_DB` / `ATTENDANCE_CONFIG` phải được đặt **ngay khi import conftest**,
không phải trong fixture. Lý do: `db.py` chốt đường dẫn config lúc import và
`load_config()` có cache, còn code ở tầng module của các file test (`CFG =
load_config()`) chạy lúc pytest collect - tức là trước mọi fixture. Đặt muộn thì
app sẽ dùng config thật với `trust_proxy_header = false`, mọi request từ
TestClient thành ngoài subnet và cả bộ test đỏ vì lý do không liên quan.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

CODEBASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODEBASE))

# IP trong lớp / ngoài lớp dùng xuyên suốt test
IP_IN = "192.168.1.50"
IP_OUT = "203.0.113.9"

_WORKDIR = Path(tempfile.mkdtemp(prefix="attendance-test-"))

_cfg = json.loads((CODEBASE / "config.json").read_text(encoding="utf-8"))
# Chỉ nhận một dải duy nhất để test lớp 1 có ý nghĩa.
_cfg["network"]["allowed_subnets"] = ["192.168.1.0/24"]
_cfg["network"]["enforce_subnet"] = True
# Bật đọc X-Forwarded-For để test giả lập được IP nguồn. Trong lớp học thật flag
# này TẮT, vì client tự đặt được header đó.
_cfg["network"]["trust_proxy_header"] = True
# Tắt tầng mô hình cho toàn bộ test. §7.4 đòi phần chống gian lận kiểm được bằng
# máy, chạy lại được, không phụ thuộc người chấm - mà gọi Ollama thì mỗi lần chạy
# ra một chuỗi khác và mất vài giây. Chất lượng đầu ra của mô hình đo ở eval/,
# không đo ở đây. Đường "mô hình tắt" cũng chính là đường §6 mô tả khi Ollama
# chết, nên test chạy đúng cái nhánh phải luôn hoạt động.
_cfg["llm"]["enabled"] = False

_CONFIG_PATH = _WORKDIR / "config.json"
_CONFIG_PATH.write_text(json.dumps(_cfg), encoding="utf-8")

os.environ["ATTENDANCE_CONFIG"] = str(_CONFIG_PATH)
os.environ["ATTENDANCE_DB"] = str(_WORKDIR / "test.db")


@pytest.fixture()
def appmod():
    """Module app, đã reset sạch database và trạng thái trong RAM."""
    import app as appmod
    import db

    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    for suffix in ("-wal", "-shm"):
        extra = Path(str(db.DB_PATH) + suffix)
        if extra.exists():
            extra.unlink()
    db.init_db()

    appmod.GUARDS.rate.reset()
    appmod.GUARDS.sessions._sessions.clear()
    return appmod


@pytest.fixture()
def conn(appmod):
    import db

    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture()
def seeded(conn):
    """Lớp tối thiểu: 1 Labcoach + 5 học viên, chưa khoá thiết bị."""
    from db import now_ms
    from security import hash_password

    pw_hash, pw_salt = hash_password("mat-khau-test")
    conn.execute(
        """INSERT INTO admins (username, display_name, pw_hash, pw_salt, role, created_at)
           VALUES ('labcoach','Labcoach test',?,?, 'owner', ?)""",
        (pw_hash, pw_salt, now_ms()),
    )
    pin_hash, pin_salt = hash_password("123456")
    for i in range(1, 6):
        conn.execute(
            """INSERT INTO students (student_id, name, pin_hash, pin_salt, active, created_at)
               VALUES (?,?,?,?,1,?)""",
            (f"K4{i:03d}", f"Học viên {i}", pin_hash, pin_salt, now_ms()),
        )
    conn.commit()
    return conn


def make_client(appmod, ip: str = IP_IN):
    """TestClient gắn sẵn một IP nguồn giả lập, cookie jar riêng.

    Cookie jar riêng = thiết bị riêng: cookie `dev_id` do server phát là nửa
    quyết định của device_hash.
    """
    from fastapi.testclient import TestClient

    client = TestClient(appmod.app)
    client.headers.update({"X-Forwarded-For": ip})
    return client


@pytest.fixture()
def client(appmod):
    return make_client(appmod)


@pytest.fixture()
def admin_client(appmod, seeded):
    """Client đã đăng nhập Labcoach, đã gắn header CSRF."""
    client = make_client(appmod)
    res = client.post(
        "/api/admin/login", json={"username": "labcoach", "password": "mat-khau-test"}
    )
    assert res.status_code == 200, res.text
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    return client


# --------------------------------------------------------------------------
# Tiện ích dựng buổi học
# --------------------------------------------------------------------------
def create_session(conn, date: str, start_time: str = "09:00", late_after_min: int = 10) -> int:
    cur = conn.execute(
        """INSERT INTO sessions (date, start_time, room, state, late_after_min)
           VALUES (?,?, 'Lab A', 'scheduled', ?)""",
        (date, start_time, late_after_min),
    )
    conn.commit()
    return cur.lastrowid


def open_session(admin_client, session_id: int) -> None:
    res = admin_client.post(f"/api/admin/sessions/{session_id}/open")
    assert res.status_code == 200, res.text


def current_token(admin_client, session_id: int) -> str:
    res = admin_client.get(f"/api/projector/token?session_id={session_id}")
    assert res.status_code == 200, res.text
    return res.json()["token"]


def checkin(client, token: str, student_id: str, fingerprint: str = "fp-test"):
    return client.post(
        "/api/checkin",
        json={"token": token, "student_id": student_id, "fingerprint": fingerprint},
    )


def flags_for(conn, student_id: str, rule_code: str | None = None) -> list[str]:
    sql = "SELECT rule_code FROM anomaly_flags WHERE student_id = ?"
    params: list = [student_id]
    if rule_code:
        sql += " AND rule_code = ?"
        params.append(rule_code)
    return [r["rule_code"] for r in conn.execute(sql, params).fetchall()]


def expire_token(conn, token: str, seconds_past: int) -> None:
    """Đẩy hạn của token về quá khứ - test hết hạn mà không phải sleep."""
    from db import now_ms

    conn.execute(
        "UPDATE qr_tokens SET expires_at = ? WHERE token = ?",
        (now_ms() - seconds_past * 1000, token),
    )
    conn.commit()
