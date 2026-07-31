"""Ranh giới quyền của tầng mô hình ngôn ngữ (§4.2).

Không test nào ở đây gọi Ollama. Cái được kiểm là **ranh giới**, không phải chất
lượng câu chữ: mô hình có sinh ra chuỗi gì đi nữa thì cũng không được ghi vào
database. Chất lượng đầu ra đo ở `eval/`, nơi có golden set và người chấm.

Cách nghĩ: coi mọi thứ mô hình trả về là chuỗi do người lạ gửi tới.
"""
from __future__ import annotations

import inspect
import sqlite3

import llm
import pytest
from conftest import CODEBASE, create_session, open_session  # noqa: F401

TODAY = "2026-07-30"


# ==========================================================================
# Ranh giới ở tầng chữ ký hàm - §4.2 nói ranh giới này giữ ở code, không phải
# ở quy ước. Nếu ai đó thêm `conn` vào một hàm trong llm.py, test này gãy.
# ==========================================================================
def test_no_llm_function_accepts_a_database_connection():
    public = [
        (name, fn) for name, fn in inspect.getmembers(llm, inspect.isfunction)
        if not name.startswith("_") and fn.__module__ == "llm"
    ]
    assert public, "không tìm thấy hàm public nào trong llm.py"
    for name, fn in public:
        params = set(inspect.signature(fn).parameters)
        assert "conn" not in params, f"llm.{name}() nhận conn - phá ranh giới §4.2"
        assert not (params & {"db", "connection", "cursor"}), f"llm.{name}() nhận tay cầm database"


def test_llm_module_never_imports_db_layer():
    """Không import `db` thì không có đường nào mở connection từ trong llm.py."""
    source = (CODEBASE / "llm.py").read_text(encoding="utf-8")
    assert "import db" not in source
    assert "from db import" not in source
    assert "sqlite3" not in source


# ==========================================================================
# Cửa kiểm tra SQL do mô hình sinh
# ==========================================================================
@pytest.fixture()
def check(appmod):
    return appmod._check_generated_sql


WRITES = [
    "DELETE FROM attendance",
    "UPDATE students SET device_hash = NULL",
    "INSERT INTO attendance (student_id) VALUES ('K4001')",
    "DROP TABLE anomaly_flags",
    "ALTER TABLE students ADD COLUMN x TEXT",
    "CREATE TABLE evil (x TEXT)",
    "ATTACH DATABASE '/etc/passwd' AS leak",
    "PRAGMA table_info(admin_users)",
    "VACUUM",
]


@pytest.mark.parametrize("sql", WRITES)
def test_write_statements_are_rejected(check, sql):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        check(sql)
    assert exc.value.status_code == 422


