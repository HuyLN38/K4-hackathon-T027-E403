"""Kiểm thử phần chống gian lận (spec §7.4).

Toàn bộ test ở đây **không dùng mô hình** - đó là điều kiện của §7.4: phần chống
gian lận phải kiểm được bằng máy, chạy lại được, không phụ thuộc người chấm.

Năm ca bắt buộc trong spec được đánh dấu SPEC-7.4-*.
"""
from __future__ import annotations

import re

import pytest
import rules
from conftest import (
    CODEBASE,
    IP_IN,
    IP_OUT,
    checkin,
    create_session,
    current_token,
    expire_token,
    flags_for,
    make_client,
    open_session,
)

TODAY = "2026-07-30"


# ==========================================================================
# SPEC-7.4-1 · Request từ IP ngoài subnet -> 403
# ==========================================================================
def test_request_from_outside_subnet_is_rejected(appmod, seeded):
    outsider = make_client(appmod, ip=IP_OUT)
    res = outsider.get("/")
    assert res.status_code == 403
    assert "dải mạng" in res.text

    res = outsider.post(
        "/api/checkin", json={"token": "x", "student_id": "K4001", "fingerprint": "f"}
    )
    assert res.status_code == 403
    assert res.json()["error"] == "outside_class_network"


def test_request_from_inside_subnet_is_allowed(client, seeded):
    assert client.get("/").status_code == 200


def test_ipv6_and_garbage_source_addresses_are_rejected(appmod, seeded):
    for bad_ip in ["not-an-ip", "10.0.0.1", "::1", ""]:
        outsider = make_client(appmod, ip=bad_ip)
        assert outsider.get("/").status_code == 403, bad_ip


# ==========================================================================
# SPEC-7.4-2 · Token QR hết hạn -> từ chối
# ==========================================================================
def test_expired_token_is_rejected(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    token = current_token(admin_client, session_id)

    expire_token(conn, token, seconds_past=60)  # quá cả grace

    res = checkin(make_client(appmod), token, "K4001")
    assert res.status_code == 400
    assert "hết hạn" in res.json()["error"]
    assert conn.execute("SELECT COUNT(*) AS n FROM attendance").fetchone()["n"] == 0


def test_token_inside_grace_is_accepted_but_flagged(appmod, seeded, admin_client, conn):
    """Trong khoảng gia hạn thì vẫn nhận - nhưng phải để lại dấu."""
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    token = current_token(admin_client, session_id)

    expire_token(conn, token, seconds_past=3)  # quá hạn 3s, grace 10s

    res = checkin(make_client(appmod), token, "K4001")
    assert res.status_code == 200, res.text
    assert "TOKEN_GRACE_USED" in flags_for(conn, "K4001")


def test_revoked_token_is_rejected_immediately(appmod, seeded, admin_client, conn):
    """Labcoach thấy mã bị chụp gửi ra ngoài -> bấm đổi mã -> mã cũ chết ngay."""
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    stolen = current_token(admin_client, session_id)

    res = admin_client.post(f"/api/admin/sessions/{session_id}/rotate-token")
    assert res.status_code == 200
    assert res.json()["token"] != stolen

    res = checkin(make_client(appmod), stolen, "K4001")
    assert res.status_code == 400
    assert "thu hồi" in res.json()["error"]


def test_unknown_token_is_rejected(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    res = checkin(make_client(appmod), "token-hoan-toan-bia-ra", "K4001")
    assert res.status_code == 400


def test_same_token_cannot_be_replayed_by_same_student(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    token = current_token(admin_client, session_id)
    device = make_client(appmod)

    assert checkin(device, token, "K4001").status_code == 200
    again = checkin(device, token, "K4001")
    # Chặn ở tầng token (đã dùng rồi) trước cả khi tới ràng buộc UNIQUE của bảng
    # attendance - lý do trả về vì thế nói đúng chuyện đang xảy ra.
    assert again.status_code == 400
    assert "đã dùng rồi" in again.json()["error"]
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM attendance WHERE student_id='K4001'"
    ).fetchone()["n"] == 1


def test_token_from_first_call_does_not_work_for_second_call(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    call1_token = current_token(admin_client, session_id)

    assert admin_client.post(f"/api/admin/sessions/{session_id}/second-call").status_code == 200

    res = checkin(make_client(appmod), call1_token, "K4002")
    assert res.status_code in (400, 409)


# ==========================================================================
# SPEC-7.4-3 · Hai student_id từ cùng device_hash -> DEVICE_REUSE
# ==========================================================================
def test_second_student_on_same_device_is_blocked(appmod, seeded, admin_client, conn):
    """Một thiết bị chỉ điểm danh cho MỘT học viên.

    Phải chặn trước khi ghi. Ghi rồi mới gắn flag nghĩa là dữ liệu đã sai từ lúc
    chưa ai xem - đúng thứ §1 gọi là "số liệu không đáng tin".
    """
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)

    device = make_client(appmod)  # một cookie jar = một thiết bị
    token1 = current_token(admin_client, session_id)
    assert checkin(device, token1, "K4001", "fp-cung-may").status_code == 200

    admin_client.post(f"/api/admin/sessions/{session_id}/rotate-token")
    token2 = current_token(admin_client, session_id)
    res = checkin(device, token2, "K4002", "fp-cung-may")

    assert res.status_code == 409
    assert "một người" in res.json()["error"]
    assert "DEVICE_REUSE" in flags_for(conn, "K4002")

    # K4002 không có bản ghi nào, và cũng không bị buộc vào máy của K4001
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM attendance WHERE student_id='K4002'"
    ).fetchone()["n"] == 0
    assert conn.execute(
        "SELECT device_hash FROM students WHERE student_id='K4002'"
    ).fetchone()["device_hash"] is None

    severity = conn.execute(
        "SELECT severity FROM anomaly_flags WHERE rule_code='DEVICE_REUSE' LIMIT 1"
    ).fetchone()["severity"]
    assert severity == "high"


def test_unbound_student_cannot_hijack_a_bound_device(appmod, seeded, admin_client, conn):
    """Lỗ hổng cũ: học viên CHƯA buộc thiết bị mượn máy bạn để điểm danh.

    Trước đây vế này lọt vì chỉ kiểm "thiết bị của học viên này có khác không",
    mà học viên chưa buộc thì không có gì để so.
    """
    first = create_session(conn, TODAY)
    open_session(admin_client, first)
    borrowed = make_client(appmod)
    assert checkin(borrowed, current_token(admin_client, first), "K4001", "fp-x").status_code == 200
    admin_client.post(f"/api/admin/sessions/{first}/close")

    # buổi khác, K4002 vẫn chưa từng check-in lần nào
    second = create_session(conn, "2026-07-31")
    open_session(admin_client, second)
    assert conn.execute(
        "SELECT device_hash FROM students WHERE student_id='K4002'"
    ).fetchone()["device_hash"] is None

    res = checkin(borrowed, current_token(admin_client, second), "K4002", "fp-x")
    assert res.status_code == 409
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM attendance WHERE student_id='K4002'"
    ).fetchone()["n"] == 0


