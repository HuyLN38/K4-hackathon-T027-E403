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
