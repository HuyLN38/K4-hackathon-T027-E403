"""Kiểm thử đồng thời trên **server uvicorn thật**.

Vì sao không dùng `TestClient` cho nhóm test này: TestClient đẩy mọi request qua
một portal duy nhất, nên dù bắn từ nhiều thread thì phía server vẫn tuần tự. Một
test viết bằng TestClient cho "40 người quét cùng lúc" sẽ **xanh cả khi bug còn
nguyên** - đã thử và đúng như vậy. Muốn bắt được lỗi tầng thread thì phải có
server thật, socket thật, request thật chạy song song.

Bug cụ thể nhóm test này canh: `sqlite3.connect()` mặc định không cho dùng
connection ở thread khác thread đã tạo, mà FastAPI chạy dependency đồng bộ và thân
endpoint ở hai thread khác nhau của threadpool. Chạy lẻ thì threadpool hay tái
dùng đúng một thread nên không lộ; đúng lúc cả lớp quét QR cùng lúc mới vỡ.
"""
from __future__ import annotations

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import uvicorn
from conftest import IP_IN, create_session

TODAY = "2026-07-30"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def live_server(appmod, seeded):
    """Server uvicorn thật trong một thread, tắt khi test xong."""
    port = _free_port()
    config = uvicorn.Config(appmod.app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    # uvicorn cài signal handler, việc đó chỉ làm được ở main thread
    server.install_signal_handlers = lambda: None

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "server không khởi động được"

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=15)


@pytest.fixture()
def live_admin(live_server):
    """httpx.Client đã đăng nhập Labcoach, an toàn khi dùng từ nhiều thread."""
    client = httpx.Client(base_url=live_server, headers={"X-Forwarded-For": IP_IN}, timeout=30)
    res = client.post(
        "/api/admin/login", json={"username": "labcoach", "password": "mat-khau-test"}
    )
    assert res.status_code == 200, res.text
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    return client


def test_parallel_reads_never_500(live_admin):
    paths = [
        "/api/admin/roster",
        "/api/admin/sessions",
        "/api/admin/anomalies",
        "/api/admin/audit",
        "/api/admin/briefing",
        "/api/admin/students/K4001/devices",
        "/api/admin/risk/K4001",
        "/api/health",
    ] * 6

    with ThreadPoolExecutor(max_workers=12) as pool:
        codes = list(pool.map(lambda p: live_admin.get(p).status_code, paths))

    assert 500 not in codes, f"có request đổ 500: {sorted(set(codes))}"
    assert all(code == 200 for code in codes), sorted(set(codes))


def test_parallel_checkins_from_forty_devices(live_admin, live_server, conn, appmod):
    """Cả lớp quét cùng lúc - đúng tình huống buổi học thật."""
    session_id = create_session(conn, TODAY)
    assert live_admin.post(f"/api/admin/sessions/{session_id}/open").status_code == 200

    # 40 học viên cho test này
    from db import now_ms
    from security import hash_password

    pin_hash, pin_salt = hash_password("123456")
    for i in range(6, 41):
        conn.execute(
            """INSERT OR IGNORE INTO students
               (student_id, name, pin_hash, pin_salt, active, created_at)
               VALUES (?,?,?,?,1,?)""",
            (f"K4{i:03d}", f"Học viên {i}", pin_hash, pin_salt, now_ms()),
        )
    conn.commit()

    token = live_admin.get(f"/api/projector/token?session_id={session_id}").json()["token"]

    def one(index: int) -> int:
        """Mỗi học viên một client riêng = một cookie jar = một thiết bị."""
        student_id = f"K4{index:03d}"
        with httpx.Client(
            base_url=live_server, headers={"X-Forwarded-For": f"192.168.1.{index % 200 + 10}"},
            timeout=30,
        ) as client:
            res = client.post(
                "/api/checkin",
                json={"token": token, "student_id": student_id, "fingerprint": f"fp-{student_id}"},
            )
            return res.status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(one, range(1, 41)))

    assert 500 not in codes, f"có request đổ 500: {sorted(set(codes))}"
    # Cùng một token nên ai cũng dùng được (token dùng chung trong 20s, mỗi người
    # một lần) - toàn bộ 40 phải vào được.
    assert all(code == 200 for code in codes), sorted(set(codes))

    recorded = conn.execute(
        "SELECT COUNT(*) AS n FROM attendance WHERE session_id = ?", (session_id,)
    ).fetchone()["n"]
    assert recorded == 40, recorded


def test_parallel_writes_do_not_corrupt_device_binding(live_admin, live_server, conn):
    """Thiết bị đã buộc rồi thì hai người khác tranh nhau cùng lúc đều bị chặn.

    Cookie `dev_id` phải có sẵn trước khi thử race. Lần đầu tiên một máy gọi
    `/api/checkin` mà chưa có cookie thì server phát cookie mới ngay trong response
    đó - nên hai request song song *cùng chưa có cookie* là hai danh tính thiết bị
    khác nhau dưới mắt server, và cả hai buộc thành công một cách hợp lệ. Đó không
    phải race trên ràng buộc; đó là giới hạn đã biết của lớp 3 (xem
    `test_incognito_on_one_phone_is_flagged` trong test_security.py).
    """
    session_id = create_session(conn, TODAY)
    live_admin.post(f"/api/admin/sessions/{session_id}/open")

    shared = httpx.Client(base_url=live_server, headers={"X-Forwarded-For": IP_IN}, timeout=30)
    token = live_admin.get(f"/api/projector/token?session_id={session_id}").json()["token"]

    # K4001 buộc thiết bị trước -> client giữ cookie dev_id
    first = shared.post(
        "/api/checkin",
        json={"token": token, "student_id": "K4001", "fingerprint": "fp-chung"},
    )
    assert first.status_code == 200, first.text
    assert shared.cookies.get("dev_id"), "server phải phát cookie thiết bị"

    live_admin.post(f"/api/admin/sessions/{session_id}/rotate-token")
    token2 = live_admin.get(f"/api/projector/token?session_id={session_id}").json()["token"]

    def one(student_id: str) -> int:
        return shared.post(
            "/api/checkin",
            json={"token": token2, "student_id": student_id, "fingerprint": "fp-chung"},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(one, ["K4002", "K4003"]))

    assert 500 not in codes, codes
    assert all(code == 409 for code in codes), codes

    holders = [
        r["student_id"] for r in conn.execute(
            "SELECT student_id FROM students WHERE device_hash IS NOT NULL"
        ).fetchall()
    ]
    assert holders == ["K4001"], f"thiết bị bị buộc sai: {holders}"
    shared.close()