def test_incognito_on_one_phone_is_flagged(appmod, seeded, admin_client, conn):
    """Lỗ hở còn lại của lớp 3, và cách bù.

    Mở cửa sổ ẩn danh thứ hai trên cùng một điện thoại: cookie mới nên device_hash
    mới, luật "một thiết bị một học viên" **không** chặn được - server không có
    cách nào biết hai cookie đó ở cùng một máy.

    Bù bằng flag `FINGERPRINT_MATCH` mức med: fingerprint vẫn giống nhau. Cố tình **không
    chặn** - hai điện thoại cùng model cho fingerprint giống nhau, mà lớp học thì
    đầy máy giống nhau, nên chặn là chặn oan bạn cùng lớp. Để Labcoach xem hai
    người có ngồi cạnh nhau không rồi tự quyết.
    """
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)

    window1 = make_client(appmod)
    assert checkin(
        window1, current_token(admin_client, session_id), "K4001", "fp-iphone-13-vn"
    ).status_code == 200

    admin_client.post(f"/api/admin/sessions/{session_id}/rotate-token")
    window2 = make_client(appmod)  # cookie jar mới = cửa sổ ẩn danh
    res = checkin(
        window2, current_token(admin_client, session_id), "K4002", "fp-iphone-13-vn"
    )

    assert res.status_code == 200, "cố ý không chặn - chặn theo fingerprint là chặn oan"
    assert "FINGERPRINT_MATCH" in flags_for(conn, "K4002")
    assert any(f["code"] == "FINGERPRINT_MATCH" for f in res.json()["flags"])

    severity = conn.execute(
        "SELECT severity FROM anomaly_flags WHERE rule_code='FINGERPRINT_MATCH' LIMIT 1"
    ).fetchone()["severity"]
    assert severity == "med"


def test_different_fingerprints_do_not_trigger_fingerprint_match(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    for i, student in enumerate(["K4001", "K4002"]):
        if i:
            admin_client.post(f"/api/admin/sessions/{session_id}/rotate-token")
        assert checkin(
            make_client(appmod), current_token(admin_client, session_id), student, f"fp-{student}"
        ).status_code == 200
    assert "FINGERPRINT_MATCH" not in flags_for(conn, "K4002")


def test_database_index_forbids_two_students_holding_one_device(seeded):
    """Ràng buộc được chốt ở tầng database, không chỉ ở tầng code.

    Nếu về sau có đường ghi nào quên kiểm tra, index UNIQUE vẫn chặn.
    """
    import sqlite3 as _sqlite3

    seeded.execute("UPDATE students SET device_hash = 'hash-chung' WHERE student_id = 'K4001'")
    seeded.commit()
    with pytest.raises(_sqlite3.IntegrityError):
        seeded.execute("UPDATE students SET device_hash = 'hash-chung' WHERE student_id = 'K4002'")
        seeded.commit()


def test_many_students_can_share_null_device(seeded):
    """Index UNIQUE là một phần (WHERE device_hash IS NOT NULL) - nhiều học viên
    chưa buộc thiết bị vẫn hợp lệ, nếu không thì cả lớp mới nhận không ai vào được."""
    seeded.execute("UPDATE students SET device_hash = NULL")
    seeded.commit()
    assert seeded.execute(
        "SELECT COUNT(*) AS n FROM students WHERE device_hash IS NULL"
    ).fetchone()["n"] == 5


# ==========================================================================
# SPEC-7.4-4 · 3 request/5s cùng IP -> IP_RATE_SPIKE
# ==========================================================================
def test_three_checkins_from_one_ip_raise_ip_rate_spike(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)

    for i, student in enumerate(["K4001", "K4002", "K4003"]):
        if i:
            admin_client.post(f"/api/admin/sessions/{session_id}/rotate-token")
        token = current_token(admin_client, session_id)
        device = make_client(appmod, ip=IP_IN)  # cùng IP, khác thiết bị
        assert checkin(device, token, student, f"fp-{student}").status_code == 200

    assert "IP_RATE_SPIKE" in flags_for(conn, "K4003")


def test_two_checkins_from_one_ip_do_not_raise_ip_rate_spike(appmod, seeded, admin_client, conn):
    """Ngưỡng là 3 - hai người dùng chung một IP là chuyện bình thường."""
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)

    for i, student in enumerate(["K4001", "K4002"]):
        if i:
            admin_client.post(f"/api/admin/sessions/{session_id}/rotate-token")
        token = current_token(admin_client, session_id)
        assert checkin(make_client(appmod), token, student, f"fp-{student}").status_code == 200

    assert "IP_RATE_SPIKE" not in flags_for(conn, "K4002")


# ==========================================================================
# SPEC-7.4-5 · Có lượt 1, thiếu lượt 2 -> EARLY_DEPARTURE
# ==========================================================================
def test_present_at_call_one_absent_at_call_two_raises_early_departure(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)

    token = current_token(admin_client, session_id)
    stayer = make_client(appmod)
    leaver = make_client(appmod)
    assert checkin(stayer, token, "K4001", "fp-1").status_code == 200
    assert checkin(leaver, token, "K4002", "fp-2").status_code == 200

    assert admin_client.post(f"/api/admin/sessions/{session_id}/second-call").status_code == 200
    token2 = current_token(admin_client, session_id)
    assert checkin(stayer, token2, "K4001", "fp-1").status_code == 200  # còn trong lớp

    res = admin_client.post(f"/api/admin/sessions/{session_id}/close")
    assert res.status_code == 200
    assert res.json()["early_departure_flags"] == ["K4002"]

    assert "EARLY_DEPARTURE" in flags_for(conn, "K4002")
    assert "EARLY_DEPARTURE" not in flags_for(conn, "K4001")