def test_second_statement_smuggled_after_a_select_is_rejected(check):
    """Đường tấn công thật: mô hình bị dụ sinh ra hai câu, câu sau mới là câu ghi."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        check("SELECT 1; DROP TABLE students")


def test_plain_select_passes_and_is_normalised(check):
    assert check("  SELECT name FROM students LIMIT 5;  ") == "SELECT name FROM students LIMIT 5"


def test_cte_select_passes(check):
    sql = "WITH x AS (SELECT student_id FROM attendance) SELECT * FROM x LIMIT 10"
    assert check(sql) == sql


def test_empty_generation_is_rejected(check):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        check("   ")


# ==========================================================================
# Lớp phòng vệ cuối: kết nối read-only của chính SQLite.
# Kể cả khi cửa kiểm tra ở trên bị lọt, tầng driver vẫn phải từ chối phép ghi.
# ==========================================================================
def test_readonly_connection_refuses_writes_even_if_the_guard_is_bypassed(seeded, appmod):
    ro = sqlite3.connect(f"file:{appmod.DB_PATH}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("DELETE FROM attendance")
        # đọc thì vẫn phải chạy được, nếu không thì tính năng hỏi dữ liệu vô dụng
        assert ro.execute("SELECT COUNT(*) FROM students").fetchone()[0] > 0
    finally:
        ro.close()


# ==========================================================================
# Hợp đồng §6: tầng mô hình tắt = mất phần diễn giải, không mất trang
# ==========================================================================
def test_every_llm_entrypoint_returns_none_when_disabled():
    cfg = {"llm": {"enabled": False}, "checkin": {"late_after_min": 10}}
    trace = {"level": "watch", "counts": {"absent": 2, "late": 0, "sessions_considered": 5}}
    assert llm.write_diagnosis(trace, cfg) is None
    assert llm.draft_message(trace, "Nguyễn Văn A", cfg) is None
    assert llm.ask_sql("ai vắng nhiều nhất", cfg) is None
    assert llm.parse_leave_request("em xin nghỉ mai", cfg, today="2026-07-31") is None
    assert llm.health(cfg) == {"enabled": False, "reachable": False,
                               "model_ready": False, "model": None}


def test_risk_detail_still_works_with_the_model_off(seeded, admin_client):
    """Đường phải luôn sống: mức rủi ro và rule_trace hiện đủ khi không có mô hình."""
    res = admin_client.get("/api/admin/risk/K4001")
    assert res.status_code == 200
    body = res.json()
    assert body["llm_enabled"] is False
    assert body["risk_level"] in ("ok", "watch", "at_risk")
    assert "signals" in body["rule_trace"]


def test_llm_endpoints_answer_503_when_disabled(seeded, admin_client):
    """503 chứ không phải 500: tắt mô hình là một trạng thái hợp lệ, không phải lỗi."""
    for path, body in [
        ("/api/admin/ask", {"question": "ai vắng nhiều nhất"}),
        ("/api/admin/parse-leave", {"text": "em xin nghỉ ngày mai ạ"}),
        ("/api/admin/risk/K4001/explain", None),
    ]:
        res = admin_client.post(path, json=body) if body else admin_client.post(path)
        assert res.status_code == 503, path


# ==========================================================================
# Bóc đơn xin phép: chuẩn hoá đầu ra méo của mô hình
# ==========================================================================
def test_parse_leave_normalises_a_malformed_model_reply(monkeypatch):
    """Model trả category lạ và dates là chuỗi đơn - phải chuẩn hoá, không nổ."""
    cfg = {"llm": {"enabled": True}}
    monkeypatch.setattr(
        llm, "_generate",
        lambda *a, **k: '{"student_id":"k4012","dates":"2026-08-03",'
                        '"category":"tự nghĩ ra","reason_text":"ốm","missing":[]}',
    )
    out = llm.parse_leave_request("...", cfg, today="2026-08-01")
    assert out["dates"] == ["2026-08-03"]
    assert out["category"] == "khác"


def test_parse_leave_drops_dates_that_are_not_real_dates(monkeypatch):
    cfg = {"llm": {"enabled": True}}
    monkeypatch.setattr(
        llm, "_generate",
        lambda *a, **k: '{"dates":["mai","2026-08-03","thứ ba"],"category":"ốm"}',
    )
    assert llm.parse_leave_request("...", cfg, today="2026-08-01")["dates"] == ["2026-08-03"]


def test_parse_leave_returns_none_when_model_replies_with_prose(monkeypatch):
    cfg = {"llm": {"enabled": True}}
    monkeypatch.setattr(llm, "_generate", lambda *a, **k: "Chào bạn, đơn này xin nghỉ ngày mai.")
    assert llm.parse_leave_request("...", cfg, today="2026-08-01") is None


# ==========================================================================
# Bảng dữ kiện đưa cho mô hình không được tự mâu thuẫn.
# Chính mâu thuẫn "0 buổi đi muộn" vs "muộn 8'" đã làm mô hình bịa ra hai lần
# đi muộn không có trong log - vi phạm chỉ tiêu §7.2 "không bịa thông tin".
# ==========================================================================
def test_fact_sheet_marks_sub_threshold_lateness_as_not_counted():
    trace = {
        "level": "ok",
        "as_of": "2026-07-30",
        "counts": {"absent": 0, "late": 0, "sessions_considered": 2},
        "signals": [],
        "history": [
            {"date": "2026-07-24", "status": "present", "late_min": 8},
            {"date": "2026-07-29", "status": "present", "late_min": 0},
        ],
    }
    facts = llm._facts(trace, late_after_min=10)
    assert "dưới ngưỡng nên không tính là đi muộn" in facts
    assert "từ 10 phút trở lên" in facts


def test_fact_sheet_never_leaks_raw_rule_codes():
    """Câu chữ đưa cho mô hình phải là tiếng Việt: mã rule lọt vào đây thì nó lọt
    thẳng ra câu chẩn đoán Labcoach đọc."""
    trace = {
        "level": "at_risk",
        "as_of": "2026-07-30",
        "counts": {"absent": 1, "late": 0, "sessions_considered": 5},
        "early_departure_flags": 2,
        "signals": [{"code": "EARLY_DEPARTURE_REPEATED", "value": 2, "threshold": 2,
                     "note": "Vắng ở lượt điểm danh thứ hai 2 lần", "tier": "at_risk"}],
        "history": [],
    }
    facts = llm._facts(trace, late_after_min=10)
    for code in ("EARLY_DEPARTURE", "DEVICE_REUSE", "IP_RATE_SPIKE", "TOKEN_GRACE_USED"):
        assert code not in facts


# ==========================================================================
# Đối chiếu ngày bằng code. Model 4B khớp chữ SỐ: đơn viết "thứ 3" thì nó trả về
# ngày mùng 3 của tháng, lệch một ngày so với thứ Ba thật. Bảng quy đổi tính sẵn
# trong prompt cũng không chữa được, nên phép kiểm phải nằm ở code.
# ==========================================================================
def test_weekday_mismatch_is_reported(monkeypatch):
    cfg = {"llm": {"enabled": True}}
    # 2026-08-03 là thứ Hai, 2026-08-05 là thứ Tư
    monkeypatch.setattr(
        llm, "_generate",
        lambda *a, **k: '{"dates":["2026-08-03","2026-08-05"],"category":"ốm",'
                        '"reason_text":"sốt","student_id":null}',
    )
    out = llm.parse_leave_request(
        "em xin nghỉ thứ 3 với thứ 5 tuần sau em bị sốt", cfg, today="2026-07-31")
    assert len(out["date_warnings"]) == 2
    assert "thứ 2" in out["date_warnings"][0]


def test_matching_weekday_raises_no_warning(monkeypatch):
    cfg = {"llm": {"enabled": True}}
    monkeypatch.setattr(  # 2026-08-03 đúng là thứ Hai
        llm, "_generate",
        lambda *a, **k: '{"dates":["2026-08-03"],"category":"việc gia đình",'
                        '"reason_text":"đám giỗ"}',
    )
    out = llm.parse_leave_request("em xin nghỉ thứ 2 tuần tới", cfg, today="2026-07-31")
    assert out["date_warnings"] == []


def test_no_weekday_in_text_means_nothing_to_check(monkeypatch):
    cfg = {"llm": {"enabled": True}}
    monkeypatch.setattr(
        llm, "_generate",
        lambda *a, **k: '{"dates":["2026-08-01"],"category":"ốm","reason_text":"ốm"}')
    out = llm.parse_leave_request("mai em xin nghỉ ạ", cfg, today="2026-07-31")
    assert out["date_warnings"] == []


def test_date_table_is_short_and_correct():
    """Bảng dài thì model 4B coi cả bảng là câu trả lời - đã từng trả về 15 ngày
    cho một đơn xin nghỉ hai buổi."""
    table = llm._date_table("2026-07-31")   # thứ Sáu
    assert table.count("\n") <= 12, "bảng quá dài, model sẽ chép cả bảng"
    assert "mai = 2026-08-01" in table
    assert "thứ 3 = thứ Ba kế tiếp = 2026-08-04" in table
    assert "thứ 5 = thứ Năm kế tiếp = 2026-08-06" in table


# ==========================================================================
# Chi tiết một flag + diễn giải bằng mô hình
# ==========================================================================
# Chuỗi dài đúng kiểu bị cắt bằng "…" trong bảng - lý do tồn tại của endpoint này.
LONG_DETAIL = (
    "Chặn check-in: thiết bị đã buộc cho K4002, học viên này dùng máy của bạn cùng "
    "lớp để điểm danh nên hệ thống từ chối ghi và giữ lại dấu vết cho Labcoach xem lại"
)


@pytest.fixture()
def flag_id(seeded, conn):
    """Một flag thật, gắn vào một buổi thật, với detail đủ dài để bị cắt."""
    import rules
    session_id = create_session(conn, TODAY)
    rules.raise_flag(conn, None, session_id, "K4001", "DEVICE_REUSE", LONG_DETAIL)
    conn.commit()
    row = conn.execute(
        "SELECT id FROM anomaly_flags WHERE rule_code = 'DEVICE_REUSE' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["id"]


def test_literal_anomaly_routes_win_over_the_id_route(seeded, admin_client, conn):
    """`/anomalies/grouped` phải vẫn là endpoint gộp, không bị đọc thành flag_id.

    FastAPI khớp route theo thứ tự khai báo. Ai đó chuyển `{flag_id}` lên trên là
    `grouped` và `resolve-group` chết ngay, mà triệu chứng chỉ là 422 khó hiểu.
    """
    assert admin_client.get("/api/admin/anomalies/grouped").status_code == 200
    res = admin_client.post("/api/admin/anomalies/resolve-group",
                            json={"rule_code": "EARLY_DEPARTURE", "student_id": "K4001", "note": ""})
    assert res.status_code in (200, 404)   # 404 = không còn flag nào trong nhóm, vẫn là route đúng


def test_flag_detail_returns_the_full_untruncated_text(flag_id, admin_client, conn):
    """Lý do tồn tại của endpoint này: cột trong bảng bị cắt bằng "…"."""
    res = admin_client.get(f"/api/admin/anomalies/{flag_id}")
    assert res.status_code == 200, res.text
    body = res.json()
    stored = conn.execute("SELECT detail FROM anomaly_flags WHERE id = ?", (flag_id,)).fetchone()
    assert body["flag"]["detail"] == stored["detail"] == LONG_DETAIL
    assert "…" not in body["flag"]["detail"]
    assert body["flag"]["label"]          # nhãn tiếng Việt đầy đủ
    assert "student_other_flags" in body
    assert "others_same_session" in body


def test_flag_detail_works_with_the_model_off(flag_id, admin_client, conn):
    """Phần dữ kiện là deterministic - Ollama chết thì vẫn đọc được flag."""
    body = admin_client.get(f"/api/admin/anomalies/{flag_id}").json()
    assert body["llm_enabled"] is False
    assert body["flag"]["rule_code"]


def test_unknown_flag_id_is_404(seeded, admin_client):
    assert admin_client.get("/api/admin/anomalies/999999").status_code == 404


def test_flag_explain_is_503_when_model_is_off(flag_id, admin_client):
    res = admin_client.post(f"/api/admin/anomalies/{flag_id}/explain")
    assert res.status_code == 503


def test_explain_flag_prompt_forbids_concluding_fraud(monkeypatch):
    """Ranh giới quan trọng nhất của tính năng này.

    Một câu "học viên này gian lận" đọc rất thuyết phục, mà bằng chứng thì chỉ đủ
    để nói "hai người dùng chung một máy". Lệnh cấm phải nằm trong prompt, và test
    này giữ nó ở đó.
    """
    captured = {}
    monkeypatch.setattr(llm, "_generate",
                        lambda prompt, cfg, **k: captured.setdefault("p", prompt) and "x")
    ctx = {"flag": {"label": "Một thiết bị ghi nhận cho nhiều học viên",
                    "rule_code": "DEVICE_REUSE", "severity": "high",
                    "student_id": "K4001", "student_name": "A", "date": "2026-07-30",
                    "start_time": "09:00", "detail": "Chặn check-in", "resolved": 0}}
    llm.explain_flag(ctx, {"llm": {"enabled": True}})
    prompt = captured["p"]
    assert "KHÔNG kết luận có gian lận" in prompt
    assert "KHÔNG đề xuất kỷ luật" in prompt
    assert "nên đóng hay không" in prompt


def test_flag_facts_says_plainly_when_the_checkin_was_blocked(monkeypatch):
    """Không có bản ghi attendance nghĩa là lượt check-in bị CHẶN, không phải
    "có mặt bình thường". Nhầm chỗ này là mô hình kể sai hẳn câu chuyện."""
    ctx = {"flag": {"label": "x", "rule_code": "DEVICE_REUSE", "severity": "high",
                    "student_id": "K4001", "student_name": "A", "date": "2026-07-30",
                    "start_time": "09:00", "detail": "d", "resolved": 0},
           "attendance": None}
    facts = llm._flag_facts(ctx)
    assert "bị CHẶN" in facts
    assert "chưa được tính có mặt" in facts


# ==========================================================================
# Bóc đơn xin phép: tra mã học viên theo TÊN
#
# Đưa cả danh sách tên vào prompt thì mô hình tự tra tên -> mã, và với tên trùng
# hai người nó chọn bừa một người. Ghi chuyên cần cho nhầm anh em sinh đôi là
# đúng thứ hệ thống này sinh ra để tránh (§5.5), nên phép đối chiếu phải chạy
# bằng code KỂ CẢ khi mô hình đã đưa ra một mã.
# ==========================================================================
@pytest.fixture()
def twins(seeded, conn):
    """Hai học viên trùng tên hoàn toàn - đúng tình huống §5.5 mô tả."""
    from db import now_ms
    ts = now_ms()
    for sid in ("K4101", "K4102"):
        conn.execute(
            """INSERT INTO students (student_id, name, active, created_at)
               VALUES (?,?,1,?)""", (sid, "Trần Văn Sinh Đôi", ts))
    conn.commit()
    return ("K4101", "K4102")


def fake_model(monkeypatch, payload: str):
    """Giả lập một lượt trả lời của mô hình, không gọi Ollama.

    Phải bật cả `is_enabled`: toàn bộ test suite chạy với tầng mô hình TẮT (§7.4),
    nên endpoint sẽ trả 503 trước khi tới được phần đang muốn kiểm.
    """
    monkeypatch.setattr(llm, "is_enabled", lambda cfg: True)
    monkeypatch.setattr(llm, "_generate", lambda *a, **k: payload)


def test_name_alone_resolves_to_the_single_matching_student(
    seeded, admin_client, conn, monkeypatch
):
    fake_model(monkeypatch, '{"student_id":null,"student_name":"Nguyễn Văn A",'
                            '"dates":["2026-08-01"],"category":"ốm","reason_text":"sốt"}')
    conn.execute("UPDATE students SET name = 'Nguyễn Văn A' WHERE student_id = 'K4001'")
    conn.commit()
    body = admin_client.post("/api/admin/parse-leave",
                             json={"text": "Em Nguyễn Văn A xin nghỉ mai ạ"}).json()["parsed"]
    assert body["student_id"] == "K4001"
    assert body["student_known"] is True
    assert "suy ra từ tên" in body["lookup_note"]


def test_duplicate_name_without_an_id_refuses_to_guess(twins, admin_client, monkeypatch):
    """Mô hình đoán K4101; code phải gạt đi vì đơn không ghi mã."""
    fake_model(monkeypatch, '{"student_id":"K4101","student_name":"Trần Văn Sinh Đôi",'
                            '"dates":["2026-08-01"],"category":"ốm","reason_text":"sốt"}')
    body = admin_client.post(
        "/api/admin/parse-leave",
        json={"text": "Em Trần Văn Sinh Đôi xin nghỉ mai ạ"}).json()["parsed"]
    assert body["student_id"] is None, "không được chọn hộ khi hai người trùng tên"
    assert body["student_known"] is False
    assert sorted(m["student_id"] for m in body["name_matches"]) == list(twins)
    assert "phải bạn chọn" in body["lookup_note"]


def test_duplicate_name_with_an_id_in_the_text_trusts_the_id(twins, admin_client, monkeypatch):
    """Đơn tự ghi mã thì tin mã, kể cả khi tên trùng nhiều người."""
    fake_model(monkeypatch, '{"student_id":"K4102","student_name":"Trần Văn Sinh Đôi",'
                            '"dates":["2026-08-01"],"category":"ốm","reason_text":"sốt"}')
    body = admin_client.post(
        "/api/admin/parse-leave",
        json={"text": "Em K4102 Trần Văn Sinh Đôi xin nghỉ mai ạ"}).json()["parsed"]
    assert body["student_id"] == "K4102"
    assert body["student_known"] is True


def test_name_not_in_the_roster_is_reported(seeded, admin_client, monkeypatch):
    fake_model(monkeypatch, '{"student_id":null,"student_name":"Người Lạ Hoắc",'
                            '"dates":["2026-08-01"],"category":"ốm","reason_text":"x"}')
    body = admin_client.post("/api/admin/parse-leave",
                             json={"text": "Em Người Lạ Hoắc xin nghỉ"}).json()["parsed"]
    assert body["student_known"] is False
    assert "Không tìm thấy" in body["lookup_note"]


def test_id_not_in_the_roster_is_reported_and_cleared(seeded, admin_client, monkeypatch):
    """Mã không có trong lớp phải bị gạt, không được để lại như thể hợp lệ."""
    fake_model(monkeypatch, '{"student_id":"K9999","student_name":null,'
                            '"dates":["2026-08-01"],"category":"ốm","reason_text":"x"}')
    body = admin_client.post("/api/admin/parse-leave",
                             json={"text": "Em K9999 xin nghỉ mai"}).json()["parsed"]
    assert body["student_id"] is None
    assert body["student_known"] is False
    assert "KHÔNG có trong danh sách lớp" in body["lookup_note"]


# ==========================================================================
# SQL do mô hình sinh: `;` rồi mới tới LIMIT
# ==========================================================================
def test_semicolon_before_a_trailing_limit_is_tolerated(check):
    """Lỗi thật: model sinh `SELECT …;\\nLIMIT 200` làm hỏng 100% một câu hỏi.

    Phần sau `;` không bao giờ được chạy; ở đây chỉ quyết định bỏ qua hay báo lỗi.
    Mệnh đề LIMIT thừa thì vô hại - `fetchmany` đã chặn số dòng ở tầng dưới.
    """
    assert check("SELECT name FROM students;\nLIMIT 200") == "SELECT name FROM students"


def test_real_second_statement_after_a_semicolon_is_still_rejected(check):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        check("SELECT 1;\nDROP TABLE students")


def test_semicolon_inside_a_string_literal_is_not_a_split(check):
    sql = "SELECT name FROM students WHERE name = 'a;b' LIMIT 5"
    assert check(sql) == sql
