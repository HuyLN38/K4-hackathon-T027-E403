"""Mở phiên /me bằng thiết bị đã buộc, không cần PIN.

Đây là một đường xác thực mới, nên phần lớn test ở đây kiểm các ca **từ chối**:
một đường đăng nhập chỉ an toàn bằng đúng những trường hợp nó nói không.

Nguyên tắc: chỉ đúng thiết bị đang buộc với một mã học viên còn hoạt động mới mở
được phiên, và phiên đó chỉ đọc được dữ liệu của chính chủ thiết bị.
"""
from __future__ import annotations

import pytest
from conftest import (
    IP_IN,
    checkin,
    create_session,
    current_token,
    make_client,
    open_session,
)

TODAY = "2026-07-30"


def bind_device(appmod, admin_client, conn, student_id: str, fingerprint: str = "fp-may-cua-toi"):
    """Cho một học viên check-in một lần để thiết bị được buộc. Trả về client đó."""
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    device = make_client(appmod)
    res = checkin(device, current_token(admin_client, session_id), student_id, fingerprint)
    assert res.status_code == 200, res.text
    admin_client.post(f"/api/admin/sessions/{session_id}/close")
    return device


def device_session(client, fingerprint: str = "fp-may-cua-toi"):
    return client.post("/api/student/device-session", json={"fingerprint": fingerprint})


# ==========================================================================
# Đường chính
# ==========================================================================
def test_bound_device_opens_a_session_without_a_pin(appmod, seeded, admin_client, conn):
    device = bind_device(appmod, admin_client, conn, "K4001")

    res = device_session(device)
    assert res.status_code == 200, res.text
    assert res.json()["student_id"] == "K4001"

    me = device.get("/api/student/me")
    assert me.status_code == 200
    body = me.json()
    assert body["student"]["student_id"] == "K4001"
    assert body["auth_via"] == "device"


def test_pin_login_still_reports_itself_as_pin(seeded, appmod, conn):
    """Hai đường vào phải phân biệt được ở đầu ra, nếu không audit vô nghĩa."""
    conn.execute("UPDATE students SET pin_hash = ?, pin_salt = ? WHERE student_id = 'K4001'",
                 _set_pin(appmod, "123456"))
    conn.commit()
    client = make_client(appmod)
    res = client.post("/api/student/login", json={"student_id": "K4001", "pin": "123456"})
    assert res.status_code == 200, res.text
    assert client.get("/api/student/me").json()["auth_via"] == "pin"


def _set_pin(appmod, pin: str):
    pin_hash, salt = appmod.hash_password(pin)
    return pin_hash, salt


# ==========================================================================
# Các ca phải từ chối
# ==========================================================================
def test_device_that_never_checked_in_is_refused(appmod, seeded):
    """Không có cookie thiết bị thì không có gì để nhận ra."""
    assert device_session(make_client(appmod)).status_code == 401


def test_wrong_fingerprint_on_the_right_cookie_is_refused(appmod, seeded, admin_client, conn):
    """device_hash trộn cookie với fingerprint. Lệch một nửa là lệch cả hash.

    Đây là ca chống việc bê cookie sang máy khác: cookie có thể copy được, nhưng
    fingerprint của máy kia khác nên hash không khớp.
    """
    device = bind_device(appmod, admin_client, conn, "K4001")
    assert device_session(device, fingerprint="fp-cua-may-khac").status_code == 401


def test_device_released_by_labcoach_no_longer_opens_a_session(appmod, seeded, admin_client, conn):
    """Nhả thiết bị là cắt luôn đường vào này - nếu không, học viên mất máy vẫn
    bị người nhặt được máy đọc hồ sơ."""
    device = bind_device(appmod, admin_client, conn, "K4001")
    assert device_session(device).status_code == 200

    res = admin_client.post("/api/admin/students/K4001/release-device",
                            json={"note": "học viên báo mất máy"})
    assert res.status_code == 200, res.text
    assert device_session(device).status_code == 401


def test_deactivated_student_cannot_open_a_session(appmod, seeded, admin_client, conn):
    device = bind_device(appmod, admin_client, conn, "K4001")
    conn.execute("UPDATE students SET active = 0 WHERE student_id = 'K4001'")
    conn.commit()
    assert device_session(device).status_code == 401


# ==========================================================================
# Đăng xuất phải thật sự đăng xuất
# ==========================================================================
def test_logout_stops_the_device_from_signing_back_in(appmod, seeded, admin_client, conn):
    """Không có cờ chặn thì trang tự nhận lại ngay và nút Đăng xuất thành nút
    không làm gì - học viên đưa máy cho bạn xem thứ khác sẽ không thoát được."""
    device = bind_device(appmod, admin_client, conn, "K4001")
    assert device_session(device).status_code == 200

    assert device.post("/api/student/logout").status_code == 200
    assert device.get("/api/student/me").status_code == 401
    assert device_session(device).status_code == 401


def test_pin_login_clears_the_no_auto_flag(appmod, seeded, admin_client, conn):
    """Gõ PIN là nói rõ "đúng tôi", nên cờ chặn được gỡ.

    Không gỡ thì học viên lỡ bấm Đăng xuất một lần sẽ phải gõ PIN mãi mãi trên
    chính máy của mình - đúng thứ tính năng này sinh ra để bỏ đi.

    Lưu ý: mỗi lần Đăng xuất lại đặt cờ trở lại. Đó là chủ ý, không phải lỗi -
    "đăng xuất" phải có tác dụng kể cả lần thứ hai.
    """
    device = bind_device(appmod, admin_client, conn, "K4001")
    device.post("/api/student/logout")
    assert device_session(device).status_code == 401

    pin_hash, salt = _set_pin(appmod, "246810")
    conn.execute("UPDATE students SET pin_hash = ?, pin_salt = ? WHERE student_id = 'K4001'",
                 (pin_hash, salt))
    conn.commit()
    assert device.post("/api/student/login",
                       json={"student_id": "K4001", "pin": "246810"}).status_code == 200

    # Cờ đã được gỡ: đường nhận diện thiết bị sống lại ngay, không phải chờ gì.
    assert device_session(device).status_code == 200


# ==========================================================================
# Phiên mở bằng thiết bị không được rộng hơn phiên mở bằng PIN
# ==========================================================================
def test_device_session_reads_only_its_own_student(appmod, seeded, admin_client, conn):
    device = bind_device(appmod, admin_client, conn, "K4001")
    device_session(device)
    # Không có endpoint nào cho học viên đọc người khác; xác nhận dữ liệu trả về
    # luôn khoá theo chủ thiết bị chứ không theo tham số client gửi lên.
    body = device.get("/api/student/me?student_id=K4002").json()
    assert body["student"]["student_id"] == "K4001"


def test_device_session_cannot_reach_labcoach_endpoints(appmod, seeded, admin_client, conn):
    device = bind_device(appmod, admin_client, conn, "K4001")
    device_session(device)
    for path in ("/api/admin/roster", "/api/admin/anomalies", "/api/admin/briefing"):
        assert device.get(path).status_code in (401, 403), path


def test_device_session_is_audited_distinctly_from_pin_login(appmod, seeded, admin_client, conn):
    """Khi có khiếu nại phải phân biệt được ai gõ PIN và ai chỉ cầm đúng máy."""
    device = bind_device(appmod, admin_client, conn, "K4001")
    device_session(device)
    actions = [r["action"] for r in conn.execute(
        "SELECT action FROM audit_log WHERE actor = 'K4001'")]
    assert "student_device_session" in actions
    assert "student_login" not in actions