def test_early_departure_is_not_raised_before_second_call_happened(appmod, seeded, admin_client, conn):
    """Chưa gọi lượt 2 thì "chưa check-in" khác "vắng" - gắn flag sớm là vu oan."""
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    token = current_token(admin_client, session_id)
    assert checkin(make_client(appmod), token, "K4001").status_code == 200

    res = admin_client.post(f"/api/admin/sessions/{session_id}/close")
    assert res.status_code == 200
    assert res.json()["early_departure_flags"] == []
    assert flags_for(conn, "K4001", "EARLY_DEPARTURE") == []


# ==========================================================================
# Lớp 3 · buộc thiết bị
# ==========================================================================
def test_device_is_locked_on_first_checkin(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    token = current_token(admin_client, session_id)

    res = checkin(make_client(appmod), token, "K4001")
    assert res.status_code == 200
    assert res.json()["device_locked_now"] is True

    row = conn.execute(
        "SELECT device_hash, device_locked_at FROM students WHERE student_id='K4001'"
    ).fetchone()
    assert row["device_hash"] and row["device_locked_at"]


def test_checkin_from_different_device_is_blocked_and_flagged(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)

    original = make_client(appmod)
    assert checkin(original, current_token(admin_client, session_id), "K4001", "fp-may-cu").status_code == 200

    # buổi sau, người khác mở ẩn danh trên máy mình để điểm danh hộ
    session2 = create_session(conn, "2026-07-31")
    admin_client.post(f"/api/admin/sessions/{session_id}/close")
    open_session(admin_client, session2)
    token2 = current_token(admin_client, session2)

    impostor = make_client(appmod)  # cookie jar khác = thiết bị khác
    res = checkin(impostor, token2, "K4001", "fp-may-la")
    assert res.status_code == 409
    assert "thiết bị" in res.json()["error"].lower()

    assert "DEVICE_MISMATCH" in flags_for(conn, "K4001")
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM attendance WHERE session_id = ?", (session2,)
    ).fetchone()["n"] == 0


def test_blocked_device_mismatch_does_not_pile_up_duplicate_flags(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    original = make_client(appmod)
    checkin(original, current_token(admin_client, session_id), "K4001", "fp-cu")

    session2 = create_session(conn, "2026-07-31")
    admin_client.post(f"/api/admin/sessions/{session_id}/close")
    open_session(admin_client, session2)

    impostor = make_client(appmod)
    for _ in range(4):
        admin_client.post(f"/api/admin/sessions/{session2}/rotate-token")
        checkin(impostor, current_token(admin_client, session2), "K4001", "fp-la")

    assert len(flags_for(conn, "K4001", "DEVICE_MISMATCH")) == 1


def test_labcoach_can_release_device_and_student_rebinds(appmod, seeded, admin_client, conn):
    """Học viên mất máy / đổi máy: Labcoach xóa dữ liệu thiết bị, máy mới buộc lại."""
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    old = make_client(appmod)
    checkin(old, current_token(admin_client, session_id), "K4001", "fp-cu")

    session2 = create_session(conn, "2026-07-31")
    admin_client.post(f"/api/admin/sessions/{session_id}/close")
    open_session(admin_client, session2)

    new_phone = make_client(appmod)
    assert checkin(new_phone, current_token(admin_client, session2), "K4001", "fp-moi").status_code == 409

    res = admin_client.post(
        "/api/admin/students/K4001/release-device", json={"note": "mất điện thoại"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["had_device"] is True

    admin_client.post(f"/api/admin/sessions/{session2}/rotate-token")
    res = checkin(new_phone, current_token(admin_client, session2), "K4001", "fp-moi")
    assert res.status_code == 200, res.text
    assert res.json()["device_locked_now"] is True

    unresolved = conn.execute(
        """SELECT COUNT(*) AS n FROM anomaly_flags
           WHERE student_id='K4001' AND rule_code='DEVICE_MISMATCH' AND resolved=0"""
    ).fetchone()["n"]
    assert unresolved == 0


def test_released_device_can_be_bound_to_another_student(appmod, seeded, admin_client, conn):
    """Máy mượn của lớp: nhả khỏi người này thì người khác dùng được.

    Chặn theo cả hai chiều nên phải nhả được cả hai chiều, nếu không một cái máy
    mượn dùng một lần là chết vĩnh viễn.
    """
    first = create_session(conn, TODAY)
    open_session(admin_client, first)
    loaner = make_client(appmod)
    assert checkin(loaner, current_token(admin_client, first), "K4001", "fp-may-muon").status_code == 200
    admin_client.post(f"/api/admin/sessions/{first}/close")

    second = create_session(conn, "2026-07-31")
    open_session(admin_client, second)
    # chưa nhả -> vẫn chặn
    assert checkin(loaner, current_token(admin_client, second), "K4002", "fp-may-muon").status_code == 409

    admin_client.post(
        "/api/admin/students/K4001/release-device", json={"note": "trả máy mượn của lớp"}
    )
    admin_client.post(f"/api/admin/sessions/{second}/rotate-token")
    res = checkin(loaner, current_token(admin_client, second), "K4002", "fp-may-muon")
    assert res.status_code == 200, res.text

    holder = conn.execute(
        "SELECT student_id FROM students WHERE device_hash IS NOT NULL"
    ).fetchall()
    assert [r["student_id"] for r in holder] == ["K4002"]


def test_release_device_records_history_and_audit(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    checkin(make_client(appmod), current_token(admin_client, session_id), "K4001", "fp-a")

    admin_client.post(
        "/api/admin/students/K4001/release-device", json={"note": "điện thoại vào nước"}
    )

    row = conn.execute(
        """SELECT device_hash, bound_at, released_at, released_by, release_note
           FROM device_bindings WHERE student_id = 'K4001'"""
    ).fetchone()
    assert row["released_at"] is not None
    assert row["released_by"] == "labcoach"
    assert "vào nước" in row["release_note"]

    actions = {r["action"] for r in conn.execute("SELECT action FROM audit_log").fetchall()}
    assert "release_device" in actions

    body = admin_client.get("/api/admin/students/K4001/devices").json()
    assert body["current_device"] is None
    assert body["history"][0]["active"] is False
    assert len(body["history"][0]["device_short"]) == 8  # chỉ 8 ký tự, không lộ hash đầy đủ


def test_release_device_requires_admin_and_csrf(client, appmod, seeded):
    assert client.post(
        "/api/admin/students/K4001/release-device", json={"note": "x"}
    ).status_code == 401

    no_csrf = make_client(appmod)
    no_csrf.post("/api/admin/login", json={"username": "labcoach", "password": "mat-khau-test"})
    assert no_csrf.post(
        "/api/admin/students/K4001/release-device", json={"note": "x"}
    ).status_code == 403


def test_release_unknown_student_is_404(admin_client):
    assert admin_client.post(
        "/api/admin/students/K9999/release-device", json={"note": "x"}
    ).status_code == 404


def test_release_device_on_student_without_device_is_harmless(admin_client, conn):
    res = admin_client.post(
        "/api/admin/students/K4003/release-device", json={"note": "kiểm tra"}
    )
    assert res.status_code == 200
    assert res.json()["had_device"] is False


# ==========================================================================
# Trạng thái buổi học
# ==========================================================================
def test_checkin_rejected_when_session_not_open(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    token = current_token(admin_client, session_id)
    admin_client.post(f"/api/admin/sessions/{session_id}/close")

    res = checkin(make_client(appmod), token, "K4001")
    assert res.status_code in (400, 409)


def test_only_one_session_can_be_open(appmod, seeded, admin_client, conn):
    first = create_session(conn, TODAY)
    second = create_session(conn, TODAY, start_time="14:00")
    open_session(admin_client, first)
    res = admin_client.post(f"/api/admin/sessions/{second}/open")
    assert res.status_code == 409


def test_closed_session_cannot_be_reopened(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    admin_client.post(f"/api/admin/sessions/{session_id}/close")
    assert admin_client.post(f"/api/admin/sessions/{session_id}/open").status_code == 409


def test_unknown_student_cannot_check_in(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    res = checkin(make_client(appmod), current_token(admin_client, session_id), "K9999")
    assert res.status_code == 404


def test_late_status_is_computed_from_session_start(appmod, seeded, admin_client, conn):
    """Buổi bắt đầu 00:01 hôm nay -> check-in bây giờ chắc chắn là muộn."""
    from datetime import date

    session_id = create_session(conn, date.today().isoformat(), start_time="00:01")
    open_session(admin_client, session_id)
    res = checkin(make_client(appmod), current_token(admin_client, session_id), "K4001")
    assert res.status_code == 200
    assert res.json()["status"] == "late"
    assert res.json()["late_minutes"] > 10


# ==========================================================================
# Xác thực Labcoach / học viên
# ==========================================================================
def test_admin_endpoints_require_login(client, seeded):
    for path in [
        "/api/admin/roster",
        "/api/admin/sessions",
        "/api/admin/anomalies",
        "/api/admin/audit",
        "/api/admin/briefing",
        "/api/admin/export/attendance.csv",
    ]:
        assert client.get(path).status_code == 401, path


def test_admin_write_endpoints_require_csrf_token(appmod, seeded):
    client = make_client(appmod)
    res = client.post(
        "/api/admin/login", json={"username": "labcoach", "password": "mat-khau-test"}
    )
    assert res.status_code == 200
    # có phiên hợp lệ nhưng không gửi header CSRF
    assert client.post("/api/admin/briefing/rebuild").status_code == 403
    assert client.post(
        "/api/admin/students/K4001/release-device", json={"note": "x"}
    ).status_code == 403


def test_wrong_csrf_token_is_rejected(admin_client):
    admin_client.headers["X-CSRF-Token"] = "token-bia"
    assert admin_client.post("/api/admin/briefing/rebuild").status_code == 403


def test_bad_admin_password_is_rejected_and_audited(appmod, seeded, conn):
    client = make_client(appmod)
    assert client.post(
        "/api/admin/login", json={"username": "labcoach", "password": "sai"}
    ).status_code == 401
    actions = [r["action"] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    assert "admin_login_failed" in actions


def test_logout_invalidates_session(admin_client):
    assert admin_client.get("/api/admin/roster").status_code == 200
    assert admin_client.post("/api/admin/logout").status_code == 200
    assert admin_client.get("/api/admin/roster").status_code == 401


def test_student_can_only_read_own_record(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    checkin(make_client(appmod), current_token(admin_client, session_id), "K4001")

    student = make_client(appmod)
    assert student.get("/api/student/me").status_code == 401
    assert student.post(
        "/api/student/login", json={"student_id": "K4001", "pin": "sai"}
    ).status_code == 401
    assert student.post(
        "/api/student/login", json={"student_id": "K4001", "pin": "123456"}
    ).status_code == 200

    body = student.get("/api/student/me").json()
    assert body["student"]["student_id"] == "K4001"
    # không có tham số nào để đọc hồ sơ người khác, và API admin vẫn khoá
    assert student.get("/api/admin/roster").status_code == 401


def test_student_session_cookie_does_not_grant_admin(appmod, seeded):
    student = make_client(appmod)
    student.post("/api/student/login", json={"student_id": "K4001", "pin": "123456"})
    assert student.get("/api/admin/briefing").status_code == 401


# ==========================================================================
# Giới hạn tần suất
# ==========================================================================
def test_checkin_rate_limit_per_student(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    token = current_token(admin_client, session_id)
    device = make_client(appmod)

    codes = [checkin(device, token, "K4002").status_code for _ in range(8)]
    assert 429 in codes, codes


def test_login_rate_limit(appmod, seeded):
    client = make_client(appmod)
    codes = [
        client.post("/api/admin/login", json={"username": "labcoach", "password": "sai"}).status_code
        for _ in range(14)
    ]
    assert 429 in codes, codes


# ==========================================================================
# Tầng HTTP
# ==========================================================================
def test_security_headers_present(client, seeded):
    res = client.get("/")
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["referrer-policy"] == "no-referrer"
    csp = res.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_no_api_docs_exposed(client, seeded):
    for path in ["/docs", "/redoc", "/openapi.json"]:
        assert client.get(path).status_code == 404, path


def test_csp_forbids_unsafe_inline(client, seeded):
    csp = client.get("/").headers["content-security-policy"]
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp


@pytest.mark.parametrize("template", sorted(p.name for p in (CODEBASE / "templates").glob("*.html")))
def test_no_inline_script_or_style_in_templates(template):
    """CSP là `script-src 'self'` + `style-src 'self'`, nên markup không được có
    `<script>` inline hay thuộc tính `style=` - trình duyệt chặn thẳng.

    Test này tồn tại vì đã mắc đúng lỗi đó: trang đăng nhập Labcoach dùng script
    inline, và trình duyệt chặn nó nên nút "Đăng nhập" không làm gì cả. Cả bộ test
    HTTP lẫn smoke test đều không thấy - TestClient không thực thi CSP, còn smoke
    test gọi API trực tiếp nên không đi qua trình duyệt. Chỉ mở app bằng Chromium
    thật mới lộ ra.
    """
    html = (CODEBASE / "templates" / template).read_text(encoding="utf-8")
    inline_scripts = re.findall(r"<script(?![^>]*\ssrc=)[^>]*>", html)
    assert not inline_scripts, f"{template} có <script> inline: {inline_scripts}"
    assert 'style="' not in html, f"{template} có thuộc tính style= inline"


@pytest.mark.parametrize("script", sorted(p.name for p in (CODEBASE / "static").glob("*.js")))
def test_no_inline_style_injected_by_js(script):
    """JS dựng HTML bằng innerHTML: `style="…"` trong chuỗi đó cũng thành thuộc
    tính style trong markup, nên cũng bị CSP chặn.

    Chỉ cấm đúng thứ CSP cấm. Gán qua CSSOM (`el.style.width = …`) thì **không**
    bị chặn - `style-src` quản markup (`style=` và thẻ `<style>`), không quản
    CSSOM. Đã kiểm bằng Chromium thật: thanh đếm ngược ở máy chiếu đặt
    `style.width` mỗi 200ms và không sinh lỗi CSP nào. Đó cũng là cách đúng cho
    một giá trị phần trăm liên tục - lớp CSS không biểu diễn được.
    """
    source = (CODEBASE / "static" / script).read_text(encoding="utf-8")
    assert 'style="' not in source, f"{script} chèn thuộc tính style= vào markup"


@pytest.mark.parametrize(
    "payload",
    [
        "K4001'; DROP TABLE attendance;--",
        "' OR '1'='1",
        "K4001 UNION SELECT * FROM admins",
    ],
)
def test_sql_injection_in_student_id_is_harmless(appmod, seeded, admin_client, conn, payload):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    res = checkin(make_client(appmod), current_token(admin_client, session_id), payload)
    assert res.status_code in (404, 422)
    # bảng vẫn còn, không có bản ghi rác
    assert conn.execute("SELECT COUNT(*) AS n FROM attendance").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM students").fetchone()["n"] == 5


def test_oversized_input_is_rejected(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    token = current_token(admin_client, session_id)
    res = make_client(appmod).post(
        "/api/checkin",
        json={"token": token, "student_id": "K" * 5000, "fingerprint": "f" * 50000},
    )
    assert res.status_code == 422


def test_manual_checkin_is_marked_as_manual(appmod, seeded, admin_client, conn):
    """Bản ghi tay phải phân biệt được với bản ghi tự động."""
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    res = admin_client.post(
        "/api/admin/manual-checkin",
        json={
            "session_id": session_id,
            "student_id": "K4001",
            "call_index": 1,
            "status": "present",
            "reason": "wifi_down",
            "note": "wifi sập lúc 9h",
        },
    )
    assert res.status_code == 200
    row = conn.execute(
        """SELECT source, token_valid, device_hash, manual_reason, manual_by
           FROM attendance WHERE student_id='K4001'"""
    ).fetchone()
    assert row["source"] == "manual"
    assert row["token_valid"] == 0
    assert row["device_hash"] is None
    assert "WiFi lớp sập" in row["manual_reason"]
    assert "wifi sập lúc 9h" in row["manual_reason"]
    assert row["manual_by"] == "labcoach"


def test_manual_checkin_rescues_student_whose_device_is_blocked(appmod, seeded, admin_client, conn):
    """Kịch bản thật: mất điện thoại giữa buổi, thiết bị cũ vẫn đang buộc.

    Không có đường này thì một cái điện thoại hỏng thành một buổi vắng oan, và §6
    xếp "học viên bị đánh dấu at_risk oan" là rủi ro phải xử lý.
    """
    first = create_session(conn, TODAY)
    open_session(admin_client, first)
    old_phone = make_client(appmod)
    checkin(old_phone, current_token(admin_client, first), "K4001", "fp-may-cu")
    admin_client.post(f"/api/admin/sessions/{first}/close")

    today_session = create_session(conn, "2026-07-31")
    open_session(admin_client, today_session)

    # máy mượn của bạn -> bị chặn cả hai vế
    borrowed = make_client(appmod)
    assert checkin(
        borrowed, current_token(admin_client, today_session), "K4001", "fp-may-ban"
    ).status_code == 409

    # Labcoach điểm danh tay, học viên không bị vắng oan
    res = admin_client.post(
        "/api/admin/manual-checkin",
        json={
            "session_id": today_session,
            "student_id": "K4001",
            "call_index": 1,
            "status": "present",
            "reason": "lost_phone",
            "note": "để máy ở nhà",
        },
    )
    assert res.status_code == 200
    row = conn.execute(
        "SELECT status, source, manual_reason FROM attendance WHERE student_id='K4001' AND session_id=?",
        (today_session,),
    ).fetchone()
    assert row["status"] == "present"
    assert row["source"] == "manual"
    assert "Mất / không mang điện thoại" in row["manual_reason"]


def test_manual_absent_is_recordable_for_both_calls(appmod, seeded, admin_client, conn):
    """Đánh vắng tay được cho cả lượt 1 và lượt 2.

    Thiếu lượt 2 thì Labcoach chỉ ghi được "có mặt", không ghi được "đã kiểm và
    người này không còn ở lớp" - mà đó chính là bằng chứng của rule EARLY_DEPARTURE.
    """
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)

    for call_index, status in ((1, "absent"), (2, "absent")):
        res = admin_client.post(
            "/api/admin/manual-checkin",
            json={
                "session_id": session_id, "student_id": "K4001",
                "call_index": call_index, "status": status, "reason": "lost_phone",
            },
        )
        assert res.status_code == 200, res.text

    rows = conn.execute(
        """SELECT call_index, status, source FROM attendance
           WHERE student_id='K4001' AND session_id=? ORDER BY call_index""",
        (session_id,),
    ).fetchall()
    assert [(r["call_index"], r["status"], r["source"]) for r in rows] == [
        (1, "absent", "manual"), (2, "absent", "manual")
    ]


def test_explicit_manual_absent_at_call_two_still_raises_early_departure(appmod, seeded, admin_client, conn):
    """Có mặt lượt 1, Labcoach đánh vắng tay lượt 2 -> vẫn là EARLY_DEPARTURE.

    Bản ghi 'absent' tường minh phải tương đương với việc không có bản ghi nào:
    cả hai đều nghĩa là người đó không còn ở lớp giữa buổi.
    """
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    device = make_client(appmod)
    assert checkin(device, current_token(admin_client, session_id), "K4001").status_code == 200

    admin_client.post(f"/api/admin/sessions/{session_id}/second-call")
    res = admin_client.post(
        "/api/admin/manual-checkin",
        json={
            "session_id": session_id, "student_id": "K4001",
            "call_index": 2, "status": "absent", "reason": "other", "note": "đã gọi tên, không có",
        },
    )
    assert res.status_code == 200

    closed = admin_client.post(f"/api/admin/sessions/{session_id}/close")
    assert closed.json()["early_departure_flags"] == ["K4001"]
    assert "EARLY_DEPARTURE" in flags_for(conn, "K4001")


def test_live_view_exposes_manual_marker_for_both_calls(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    for call_index in (1, 2):
        admin_client.post(
            "/api/admin/manual-checkin",
            json={
                "session_id": session_id, "student_id": "K4001",
                "call_index": call_index, "status": "present", "reason": "broken_phone",
            },
        )

    row = next(
        r for r in admin_client.get(f"/api/admin/sessions/{session_id}/live").json()["rows"]
        if r["student_id"] == "K4001"
    )
    assert row["call1_source"] == "manual" and row["call2_source"] == "manual"
    assert "Điện thoại hỏng" in row["call1_reason"]
    assert "Điện thoại hỏng" in row["call2_reason"]


def test_manual_checkin_rejects_unknown_reason(admin_client, conn):
    session_id = create_session(conn, TODAY)
    res = admin_client.post(
        "/api/admin/manual-checkin",
        json={
            "session_id": session_id,
            "student_id": "K4001",
            "call_index": 1,
            "status": "present",
            "reason": "ly-do-bia-ra",
        },
    )
    assert res.status_code == 422


def test_manual_checkin_can_correct_an_earlier_record(appmod, seeded, admin_client, conn):
    """Nhập tay hai lần thì lần sau sửa lần trước, không tạo bản ghi trùng."""
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    for status in ("absent", "present"):
        assert admin_client.post(
            "/api/admin/manual-checkin",
            json={
                "session_id": session_id, "student_id": "K4001", "call_index": 1,
                "status": status, "reason": "broken_phone",
            },
        ).status_code == 200

    rows = conn.execute(
        "SELECT status FROM attendance WHERE student_id='K4001' AND session_id=?", (session_id,)
    ).fetchall()
    assert [r["status"] for r in rows] == ["present"]


def test_manual_reasons_list_is_available_to_admin(admin_client, client):
    body = admin_client.get("/api/admin/manual-reasons").json()
    codes = {r["code"] for r in body["reasons"]}
    assert {"lost_phone", "broken_phone", "device_locked", "wifi_down"} <= codes
    assert client.get("/api/admin/manual-reasons").status_code == 401


def test_manual_checkin_requires_admin(client, seeded, conn):
    session_id = create_session(conn, TODAY)
    res = client.post(
        "/api/admin/manual-checkin",
        json={"session_id": session_id, "student_id": "K4001", "call_index": 1, "status": "present"},
    )
    assert res.status_code == 401


def test_flags_are_grouped_by_rule_and_student(appmod, seeded, admin_client, conn):
    """Flag giống nhau của cùng một học viên gộp thành một dòng kèm số lần."""
    sessions = [create_session(conn, f"2026-07-{day:02d}") for day in (20, 21, 22)]
    for session_id in sessions:
        rules.raise_flag(conn, None, session_id, "K4001", "EARLY_DEPARTURE", "về sớm")
    rules.raise_flag(conn, None, sessions[0], "K4002", "EARLY_DEPARTURE", "về sớm")
    conn.commit()

    body = admin_client.get("/api/admin/anomalies/grouped").json()
    assert body["totals"]["flags"] == 4
    assert body["totals"]["groups"] == 2  # K4001 gộp 3 flag, K4002 một flag
    assert body["totals"]["by_rule"]["EARLY_DEPARTURE"] == 4

    k4001 = next(g for g in body["groups"] if g["student_id"] == "K4001")
    assert k4001["occurrences"] == 3
    assert len(k4001["dates"]) == 3
    assert k4001["first_at"] <= k4001["last_at"]
    assert k4001["severity"] == "high"

    # nhóm nặng hơn / nhiều lần hơn lên trước
    assert body["groups"][0]["occurrences"] >= body["groups"][-1]["occurrences"]


def test_resolving_a_group_closes_every_flag_in_it(appmod, seeded, admin_client, conn):
    """Bắt bấm 17 lần cho 17 flag giống nhau thì thực tế là không ai bấm lần nào."""
    sessions = [create_session(conn, f"2026-07-{day:02d}") for day in (20, 21, 22)]
    for session_id in sessions:
        rules.raise_flag(conn, None, session_id, "K4001", "EARLY_DEPARTURE", "về sớm")
    rules.raise_flag(conn, None, sessions[0], "K4002", "EARLY_DEPARTURE", "về sớm")
    conn.commit()

    res = admin_client.post(
        "/api/admin/anomalies/resolve-group",
        json={"rule_code": "EARLY_DEPARTURE", "student_id": "K4001", "note": "đã hỏi học viên"},
    )
    assert res.status_code == 200
    assert res.json()["resolved"] == 3

    rows = conn.execute(
        "SELECT student_id, resolved, resolved_by FROM anomaly_flags ORDER BY student_id"
    ).fetchall()
    assert [r["resolved"] for r in rows if r["student_id"] == "K4001"] == [1, 1, 1]
    assert [r["resolved"] for r in rows if r["student_id"] == "K4002"] == [0]  # nhóm khác không bị đóng lây
    assert all(r["resolved_by"] == "labcoach" for r in rows if r["resolved"])

    actions = {r["action"] for r in conn.execute("SELECT action FROM audit_log").fetchall()}
    assert "resolve_flag_group" in actions


def test_resolving_an_empty_group_is_404(admin_client):
    assert admin_client.post(
        "/api/admin/anomalies/resolve-group",
        json={"rule_code": "EARLY_DEPARTURE", "student_id": "K4001", "note": ""},
    ).status_code == 404


def test_resolve_group_rejects_unknown_rule(admin_client):
    assert admin_client.post(
        "/api/admin/anomalies/resolve-group",
        json={"rule_code": "RULE_BIA_RA", "student_id": "K4001", "note": ""},
    ).status_code == 422


def test_grouped_flags_require_admin(client, seeded):
    assert client.get("/api/admin/anomalies/grouped").status_code == 401
    assert client.post(
        "/api/admin/anomalies/resolve-group",
        json={"rule_code": "EARLY_DEPARTURE", "student_id": "K4001", "note": ""},
    ).status_code == 401


def test_checkin_response_carries_identity_for_confirmation(appmod, seeded, admin_client, conn):
    """Học viên phải tự soát được "đúng người chưa" ngay tại chỗ.

    Gõ sai một số trong mã học viên là ghi nhận vào hồ sơ người khác, mà bản ghi
    chuyên cần thì có thể bị khiếu nại.
    """
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    res = checkin(make_client(appmod), current_token(admin_client, session_id), "K4001")
    assert res.status_code == 200

    body = res.json()
    for field in (
        "student_id", "student_name", "status", "call_index",
        "session_date", "session_start_time", "checkin_ts", "attended_sessions",
    ):
        assert field in body, f"thiếu {field} - học viên không soát được"
    assert body["student_id"] == "K4001"
    assert body["student_name"]
    assert body["attended_sessions"] >= 1


# ==========================================================================
# Quản lý học viên
# ==========================================================================
def test_create_student_returns_pin_once_and_stores_only_hash(admin_client, conn):
    res = admin_client.post(
        "/api/admin/students",
        json={"student_id": "k4099", "name": "  Nguyễn Văn Mới  ", "email": "moi@example.invalid"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["student_id"] == "K4099"        # mã luôn viết hoa
    assert body["name"] == "Nguyễn Văn Mới"     # tên đã cắt khoảng trắng
    assert len(body["pin"]) == 6 and body["pin"].isdigit()

    row = conn.execute("SELECT * FROM students WHERE student_id='K4099'").fetchone()
    assert row["active"] == 1
    assert row["email"] == "moi@example.invalid"
    # chỉ lưu bản băm: PIN thô không xuất hiện ở bất cứ cột nào
    assert body["pin"] not in (row["pin_hash"], row["pin_salt"])
    assert len(row["pin_hash"]) == 64


def test_created_student_can_log_in_with_returned_pin(appmod, seeded, admin_client):
    pin = admin_client.post(
        "/api/admin/students", json={"student_id": "K4099", "name": "Học viên mới"}
    ).json()["pin"]

    student = make_client(appmod)
    assert student.post(
        "/api/student/login", json={"student_id": "K4099", "pin": pin}
    ).status_code == 200


def test_created_student_can_check_in(appmod, seeded, admin_client, conn):
    admin_client.post("/api/admin/students", json={"student_id": "K4099", "name": "Học viên mới"})
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    res = checkin(make_client(appmod), current_token(admin_client, session_id), "K4099")
    assert res.status_code == 200, res.text
    assert res.json()["student_name"] == "Học viên mới"


@pytest.mark.parametrize("bad_id", ["", " ", "a", "mã có dấu", "K4001 K4002", "x" * 40, "-abc"])
def test_invalid_student_id_is_rejected(admin_client, bad_id):
    res = admin_client.post("/api/admin/students", json={"student_id": bad_id, "name": "Tên"})
    assert res.status_code == 422, f"{bad_id!r} -> {res.status_code}"


def test_duplicate_student_id_is_rejected(admin_client):
    assert admin_client.post(
        "/api/admin/students", json={"student_id": "K4001", "name": "Trùng mã"}
    ).status_code == 409


def test_empty_name_is_rejected(admin_client):
    assert admin_client.post(
        "/api/admin/students", json={"student_id": "K4099", "name": "   "}
    ).status_code == 422


def test_custom_pin_must_be_digits(admin_client):
    assert admin_client.post(
        "/api/admin/students", json={"student_id": "K4099", "name": "Tên", "pin": "abcd"}
    ).status_code == 422


def test_update_student_changes_name_but_not_id(admin_client, conn):
    res = admin_client.post(
        "/api/admin/students/K4001/update",
        json={"name": "Tên Đã Sửa", "email": "moi@example.invalid"},
    )
    assert res.status_code == 200
    row = conn.execute("SELECT name, email FROM students WHERE student_id='K4001'").fetchone()
    assert row["name"] == "Tên Đã Sửa"
    assert row["email"] == "moi@example.invalid"

    detail = conn.execute(
        "SELECT detail FROM audit_log WHERE action='update_student'"
    ).fetchone()["detail"]
    assert "->" in detail  # ghi lại cả giá trị cũ, để đối chiếu khi khiếu nại


def test_deactivated_student_cannot_check_in_but_keeps_history(appmod, seeded, admin_client, conn):
    """Ngưng theo dõi, KHÔNG xoá: lịch sử chuyên cần phải giữ được để khiếu nại."""
    first = create_session(conn, TODAY)
    open_session(admin_client, first)
    checkin(make_client(appmod), current_token(admin_client, first), "K4001")
    admin_client.post(f"/api/admin/sessions/{first}/close")

    assert admin_client.post(
        "/api/admin/students/K4001/set-active", json={"active": False}
    ).status_code == 200

    second = create_session(conn, "2026-07-31")
    open_session(admin_client, second)
    res = checkin(make_client(appmod), current_token(admin_client, second), "K4001")
    assert res.status_code == 404  # không còn trong lớp

    # nhưng bản ghi cũ còn nguyên
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM attendance WHERE student_id='K4001'"
    ).fetchone()["n"] == 1
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM students WHERE student_id='K4001'"
    ).fetchone()["n"] == 1


def test_reactivating_student_restores_checkin(appmod, seeded, admin_client, conn):
    admin_client.post("/api/admin/students/K4001/set-active", json={"active": False})
    admin_client.post("/api/admin/students/K4001/set-active", json={"active": True})
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    assert checkin(
        make_client(appmod), current_token(admin_client, session_id), "K4001"
    ).status_code == 200


def test_reset_pin_invalidates_old_pin_and_session(appmod, seeded, admin_client):
    student = make_client(appmod)
    assert student.post(
        "/api/student/login", json={"student_id": "K4001", "pin": "123456"}
    ).status_code == 200
    assert student.get("/api/student/me").status_code == 200

    new = admin_client.post("/api/admin/students/K4001/reset-pin").json()["pin"]
    assert new != "123456"

    # phiên đang mở bị huỷ, PIN cũ hết tác dụng, PIN mới dùng được
    assert student.get("/api/student/me").status_code == 401
    assert student.post(
        "/api/student/login", json={"student_id": "K4001", "pin": "123456"}
    ).status_code == 401
    assert student.post(
        "/api/student/login", json={"student_id": "K4001", "pin": new}
    ).status_code == 200


def test_import_csv_creates_every_row(admin_client, conn):
    res = admin_client.post(
        "/api/admin/students/import",
        json={"csv_text": (
            "student_id,name,email\n"
            "# dòng ghi chú bị bỏ qua\n"
            "K4090,Nguyễn Văn A,a@example.invalid\n"
            "K4091,Trần Thị B\n"
            "\n"
            "k4092,Lê Văn C,c@example.invalid\n"
        )},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True and body["imported"] == 3
    assert {s["student_id"] for s in body["students"]} == {"K4090", "K4091", "K4092"}
    assert all(len(s["pin"]) == 6 for s in body["students"])

    assert conn.execute(
        "SELECT COUNT(*) AS n FROM students WHERE student_id LIKE 'K409%'"
    ).fetchone()["n"] == 3
    assert conn.execute(
        "SELECT email FROM students WHERE student_id='K4091'"
    ).fetchone()["email"] is None


def test_import_is_all_or_nothing(admin_client, conn):
    """Một dòng lỗi là không ghi dòng nào - nhập nửa chừng thì lần chạy lại đụng trùng mã."""
    before = conn.execute("SELECT COUNT(*) AS n FROM students").fetchone()["n"]
    res = admin_client.post(
        "/api/admin/students/import",
        json={"csv_text": (
            "K4090,Hợp lệ\n"
            "mã sai,Không hợp lệ\n"
            "K4092,Cũng hợp lệ\n"
        )},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False and body["imported"] == 0
    assert len(body["errors"]) == 1
    assert body["errors"][0]["line"] == 2

    after = conn.execute("SELECT COUNT(*) AS n FROM students").fetchone()["n"]
    assert after == before, "không được ghi dòng nào khi còn lỗi"


def test_import_reports_duplicates_inside_file_and_against_db(admin_client):
    body = admin_client.post(
        "/api/admin/students/import",
        json={"csv_text": "K4090,A\nK4090,A lần hai\nK4001,Đã có trong lớp\n"},
    ).json()
    assert body["ok"] is False
    reasons = " ".join(e["error"] for e in body["errors"])
    assert "trùng mã" in reasons
    assert "đã có trong lớp" in reasons


def test_import_rejects_empty_input(admin_client):
    assert admin_client.post(
        "/api/admin/students/import", json={"csv_text": "# chỉ có ghi chú\n"}
    ).status_code == 422


def test_student_management_requires_admin_and_csrf(client, appmod, seeded):
    assert client.post(
        "/api/admin/students", json={"student_id": "K4099", "name": "x"}
    ).status_code == 401

    no_csrf = make_client(appmod)
    no_csrf.post("/api/admin/login", json={"username": "labcoach", "password": "mat-khau-test"})
    for path, body in [
        ("/api/admin/students", {"student_id": "K4099", "name": "x"}),
        ("/api/admin/students/K4001/update", {"name": "x"}),
        ("/api/admin/students/K4001/set-active", {"active": False}),
        ("/api/admin/students/K4001/reset-pin", None),
        ("/api/admin/students/import", {"csv_text": "K4099,x"}),
    ]:
        res = no_csrf.post(path, json=body) if body else no_csrf.post(path)
        assert res.status_code == 403, path


def test_student_management_on_unknown_student_is_404(admin_client):
    assert admin_client.post(
        "/api/admin/students/K9999/update", json={"name": "x"}
    ).status_code == 404
    assert admin_client.post(
        "/api/admin/students/K9999/set-active", json={"active": False}
    ).status_code == 404
    assert admin_client.post("/api/admin/students/K9999/reset-pin").status_code == 404


def test_every_state_change_is_audited(appmod, seeded, admin_client, conn):
    session_id = create_session(conn, TODAY)
    open_session(admin_client, session_id)
    token = current_token(admin_client, session_id)
    checkin(make_client(appmod), token, "K4001")
    admin_client.post(f"/api/admin/sessions/{session_id}/rotate-token")
    admin_client.post(f"/api/admin/sessions/{session_id}/close")

    actions = {r["action"] for r in conn.execute("SELECT action FROM audit_log").fetchall()}
    assert {"admin_login", "open_session", "checkin", "rotate_token", "close_session"} <= actions
