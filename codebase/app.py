"""FastAPI app - hệ thống chuyên cần đáng tin cho lớp học.

Ba bề mặt người dùng:
  - Học viên  : /checkin (quét QR)  ·  /me (dữ liệu của chính mình)
  - Máy chiếu : /projector (mã QR xoay vòng)
  - Labcoach  : /admin (bản tin đầu ngày, buổi học, flag bất thường, audit)

Tầng mô hình ngôn ngữ tắt trong bản dựng này (xem llm.py). Mọi con số trên
dashboard đều do rules.py tính và truy vết được.
"""
from __future__ import annotations

import csv
import io
import json
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

import devices
import llm
import qr
import qrtoken
import rules
from db import BASE_DIR, DB_PATH, audit, connect, init_db, load_config, now_ms, rows_to_dicts
from security import (
    ADMIN_COOKIE,
    CSRF_COOKIE,
    DEVICE_COOKIE,
    NO_AUTO_COOKIE,
    STUDENT_COOKIE,
    Guards,
    SecurityHeadersMiddleware,
    Session,
    SubnetGuardMiddleware,
    client_ip,
    compute_device_hash,
    compute_fp_hash,
    csrf_ok,
    hash_password,
    new_device_id,
    verify_password,
)

CONFIG = load_config()
GUARDS = Guards()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Chuyên cần lớp học",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SubnetGuardMiddleware, config=CONFIG)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# --------------------------------------------------------------------------
# Phụ thuộc dùng chung
# --------------------------------------------------------------------------
def get_db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def req_ip(request: Request) -> str:
    return client_ip(request, bool(CONFIG["network"]["trust_proxy_header"]))


def current_admin(request: Request) -> Session | None:
    session = GUARDS.sessions.get(request.cookies.get(ADMIN_COOKIE))
    return session if session and session.kind == "admin" else None


def require_admin(request: Request) -> Session:
    session = current_admin(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Cần đăng nhập Labcoach")
    return session


def require_admin_write(request: Request) -> Session:
    """Bắt buộc có phiên hợp lệ **và** CSRF token khớp cho mọi phép đổi trạng thái."""
    session = require_admin(request)
    if not csrf_ok(request, session):
        raise HTTPException(status_code=403, detail="CSRF token không hợp lệ")
    return session


def current_student(request: Request) -> Session | None:
    session = GUARDS.sessions.get(request.cookies.get(STUDENT_COOKIE))
    return session if session and session.kind == "student" else None


def require_student(request: Request) -> Session:
    session = current_student(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Cần đăng nhập học viên")
    return session


def today_str() -> str:
    return date_cls.today().isoformat()


def base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


# --------------------------------------------------------------------------
# Trang học viên
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    open_session = conn.execute(
        "SELECT * FROM sessions WHERE state = 'open' ORDER BY session_id DESC LIMIT 1"
    ).fetchone()
    return templates.TemplateResponse(
        request,
        "home.html",
        {"open_session": open_session, "is_admin": current_admin(request) is not None},
    )


@app.get("/checkin", response_class=HTMLResponse)
def checkin_page(request: Request, t: str = "", conn: sqlite3.Connection = Depends(get_db)):
    """Trang mở ra sau khi quét QR. Token nằm trong URL, học viên chỉ nhập mã học viên."""
    token_row = None
    session_row = None
    problem = None

    if t:
        token_row = conn.execute("SELECT * FROM qr_tokens WHERE token = ?", (t,)).fetchone()
        if token_row is None:
            problem = "Mã QR không hợp lệ. Quét lại mã đang hiện trên máy chiếu."
        else:
            session_row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (token_row["session_id"],)
            ).fetchone()
            grace_ms = int(CONFIG["qr"]["grace_sec"]) * 1000
            if token_row["revoked"]:
                problem = "Mã QR đã bị thu hồi. Quét lại mã mới trên máy chiếu."
            elif now_ms() > token_row["expires_at"] + grace_ms:
                problem = "Mã QR đã hết hạn. Quét lại mã đang hiện trên máy chiếu."
            elif session_row is None or session_row["state"] != "open":
                problem = "Buổi học chưa mở điểm danh."
    else:
        problem = "Chưa có mã QR. Mở camera và quét mã trên máy chiếu."

    return templates.TemplateResponse(
        request,
        "checkin.html",
        {
            "token": t,
            "token_row": token_row,
            "session_row": session_row,
            "problem": problem,
        },
    )


class CheckinIn(BaseModel):
    token: str = Field(min_length=1, max_length=64)
    student_id: str = Field(min_length=1, max_length=32)
    fingerprint: str = Field(default="", max_length=256)


@app.post("/api/checkin")
def api_checkin(
    payload: CheckinIn,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
):
    ip = req_ip(request)
    rl = CONFIG["rate_limit"]
    if not GUARDS.rate.check(f"ip:{ip}", int(rl["checkin_per_ip_per_min"]), 60):
        raise HTTPException(status_code=429, detail="Quá nhiều yêu cầu từ thiết bị này. Thử lại sau.")
    student_id = payload.student_id.strip().upper()
    if not GUARDS.rate.check(f"sid:{student_id}", int(rl["checkin_per_student_per_min"]), 60):
        raise HTTPException(status_code=429, detail="Quá nhiều lần thử cho mã học viên này.")

    student = conn.execute(
        "SELECT * FROM students WHERE student_id = ? AND active = 1", (student_id,)
    ).fetchone()
    if student is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy mã học viên trong lớp này.")

    token_row = conn.execute(
        "SELECT * FROM qr_tokens WHERE token = ?", (payload.token.strip(),)
    ).fetchone()
    if token_row is None:
        raise HTTPException(status_code=400, detail="Mã QR không hợp lệ.")

    session_id = token_row["session_id"]
    call_index = token_row["call_index"]
    session_row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if session_row is None or session_row["state"] != "open":
        raise HTTPException(status_code=409, detail="Buổi học chưa mở điểm danh.")
    if session_row["call_index"] != call_index:
        raise HTTPException(status_code=409, detail="Mã QR thuộc lượt điểm danh đã đóng.")

    ok, _row, token_in_grace, reason = qrtoken.verify(
        conn, payload.token.strip(), session_id, call_index, student_id, CONFIG
    )
    if not ok:
        messages = {
            qrtoken.REASON_UNKNOWN: "Mã QR không hợp lệ.",
            qrtoken.REASON_REVOKED: "Mã QR đã bị thu hồi. Quét lại mã mới.",
            qrtoken.REASON_EXPIRED: "Mã QR đã hết hạn. Quét lại mã đang hiện trên máy chiếu.",
            qrtoken.REASON_WRONG_SESSION: "Mã QR không thuộc buổi học này.",
            qrtoken.REASON_WRONG_CALL: "Mã QR thuộc lượt điểm danh đã đóng.",
            qrtoken.REASON_REPLAY: "Mã QR này bạn đã dùng rồi. Quét lại mã mới.",
        }
        raise HTTPException(status_code=400, detail=messages.get(reason, "Mã QR không dùng được."))

    # --- lớp 3: danh tính thiết bị ---
    device_id = request.cookies.get(DEVICE_COOKIE)
    minted_device = False
    if not device_id:
        device_id = new_device_id()
        minted_device = True
    device_hash = compute_device_hash(device_id, payload.fingerprint)
    fp_hash = compute_fp_hash(payload.fingerprint)

    locked = student["device_hash"]
    enforce_device = bool(CONFIG["checkin"]["require_device_binding"])

    # Vế 1: học viên đã buộc thiết bị nhưng đang dùng máy khác.
    if enforce_device and locked and locked != device_hash:
        rules.raise_flag(
            conn, None, session_id, student_id, "DEVICE_MISMATCH",
            "Chặn check-in: thiết bị khác thiết bị đã khoá, chờ Labcoach nhả thiết bị",
        )
        audit(conn, student_id, "checkin_blocked_device_mismatch", target=str(session_id), ip=ip)
        conn.commit()
        raise HTTPException(
            status_code=409,
            detail="Thiết bị này khác thiết bị đã khoá của mã học viên của bạn. "
                   "Nhờ Labcoach nhả thiết bị cũ, hoặc điểm danh tay cho bạn.",
        )

    # Vế 2: máy này đã buộc cho học viên khác - một thiết bị chỉ cho một người.
    # Phải chặn TRƯỚC khi ghi, không phải ghi rồi gắn flag: ghi trước nghĩa là dữ
    # liệu đã sai từ lúc chưa có ai xem (§1 - "số liệu không đáng tin").
    if enforce_device:
        holder = devices.owner_of(conn, device_hash)
        if holder is not None and holder != student_id:
            rules.raise_flag(
                conn, None, session_id, student_id, "DEVICE_REUSE",
                f"Chặn check-in: thiết bị đã buộc cho {holder}",
            )
            audit(
                conn, student_id, "checkin_blocked_device_reuse",
                target=str(session_id), detail=f"holder={holder}", ip=ip,
            )
            conn.commit()
            raise HTTPException(
                status_code=409,
                detail="Máy này đã được dùng để điểm danh cho một mã học viên khác. "
                       "Mỗi thiết bị chỉ điểm danh cho một người. "
                       "Dùng máy của chính bạn, hoặc nhờ Labcoach điểm danh tay.",
            )

    already = conn.execute(
        """SELECT 1 FROM attendance
           WHERE student_id = ? AND session_id = ? AND call_index = ?""",
        (student_id, session_id, call_index),
    ).fetchone()
    if already is not None:
        raise HTTPException(status_code=409, detail="Bạn đã điểm danh cho lượt này.")

    ts = now_ms()
    status = (
        rules.classify_status(session_row, ts, int(session_row["late_after_min"]))
        if call_index == 1
        else "present"
    )

    try:
        cur = conn.execute(
            """INSERT INTO attendance
               (student_id, session_id, checkin_ts_ms, call_index, ip, device_hash,
                fp_hash, token_valid, token_id, status, source, user_agent)
               VALUES (?,?,?,?,?,?,?,?,?,?,'web',?)""",
            (
                student_id,
                session_id,
                ts,
                call_index,
                ip,
                device_hash,
                fp_hash,
                1,
                token_row["token_id"],
                status,
                request.headers.get("user-agent", "")[:256],
            ),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Bạn đã điểm danh cho lượt này.")

    attendance_id = cur.lastrowid
    qrtoken.consume(conn, token_row["token_id"], student_id)

    if not locked:  # buộc thiết bị ở lần check-in đầu tiên
        devices.bind(conn, student_id, device_hash)

    fired = rules.evaluate_checkin(conn, attendance_id, CONFIG, token_in_grace=token_in_grace)
    audit(
        conn, student_id, "checkin", target=f"session={session_id},call={call_index}",
        detail=f"status={status},flags={','.join(fired) or '-'}", ip=ip,
    )
    conn.commit()

    if minted_device:
        response.set_cookie(
            DEVICE_COOKIE, device_id, max_age=180 * 24 * 3600,
            httponly=True, samesite="lax", path="/",
        )

    # Trả đủ thông tin để học viên **tự xác nhận đúng người**: gõ sai một số trong
    # mã học viên là ghi nhận vào hồ sơ người khác, mà bản ghi chuyên cần thì có
    # thể bị khiếu nại. Rẻ nhất là để chính chủ nhìn thấy tên mình ngay tại chỗ.
    return {
        "ok": True,
        "student_id": student["student_id"],
        "student_name": student["name"],
        "status": status,
        "call_index": call_index,
        "session_date": session_row["date"],
        "session_start_time": session_row["start_time"],
        "room": session_row["room"],
        "checkin_ts": ts,
        "late_minutes": rules.lateness_minutes(session_row, ts),
        "attended_sessions": conn.execute(
            """SELECT COUNT(*) AS n FROM attendance
               WHERE student_id = ? AND call_index = 1 AND status != 'absent'""",
            (student_id,),
        ).fetchone()["n"],
        "device_locked_now": not locked,
        "flags": [{"code": f, "label": rules.RULE_LABEL_VI[f]} for f in fired],
    }


# --------------------------------------------------------------------------
# Học viên xem dữ liệu của chính mình (§6 - minh bạch)
# --------------------------------------------------------------------------
@app.get("/me", response_class=HTMLResponse)
def me_page(request: Request):
    return templates.TemplateResponse(
        request, "me.html", {"session": current_student(request)}
    )


class StudentLoginIn(BaseModel):
    student_id: str = Field(min_length=1, max_length=32)
    pin: str = Field(min_length=1, max_length=32)


@app.post("/api/student/login")
def api_student_login(
    payload: StudentLoginIn,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
):
    ip = req_ip(request)
    if not GUARDS.rate.check(
        f"slogin:{ip}", int(CONFIG["rate_limit"]["login_per_ip_per_15min"]), 900
    ):
        raise HTTPException(status_code=429, detail="Quá nhiều lần đăng nhập. Thử lại sau.")

    student_id = payload.student_id.strip().upper()
    row = conn.execute(
        "SELECT * FROM students WHERE student_id = ? AND active = 1", (student_id,)
    ).fetchone()
    if row is None or not row["pin_hash"] or not verify_password(
        payload.pin, row["pin_hash"], row["pin_salt"]
    ):
        raise HTTPException(status_code=401, detail="Mã học viên hoặc PIN không đúng.")

    sid, session = GUARDS.sessions.create(student_id, "student", role="student")
    response.set_cookie(STUDENT_COOKIE, sid, httponly=True, samesite="strict", path="/")
    response.set_cookie(CSRF_COOKIE, session.csrf, samesite="strict", path="/")
    # Đăng nhập bằng PIN là nói rõ "đúng tôi", nên gỡ cờ chặn tự nhận thiết bị.
    response.delete_cookie(NO_AUTO_COOKIE, path="/")
    audit(conn, student_id, "student_login", ip=ip)
    conn.commit()
    return {"ok": True, "name": row["name"]}


class DeviceSessionIn(BaseModel):
    fingerprint: str = Field(default="", max_length=250)


@app.post("/api/checkin/whoami")
def api_checkin_whoami(
    payload: DeviceSessionIn,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Máy này đang buộc với mã học viên nào? Trả `null` nếu chưa buộc.

    Để trang check-in tự điền mã từ lần thứ hai trở đi. Gõ tay mỗi buổi là nguồn
    sai thật: gõ nhầm một ký tự thì buổi đó ghi cho người khác, và chính ràng buộc
    "một thiết bị một học viên" sẽ chặn lượt đúng của cả hai người sau đó.

    **Chỉ đọc, không ghi gì.** Endpoint này không tạo phiên, không ghi attendance.
    Việc ghi vẫn phải qua `/api/checkin` với token QR còn sống - tức vẫn phải đang
    ở trong phòng. Ở đây chỉ tiết kiệm cho học viên thao tác gõ lại mã của mình.
    """
    device_id = request.cookies.get(DEVICE_COOKIE)
    if not device_id:
        return {"bound": False}

    device_hash = compute_device_hash(device_id, payload.fingerprint)
    owner = devices.owner_of(conn, device_hash)
    if owner is None:
        return {"bound": False}

    row = conn.execute(
        "SELECT student_id, name FROM students WHERE student_id = ? AND active = 1", (owner,)
    ).fetchone()
    if row is None:
        return {"bound": False}
    return {"bound": True, "student_id": row["student_id"], "name": row["name"]}


@app.post("/api/student/device-session")
def api_student_device_session(
    payload: DeviceSessionIn,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Mở phiên /me bằng chính thiết bị đã buộc, không cần PIN.

    Vì sao được phép: `device_hash` đã là bằng chứng danh tính mạnh nhất hệ thống
    có (lớp 3, §4.3). Chính nó quyết định một lượt check-in có được ghi dưới tên
    học viên này hay không. Thiết bị đủ tin để **ghi** một bản ghi chuyên cần thì
    cũng đủ tin để **đọc lại** bản ghi đó.

    Vì sao vẫn giữ đăng nhập PIN: máy mới chưa buộc, máy mượn, hoặc học viên muốn
    xem từ máy tính đều không có đường này.

    Khác biệt so với check-in, và đây là chỗ phải nói thẳng: check-in còn đòi một
    token QR còn sống, tức bằng chứng "đang ở trong phòng". Đường này không đòi.
    Ai cầm được điện thoại đã mở khoá của học viên thì xem được dữ liệu chuyên cần
    của người đó. Đổi lại là học viên không phải nhớ PIN để xem hồ sơ của chính
    mình - mà PIN quên được thì trang này thành trang không ai vào.
    """
    ip = req_ip(request)
    if not GUARDS.rate.check(f"devsess:{ip}", 30, 900):
        raise HTTPException(status_code=429, detail="Thử lại sau ít phút.")

    # Vừa bấm Đăng xuất thì không tự nhận lại - nếu không, nút đó vô nghĩa.
    if request.cookies.get(NO_AUTO_COOKIE):
        raise HTTPException(status_code=401, detail="Đã đăng xuất trên thiết bị này.")

    device_id = request.cookies.get(DEVICE_COOKIE)
    if not device_id:
        raise HTTPException(status_code=401, detail="Thiết bị này chưa từng điểm danh.")

    device_hash = compute_device_hash(device_id, payload.fingerprint)
    owner = devices.owner_of(conn, device_hash)
    if owner is None:
        raise HTTPException(status_code=401, detail="Thiết bị này chưa buộc với mã học viên nào.")

    row = conn.execute(
        "SELECT student_id, name FROM students WHERE student_id = ? AND active = 1", (owner,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Mã học viên của thiết bị này đã ngưng theo dõi.")

    # role ghi rõ phiên này đến từ thiết bị chứ không từ PIN. `current_student`
    # chỉ xét `kind`, nên hai loại phiên dùng được như nhau - nhưng khi có khiếu
    # nại thì audit_log phân biệt được ai gõ PIN và ai chỉ cầm đúng máy.
    sid, session = GUARDS.sessions.create(row["student_id"], "student", role="student:device")
    response.set_cookie(STUDENT_COOKIE, sid, httponly=True, samesite="strict", path="/")
    response.set_cookie(CSRF_COOKIE, session.csrf, samesite="strict", path="/")
    audit(conn, row["student_id"], "student_device_session",
          detail=f"device={devices.short(device_hash)}", ip=ip)
    conn.commit()
    return {"ok": True, "name": row["name"], "student_id": row["student_id"]}


@app.post("/api/student/logout")
def api_student_logout(request: Request, response: Response):
    GUARDS.sessions.destroy(request.cookies.get(STUDENT_COOKIE))
    response.delete_cookie(STUDENT_COOKIE, path="/")
    # Chặn tự nhận thiết bị cho tới khi có người đăng nhập bằng PIN. Không có cờ
    # này thì bấm Đăng xuất xong trang tự vào lại ngay - học viên muốn đưa máy cho
    # người khác xem một thứ khác sẽ không có cách nào thoát.
    response.set_cookie(NO_AUTO_COOKIE, "1", httponly=True, samesite="strict", path="/")
    return {"ok": True}


@app.get("/api/student/me")
def api_student_me(
    request: Request,
    session: Session = Depends(require_student),
    conn: sqlite3.Connection = Depends(get_db),
):
    student_id = session.subject
    student = conn.execute(
        "SELECT student_id, name, device_locked_at FROM students WHERE student_id = ?",
        (student_id,),
    ).fetchone()

    history = conn.execute(
        """SELECT s.session_id, s.date, s.start_time, s.room, s.state,
                  a.call_index, a.status, a.checkin_ts_ms, a.source
           FROM sessions s
           LEFT JOIN attendance a
                  ON a.session_id = s.session_id AND a.student_id = ? AND a.call_index = 1
           WHERE s.state = 'closed'
           ORDER BY s.date DESC, s.start_time DESC LIMIT 30""",
        (student_id,),
    ).fetchall()

    risk = rules.compute_risk(conn, student_id, CONFIG, today_str())
    flags = conn.execute(
        """SELECT rule_code, severity, detail, created_at, resolved
           FROM anomaly_flags WHERE student_id = ? ORDER BY created_at DESC LIMIT 20""",
        (student_id,),
    ).fetchall()

    return {
        "student": dict(student) if student else None,
        "history": rows_to_dicts(history),
        "risk_level": risk.level,
        "rule_trace": risk.trace,
        "flags": [
            {**dict(f), "label": rules.RULE_LABEL_VI.get(f["rule_code"], f["rule_code"])}
            for f in flags
        ],
        # "device" hay "pin". Trang nói ra vì sao nó biết bạn là ai: hiện dữ liệu
        # cá nhân mà không giải thích mình nhận ra người dùng bằng cách nào thì
        # đúng là thứ §6 gọi là "bị xem như công cụ giám sát".
        "auth_via": "device" if session.role == "student:device" else "pin",
    }


# --------------------------------------------------------------------------
# Đăng nhập Labcoach
# --------------------------------------------------------------------------
@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    if current_admin(request):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(request, "admin_login.html", {})


class AdminLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@app.post("/api/admin/login")
def api_admin_login(
    payload: AdminLoginIn,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
):
    ip = req_ip(request)
    if not GUARDS.rate.check(
        f"alogin:{ip}", int(CONFIG["rate_limit"]["login_per_ip_per_15min"]), 900
    ):
        raise HTTPException(status_code=429, detail="Quá nhiều lần đăng nhập. Thử lại sau.")

    row = conn.execute(
        "SELECT * FROM admins WHERE username = ?", (payload.username.strip().lower(),)
    ).fetchone()
    if row is None or not verify_password(payload.password, row["pw_hash"], row["pw_salt"]):
        audit(conn, payload.username.strip().lower(), "admin_login_failed", ip=ip)
        conn.commit()
        raise HTTPException(status_code=401, detail="Tên đăng nhập hoặc mật khẩu không đúng.")

    sid, session = GUARDS.sessions.create(row["username"], "admin", role=row["role"])
    response.set_cookie(ADMIN_COOKIE, sid, httponly=True, samesite="strict", path="/")
    response.set_cookie(CSRF_COOKIE, session.csrf, samesite="strict", path="/")
    conn.execute(
        "UPDATE admins SET last_login_at = ? WHERE username = ?", (now_ms(), row["username"])
    )
    audit(conn, row["username"], "admin_login", ip=ip)
    conn.commit()
    return {"ok": True, "display_name": row["display_name"], "role": row["role"]}


@app.post("/api/admin/logout")
def api_admin_logout(request: Request, response: Response):
    GUARDS.sessions.destroy(request.cookies.get(ADMIN_COOKIE))
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return {"ok": True}


# --------------------------------------------------------------------------
# Trang Labcoach
# --------------------------------------------------------------------------
def _admin_page(
    request: Request, template: str, active: str, extra: dict[str, Any] | None = None
):
    session = current_admin(request)
    if session is None:
        return RedirectResponse("/admin/login", status_code=303)
    context = {
        "admin": session,
        "active": active,
        "today": today_str(),
        "llm_enabled": llm.is_enabled(CONFIG),
    }
    context.update(extra or {})
    return templates.TemplateResponse(request, template, context)


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    return _admin_page(request, "admin_dashboard.html", "dashboard")


@app.get("/admin/sessions", response_class=HTMLResponse)
def admin_sessions_page(request: Request):
    return _admin_page(request, "admin_sessions.html", "sessions")


@app.get("/admin/roster", response_class=HTMLResponse)
def admin_roster_page(request: Request):
    return _admin_page(request, "admin_roster.html", "roster")


@app.get("/admin/anomalies", response_class=HTMLResponse)
def admin_anomalies_page(request: Request):
    return _admin_page(request, "admin_anomalies.html", "anomalies")


@app.get("/admin/assistant", response_class=HTMLResponse)
def admin_assistant_page(request: Request):
    return _admin_page(request, "admin_assistant.html", "assistant")


@app.get("/admin/audit", response_class=HTMLResponse)
def admin_audit_page(request: Request):
    return _admin_page(request, "admin_audit.html", "audit")


@app.get("/projector", response_class=HTMLResponse)
def projector_page(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    session = current_admin(request)
    if session is None:
        return RedirectResponse("/admin/login", status_code=303)
    open_session = conn.execute(
        "SELECT * FROM sessions WHERE state = 'open' ORDER BY session_id DESC LIMIT 1"
    ).fetchone()
    return templates.TemplateResponse(
        request,
        "projector.html",
        {"admin": session, "open_session": open_session, "rotate_sec": CONFIG["qr"]["rotate_sec"]},
    )


# --------------------------------------------------------------------------
# API máy chiếu
# --------------------------------------------------------------------------
@app.get("/api/projector/token")
def api_projector_token(
    request: Request,
    session_id: int | None = None,
    _admin: Session = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Mã đang chiếu. Bỏ trống `session_id` = "buổi nào đang mở thì chiếu buổi đó".

    Máy chiếu gọi theo kiểu bỏ trống. Lý do: màn hình treo trên tường suốt buổi,
    còn Labcoach đóng buổi này rồi mở buổi kia từ một máy khác. Nếu trang bám vào
    `session_id` nhúng lúc tải, nó sẽ hỏi mãi một buổi đã đóng và đứng yên ở mã
    đã chết - học viên quét vào mã không còn hiệu lực mà không ai trong phòng biết.
    """
    if session_id is None:
        session_row = conn.execute(
            "SELECT * FROM sessions WHERE state = 'open' ORDER BY session_id DESC LIMIT 1"
        ).fetchone()
    else:
        session_row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if session_row is None:
            raise HTTPException(status_code=404, detail="Không có buổi học này")
        if session_row["state"] != "open":
            raise HTTPException(status_code=409, detail="Buổi học chưa mở điểm danh")

    # Giữa hai buổi thì không có buổi nào mở - đó là trạng thái bình thường, không
    # phải lỗi. Trả 200 để máy chiếu hiện "chưa mở buổi" và tự bắt lại khi có buổi
    # mới, thay vì kẹt ở một thông báo lỗi cho tới khi có người bấm F5.
    if session_row is None:
        return {"open": False}

    session_id = session_row["session_id"]
    call_index = session_row["call_index"]
    token_row = qrtoken.active_token(conn, session_id, call_index, CONFIG)
    url = f"{base_url(request)}/checkin?t={token_row['token']}"

    counted = conn.execute(
        """SELECT COUNT(*) AS n FROM attendance
           WHERE session_id = ? AND call_index = ?""",
        (session_id, call_index),
    ).fetchone()["n"]
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM students WHERE active = 1"
    ).fetchone()["n"]

    return {
        "open": True,
        "session_id": session_id,
        "date": session_row["date"],
        "start_time": session_row["start_time"],
        "room": session_row["room"],
        "token": token_row["token"],
        "call_index": call_index,
        "checkin_url": url,
        "qr_svg": qr.to_svg(
            url,
            module_px=int(CONFIG["qr"]["module_px"]),
            quiet_zone=int(CONFIG["qr"]["quiet_zone"]),
        ),
        "expires_in_ms": max(0, token_row["expires_at"] - now_ms()),
        "rotate_sec": int(CONFIG["qr"]["rotate_sec"]),
        "use_count": token_row["use_count"],
        "checked_in": counted,
        "roster_size": total,
    }


@app.post("/api/admin/sessions/{session_id}/rotate-token")
def api_rotate_token(
    session_id: int,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    session_row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if session_row is None:
        raise HTTPException(status_code=404, detail="Không có buổi học này")
    token_row = qrtoken.rotate_now(conn, session_id, session_row["call_index"], CONFIG)
    audit(conn, admin.subject, "rotate_token", target=str(session_id), ip=req_ip(request))
    conn.commit()
    return {"ok": True, "token": token_row["token"]}


# --------------------------------------------------------------------------
# API buổi học
# --------------------------------------------------------------------------
class SessionIn(BaseModel):
    date: str = Field(min_length=10, max_length=10)
    start_time: str = Field(min_length=5, max_length=5)
    room: str = Field(default="", max_length=64)
    late_after_min: int = Field(default=10, ge=0, le=240)


@app.get("/api/admin/sessions")
def api_list_sessions(
    _admin: Session = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
):
    rows = conn.execute(
        """SELECT s.*,
                  (SELECT COUNT(*) FROM attendance a
                    WHERE a.session_id = s.session_id AND a.call_index = 1) AS call1_count,
                  (SELECT COUNT(*) FROM attendance a
                    WHERE a.session_id = s.session_id AND a.call_index = 2) AS call2_count
           FROM sessions s ORDER BY s.date DESC, s.start_time DESC LIMIT 100"""
    ).fetchall()
    roster = conn.execute("SELECT COUNT(*) AS n FROM students WHERE active = 1").fetchone()["n"]
    return {"sessions": rows_to_dicts(rows), "roster_size": roster}


@app.post("/api/admin/sessions")
def api_create_session(
    payload: SessionIn,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    try:
        datetime.strptime(f"{payload.date} {payload.start_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(status_code=422, detail="Ngày hoặc giờ không đúng định dạng")
    try:
        cur = conn.execute(
            """INSERT INTO sessions (date, start_time, room, late_after_min)
               VALUES (?,?,?,?)""",
            (payload.date, payload.start_time, payload.room or None, payload.late_after_min),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Buổi học này đã tồn tại")
    audit(conn, admin.subject, "create_session", target=str(cur.lastrowid), ip=req_ip(request))
    conn.commit()
    return {"ok": True, "session_id": cur.lastrowid}


@app.post("/api/admin/sessions/{session_id}/open")
def api_open_session(
    session_id: int,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Không có buổi học này")
    if row["state"] == "closed":
        raise HTTPException(status_code=409, detail="Buổi học đã đóng, không mở lại được")

    other = conn.execute(
        "SELECT session_id FROM sessions WHERE state = 'open' AND session_id != ?", (session_id,)
    ).fetchone()
    if other is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Buổi #{other['session_id']} đang mở. Đóng buổi đó trước.",
        )

    conn.execute(
        "UPDATE sessions SET state = 'open', opened_at = ?, call_index = 1 WHERE session_id = ?",
        (now_ms(), session_id),
    )
    audit(conn, admin.subject, "open_session", target=str(session_id), ip=req_ip(request))
    conn.commit()
    return {"ok": True}


@app.post("/api/admin/sessions/{session_id}/second-call")
def api_second_call(
    session_id: int,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Mở lượt điểm danh thứ hai (lớp 4).

    Thời điểm do Labcoach bấm, không cố định theo lịch: nếu học viên biết trước
    phút nào gọi lượt 2 thì lớp 4 mất hết tác dụng.
    """
    row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Không có buổi học này")
    if row["state"] != "open":
        raise HTTPException(status_code=409, detail="Buổi học chưa mở")
    if row["call_index"] == 2:
        raise HTTPException(status_code=409, detail="Lượt 2 đã mở")

    qrtoken.revoke_all(conn, session_id)  # token lượt 1 chết ngay
    ts = now_ms()
    conn.execute(
        "UPDATE sessions SET call_index = 2, second_call_ts = ? WHERE session_id = ?",
        (ts, session_id),
    )
    audit(conn, admin.subject, "second_call", target=str(session_id), ip=req_ip(request))
    conn.commit()
    return {"ok": True, "second_call_ts": ts}


@app.post("/api/admin/sessions/{session_id}/close")
def api_close_session(
    session_id: int,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Không có buổi học này")

    qrtoken.revoke_all(conn, session_id)
    conn.execute(
        "UPDATE sessions SET state = 'closed', closed_at = ? WHERE session_id = ?",
        (now_ms(), session_id),
    )
    conn.commit()

    early_departures = rules.detect_early_departures(conn, session_id)
    audit(
        conn, admin.subject, "close_session", target=str(session_id),
        detail=f"early_departures={len(early_departures)}", ip=req_ip(request),
    )
    conn.commit()
    return {"ok": True, "early_departure_flags": early_departures}


@app.get("/api/admin/sessions/{session_id}/live")
def api_session_live(
    session_id: int,
    _admin: Session = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    session_row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if session_row is None:
        raise HTTPException(status_code=404, detail="Không có buổi học này")

    rows = conn.execute(
        """SELECT s.student_id, s.name,
                  s.device_hash IS NOT NULL AS device_locked,
                  a1.status AS call1_status, a1.checkin_ts_ms AS call1_ts, a1.source AS call1_source,
                  a1.manual_reason AS call1_reason, a1.manual_by AS call1_by,
                  a2.status AS call2_status, a2.checkin_ts_ms AS call2_ts,
                  a2.source AS call2_source, a2.manual_reason AS call2_reason,
                  (SELECT GROUP_CONCAT(f.rule_code) FROM anomaly_flags f
                    WHERE f.student_id = s.student_id AND f.session_id = ?
                      AND f.resolved = 0) AS flags
           FROM students s
           LEFT JOIN attendance a1
                  ON a1.student_id = s.student_id AND a1.session_id = ? AND a1.call_index = 1
           LEFT JOIN attendance a2
                  ON a2.student_id = s.student_id AND a2.session_id = ? AND a2.call_index = 2
           WHERE s.active = 1
           ORDER BY s.student_id""",
        (session_id, session_id, session_id),
    ).fetchall()

    return {"session": dict(session_row), "rows": rows_to_dicts(rows)}


# Lý do nhập tay. Danh sách đóng để về sau đếm được "bao nhiêu buổi mất vì máy
# hỏng" - lý do gõ tự do thì không tổng hợp được.
MANUAL_REASONS = {
    "lost_phone": "Mất / không mang điện thoại",
    "broken_phone": "Điện thoại hỏng hoặc hết pin",
    "device_locked": "Thiết bị đã buộc cho mã khác / chờ nhả thiết bị",
    "no_network": "Điện thoại không vào được WiFi lớp",
    "wifi_down": "WiFi lớp sập",
    "other": "Lý do khác",
}


class ManualCheckinIn(BaseModel):
    session_id: int
    student_id: str = Field(min_length=1, max_length=32)
    call_index: int = Field(ge=1, le=2)
    status: str = Field(pattern="^(present|late|absent)$")
    reason: str = Field(default="other", max_length=32)
    note: str = Field(default="", max_length=200)


@app.get("/api/admin/manual-reasons")
def api_manual_reasons(_admin: Session = Depends(require_admin)):
    return {"reasons": [{"code": k, "label": v} for k, v in MANUAL_REASONS.items()]}


@app.post("/api/admin/manual-checkin")
def api_manual_checkin(
    payload: ManualCheckinIn,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Điểm danh tay - đường thoát khi thiết bị không dùng được.

    Ba lớp kia đều chặn được thật, nên phải có đường này: mất điện thoại, máy hỏng,
    hết pin, hoặc thiết bị đang buộc cho mã khác mà chưa kịp nhả. Không có nó thì
    một cái điện thoại hỏng thành một buổi vắng oan, và §6 xếp "học viên bị đánh
    dấu at_risk oan" là rủi ro phải xử lý.

    Bản ghi tay mang `source='manual'`, `token_valid=0`, `device_hash=NULL` và kèm
    lý do - nên về sau không bao giờ lẫn với bằng chứng do hệ thống tự thu.
    """
    if payload.reason not in MANUAL_REASONS:
        raise HTTPException(status_code=422, detail="Lý do nhập tay không hợp lệ")

    student_id = payload.student_id.strip().upper()
    student = conn.execute(
        "SELECT 1 FROM students WHERE student_id = ? AND active = 1", (student_id,)
    ).fetchone()
    if student is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy mã học viên")
    session_row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (payload.session_id,)
    ).fetchone()
    if session_row is None:
        raise HTTPException(status_code=404, detail="Không có buổi học này")

    reason_text = MANUAL_REASONS[payload.reason]
    if payload.note:
        reason_text = f"{reason_text} — {payload.note}"

    conn.execute(
        """INSERT INTO attendance
           (student_id, session_id, checkin_ts_ms, call_index, ip, device_hash,
            token_valid, token_id, status, source, manual_reason, manual_by, user_agent)
           VALUES (?,?,?,?,NULL,NULL,0,NULL,?,'manual',?,?,NULL)
           ON CONFLICT(student_id, session_id, call_index)
           DO UPDATE SET status = excluded.status, source = 'manual',
                         checkin_ts_ms = excluded.checkin_ts_ms,
                         manual_reason = excluded.manual_reason,
                         manual_by = excluded.manual_by""",
        (
            student_id, payload.session_id, now_ms(), payload.call_index,
            payload.status, reason_text, admin.subject,
        ),
    )
    audit(
        conn, admin.subject, "manual_checkin",
        target=f"{student_id}@session={payload.session_id},call={payload.call_index}",
        detail=f"status={payload.status};reason={payload.reason};{payload.note}",
        ip=req_ip(request),
    )
    conn.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# API bản tin rủi ro
# --------------------------------------------------------------------------
@app.get("/api/admin/briefing")
def api_briefing(
    date: str | None = None,
    _admin: Session = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    as_of = date or today_str()
    rows = conn.execute(
        """SELECT r.*, s.name FROM risk_snapshots r
           JOIN students s ON s.student_id = r.student_id
           WHERE r.date = ? AND r.risk_level != 'ok'
           ORDER BY CASE r.risk_level WHEN 'at_risk' THEN 0 ELSE 1 END, r.student_id
           LIMIT ?""",
        (as_of, int(CONFIG["risk"]["briefing_max_cases"])),
    ).fetchall()

    cases = []
    for row in rows:
        item = dict(row)
        item["rule_trace"] = json.loads(row["rule_trace"])
        cases.append(item)

    summary = conn.execute(
        """SELECT risk_level, COUNT(*) AS n FROM risk_snapshots
           WHERE date = ? GROUP BY risk_level""",
        (as_of,),
    ).fetchall()

    # Ngày gần nhất đã có bản tin. Dùng cho trường hợp mở app vào hôm không có
    # buổi học: màn hình trống không nói được gì, còn con số này cho một lối đi.
    latest = conn.execute(
        """SELECT date FROM risk_snapshots WHERE date <= ?
           ORDER BY date DESC LIMIT 1""",
        (today_str(),),
    ).fetchone()

    return {
        "date": as_of,
        "cases": cases,
        "summary": {r["risk_level"]: r["n"] for r in summary},
        "llm_enabled": llm.is_enabled(CONFIG),
        "generated": bool(summary),
        "latest_available": latest["date"] if latest else None,
        "has_session": bool(
            conn.execute(
                "SELECT 1 FROM sessions WHERE date = ? LIMIT 1", (as_of,)
            ).fetchone()
        ),
    }


@app.get("/api/admin/calendar")
def api_calendar(
    month: str,
    _admin: Session = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Dữ liệu cho lịch chọn ngày: ngày nào có buổi học, ngày nào đã có bản tin.

    Lịch trống rỗng thì chỉ là cái để bấm; lịch có đánh dấu trả lời được câu
    "hôm đó lớp có học không" ngay trên đó - tránh việc Labcoach chọn một ngày
    không có buổi rồi tưởng hệ thống hỏng.
    """
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(status_code=422, detail="Tháng phải có dạng YYYY-MM")

    sessions = conn.execute(
        """SELECT date, COUNT(*) AS n FROM sessions
           WHERE date LIKE ? GROUP BY date""",
        (f"{month}-%",),
    ).fetchall()
    briefings = conn.execute(
        """SELECT date,
                  COUNT(*) AS total,
                  SUM(CASE WHEN risk_level = 'at_risk' THEN 1 ELSE 0 END) AS at_risk
           FROM risk_snapshots WHERE date LIKE ? GROUP BY date""",
        (f"{month}-%",),
    ).fetchall()

    days: dict[str, dict[str, Any]] = {}
    for row in sessions:
        days.setdefault(row["date"], {})["sessions"] = row["n"]
    for row in briefings:
        days.setdefault(row["date"], {})["at_risk"] = row["at_risk"] or 0

    return {"month": month, "today": today_str(), "days": days}


@app.post("/api/admin/briefing/rebuild")
def api_briefing_rebuild(
    request: Request,
    date: str | None = None,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    as_of = date or today_str()
    top = rules.build_briefing(conn, CONFIG, as_of, actor=admin.subject)
    return {"ok": True, "date": as_of, "cases": len(top)}


@app.get("/api/admin/risk/{student_id}")
def api_risk_detail(
    student_id: str,
    _admin: Session = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    student = conn.execute(
        "SELECT * FROM students WHERE student_id = ?", (student_id.strip().upper(),)
    ).fetchone()
    if student is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy học viên")

    risk = rules.compute_risk(conn, student["student_id"], CONFIG, today_str())
    flags = conn.execute(
        """SELECT * FROM anomaly_flags WHERE student_id = ?
           ORDER BY created_at DESC LIMIT 50""",
        (student["student_id"],),
    ).fetchall()

    return {
        "student": {"student_id": student["student_id"], "name": student["name"]},
        "risk_level": risk.level,
        "rule_trace": risk.trace,
        "flags": [
            {**dict(f), "label": rules.RULE_LABEL_VI.get(f["rule_code"], f["rule_code"])}
            for f in flags
        ],
        # Không gọi mô hình ở đây: hai lượt sinh mất ~25s, mà đây là endpoint chạy
        # mỗi lần Labcoach bấm mở một hồ sơ. Phần deterministic phải hiện ngay.
        # Diễn giải và tin nhắn nháp lấy qua /explain, khi có người thực sự cần.
        "llm_enabled": llm.is_enabled(CONFIG),
    }


@app.post("/api/admin/risk/{student_id}/explain")
def api_explain(
    student_id: str,
    _admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Diễn giải + tin nhắn nháp cho một ca, sinh khi có người bấm (§4.2).

    Là thao tác riêng chứ không nằm trong `/api/admin/risk/...` vì mô hình mất
    hàng chục giây, còn mức rủi ro và `rule_trace` thì phải hiện tức thì. Ai chỉ
    cần xem hồ sơ sẽ không phải trả cái giá đó.

    Trả 200 kèm `null` khi Ollama im lặng - đúng hợp đồng §6: mất phần diễn giải,
    không mất trang.
    """
    student = conn.execute(
        "SELECT * FROM students WHERE student_id = ?", (student_id.strip().upper(),)
    ).fetchone()
    if student is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy học viên")
    if not llm.is_enabled(CONFIG):
        raise HTTPException(status_code=503, detail="Tầng mô hình đang tắt.")

    risk = rules.compute_risk(conn, student["student_id"], CONFIG, today_str())
    return {
        "student_id": student["student_id"],
        "diagnosis": llm.write_diagnosis(risk.trace, CONFIG),
        "message": llm.draft_message(risk.trace, student["name"], CONFIG),
    }


@app.post("/api/admin/risk/{student_id}/mark-sent")
def api_mark_sent(
    student_id: str,
    request: Request,
    date: str | None = None,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    as_of = date or today_str()
    cur = conn.execute(
        "UPDATE risk_snapshots SET sent = 1, sent_at = ? WHERE student_id = ? AND date = ?",
        (now_ms(), student_id.strip().upper(), as_of),
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Chưa có snapshot cho học viên/ngày này")
    audit(
        conn, admin.subject, "mark_contacted", target=student_id.strip().upper(),
        detail=as_of, ip=req_ip(request),
    )
    conn.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# API danh sách lớp / flag / audit
# --------------------------------------------------------------------------
@app.get("/api/admin/roster")
def api_roster(
    _admin: Session = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
):
    rows = conn.execute(
        """SELECT s.student_id, s.name, s.email, s.active,
                  s.device_hash IS NOT NULL AS device_locked, s.device_locked_at,
                  substr(s.device_hash, 1, 8) AS device_short,
                  (SELECT COUNT(*) FROM attendance a
                    WHERE a.student_id = s.student_id AND a.call_index = 1
                      AND a.status != 'absent') AS attended,
                  (SELECT COUNT(*) FROM attendance a
                    WHERE a.student_id = s.student_id AND a.source = 'manual') AS manual_records,
                  (SELECT COUNT(*) FROM anomaly_flags f
                    WHERE f.student_id = s.student_id AND f.resolved = 0) AS open_flags,
                  (SELECT r.risk_level FROM risk_snapshots r
                    WHERE r.student_id = s.student_id
                    ORDER BY r.date DESC LIMIT 1) AS risk_level
           FROM students s ORDER BY s.student_id"""
    ).fetchall()
    closed = conn.execute(
        "SELECT COUNT(*) AS n FROM sessions WHERE state = 'closed'"
    ).fetchone()["n"]
    return {"students": rows_to_dicts(rows), "closed_sessions": closed}


# --------------------------------------------------------------------------
# Quản lý học viên
#
# Không có API xoá học viên, và đó là chủ ý: `attendance`, `anomaly_flags`,
# `risk_snapshots` đều tham chiếu tới `student_id`. Xoá một học viên là xoá luôn
# bằng chứng chuyên cần của họ - đúng thứ hệ thống này sinh ra để bảo vệ. Thay vào
# đó là flag `active`: ngưng theo dõi nhưng lịch sử còn nguyên và vẫn khiếu nại được.
# --------------------------------------------------------------------------
STUDENT_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,31}$")


def normalise_student_id(raw: str) -> str:
    sid = (raw or "").strip().upper()
    if not STUDENT_ID_RE.match(sid):
        raise HTTPException(
            status_code=422,
            detail="Mã học viên chỉ gồm chữ, số, dấu . _ - và dài 2-32 ký tự (ví dụ: K4001).",
        )
    return sid


def new_pin() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


class StudentIn(BaseModel):
    student_id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    email: str = Field(default="", max_length=128)
    pin: str = Field(default="", max_length=12)


@app.post("/api/admin/students")
def api_create_student(
    payload: StudentIn,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Thêm một học viên. PIN trả về **một lần duy nhất** - server chỉ giữ bản băm."""
    sid = normalise_student_id(payload.student_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Tên học viên không được để trống")

    pin = payload.pin.strip() or new_pin()
    if not pin.isdigit() or not (4 <= len(pin) <= 12):
        raise HTTPException(status_code=422, detail="PIN phải là 4-12 chữ số")

    pin_hash, pin_salt = hash_password(pin)
    try:
        conn.execute(
            """INSERT INTO students (student_id, name, email, pin_hash, pin_salt, active, created_at)
               VALUES (?,?,?,?,?,1,?)""",
            (sid, name, payload.email.strip() or None, pin_hash, pin_salt, now_ms()),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Mã học viên {sid} đã tồn tại")

    audit(conn, admin.subject, "create_student", target=sid, detail=name, ip=req_ip(request))
    conn.commit()
    return {"ok": True, "student_id": sid, "name": name, "pin": pin}


class StudentUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    email: str = Field(default="", max_length=128)


@app.post("/api/admin/students/{student_id}/update")
def api_update_student(
    student_id: str,
    payload: StudentUpdateIn,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Sửa tên / email. `student_id` **không đổi được** - nó là khoá của mọi bản ghi
    chuyên cần, đổi là mất liên kết với lịch sử."""
    sid = student_id.strip().upper()
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Tên học viên không được để trống")

    before = conn.execute("SELECT name, email FROM students WHERE student_id = ?", (sid,)).fetchone()
    if before is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy học viên")

    conn.execute(
        "UPDATE students SET name = ?, email = ? WHERE student_id = ?",
        (name, payload.email.strip() or None, sid),
    )
    audit(
        conn, admin.subject, "update_student", target=sid,
        detail=f"name: {before['name']} -> {name}", ip=req_ip(request),
    )
    conn.commit()
    return {"ok": True, "student_id": sid, "name": name}


class SetActiveIn(BaseModel):
    active: bool


@app.post("/api/admin/students/{student_id}/set-active")
def api_set_student_active(
    student_id: str,
    payload: SetActiveIn,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Ngưng / mở lại theo dõi. Không xoá: lịch sử chuyên cần phải giữ được."""
    sid = student_id.strip().upper()
    cur = conn.execute(
        "UPDATE students SET active = ? WHERE student_id = ?", (1 if payload.active else 0, sid)
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Không tìm thấy học viên")

    audit(
        conn, admin.subject, "set_student_active", target=sid,
        detail="active" if payload.active else "inactive", ip=req_ip(request),
    )
    conn.commit()
    return {"ok": True, "student_id": sid, "active": payload.active}


@app.post("/api/admin/students/{student_id}/reset-pin")
def api_reset_pin(
    student_id: str,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Cấp PIN mới khi học viên quên. Trả về một lần, không đọc lại được."""
    sid = student_id.strip().upper()
    pin = new_pin()
    pin_hash, pin_salt = hash_password(pin)
    cur = conn.execute(
        "UPDATE students SET pin_hash = ?, pin_salt = ? WHERE student_id = ?",
        (pin_hash, pin_salt, sid),
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Không tìm thấy học viên")

    GUARDS.sessions.destroy_subject(sid)  # phiên /me cũ chết theo PIN cũ
    audit(conn, admin.subject, "reset_student_pin", target=sid, ip=req_ip(request))
    conn.commit()
    return {"ok": True, "student_id": sid, "pin": pin}


class ImportIn(BaseModel):
    csv_text: str = Field(min_length=1, max_length=100_000)


@app.post("/api/admin/students/import")
def api_import_students(
    payload: ImportIn,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Nhập cả lớp từ CSV `mã,tên,email`.

    Kiểm **toàn bộ** trước khi ghi bất cứ dòng nào: nhập nửa chừng rồi báo lỗi thì
    Labcoach không biết đang ở trạng thái nào, và lần chạy lại sẽ đụng trùng mã.
    """
    rows, errors, seen = [], [], set()

    for line_no, raw in enumerate(payload.csv_text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in next(csv.reader([line]))]
        if parts and parts[0].lower() in ("student_id", "mã", "ma", "mã học viên"):
            continue  # dòng tiêu đề
        if len(parts) < 2 or not parts[0] or not parts[1]:
            errors.append({"line": line_no, "text": line[:80], "error": "cần ít nhất: mã,tên"})
            continue

        sid = parts[0].strip().upper()
        if not STUDENT_ID_RE.match(sid):
            errors.append({"line": line_no, "text": line[:80], "error": f"mã '{sid}' không hợp lệ"})
            continue
        if sid in seen:
            errors.append({"line": line_no, "text": line[:80], "error": f"trùng mã {sid} trong file"})
            continue
        if conn.execute("SELECT 1 FROM students WHERE student_id = ?", (sid,)).fetchone():
            errors.append({"line": line_no, "text": line[:80], "error": f"mã {sid} đã có trong lớp"})
            continue

        seen.add(sid)
        rows.append({"student_id": sid, "name": parts[1][:128],
                     "email": (parts[2][:128] if len(parts) > 2 and parts[2] else None)})

    if errors:
        return {"ok": False, "imported": 0, "errors": errors,
                "message": f"{len(errors)} dòng lỗi — chưa ghi dòng nào. Sửa rồi nhập lại."}
    if not rows:
        raise HTTPException(status_code=422, detail="Không có dòng nào để nhập")

    created = []
    ts = now_ms()
    for row in rows:
        pin = new_pin()
        pin_hash, pin_salt = hash_password(pin)
        conn.execute(
            """INSERT INTO students (student_id, name, email, pin_hash, pin_salt, active, created_at)
               VALUES (?,?,?,?,?,1,?)""",
            (row["student_id"], row["name"], row["email"], pin_hash, pin_salt, ts),
        )
        created.append({**row, "pin": pin})

    audit(
        conn, admin.subject, "import_students", target=f"{len(created)} học viên",
        detail=",".join(c["student_id"] for c in created[:20]), ip=req_ip(request),
    )
    conn.commit()
    return {"ok": True, "imported": len(created), "errors": [], "students": created}


class ReleaseDeviceIn(BaseModel):
    note: str = Field(default="", max_length=200)


@app.post("/api/admin/students/{student_id}/release-device")
def api_release_device(
    student_id: str,
    payload: ReleaseDeviceIn,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Xóa dữ liệu thiết bị của một mã học viên.

    Sau thao tác này học viên buộc được máy mới ở lần check-in kế tiếp, và máy vừa
    nhả cũng buộc được cho người khác (trường hợp máy mượn của lớp). Cả hai phía
    đều tự do trở lại - vì "một thiết bị một học viên" chặn theo cả hai chiều.

    Có ghi vết trong `device_bindings` và `audit_log`: đây là thao tác nới một lớp
    phòng vệ, nên phải trả lời được câu "ai nhả, lúc nào, vì sao".
    """
    try:
        result = devices.release(
            conn,
            student_id.strip().upper(),
            actor=admin.subject,
            note=payload.note,
            ip=req_ip(request),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Không tìm thấy học viên")
    conn.commit()
    return {"ok": True, **result}


@app.get("/api/admin/students/{student_id}/devices")
def api_student_devices(
    student_id: str,
    _admin: Session = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    sid = student_id.strip().upper()
    student = conn.execute(
        "SELECT student_id, name, device_hash, device_locked_at FROM students WHERE student_id = ?",
        (sid,),
    ).fetchone()
    if student is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy học viên")
    return {
        "student_id": student["student_id"],
        "name": student["name"],
        "current_device": devices.short(student["device_hash"]),
        "locked_at": student["device_locked_at"],
        "history": devices.binding_history(conn, sid),
    }


@app.get("/api/admin/anomalies")
def api_anomalies(
    resolved: int = 0,
    _admin: Session = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    rows = conn.execute(
        """SELECT f.*, s.name, ses.date, ses.start_time
           FROM anomaly_flags f
           LEFT JOIN students s ON s.student_id = f.student_id
           LEFT JOIN sessions ses ON ses.session_id = f.session_id
           WHERE f.resolved = ?
           ORDER BY CASE f.severity WHEN 'high' THEN 0 WHEN 'med' THEN 1 ELSE 2 END,
                    f.created_at DESC
           LIMIT 500""",
        (1 if resolved else 0,),
    ).fetchall()
    return {
        "flags": [
            {
                **dict(r),
                "label": rules.RULE_LABEL_VI.get(r["rule_code"], r["rule_code"]),
                "label_short": rules.RULE_LABEL_SHORT_VI.get(r["rule_code"], r["rule_code"]),
            }
            for r in rows
        ]
    }


@app.get("/api/admin/anomalies/grouped")
def api_anomalies_grouped(
    resolved: int = 0,
    _admin: Session = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Gộp flag theo (rule, học viên) kèm số lần.

    Vì sao gộp: một học viên rời lớp sớm 5 buổi sinh 5 flag EARLY_DEPARTURE giống nhau. Để
    nguyên thì hàng đợi đầy những dòng trùng, và Labcoach bỏ qua cả hàng đợi -
    đúng cái bẫy §1 mô tả: "số liệu không được ai đọc". Gộp theo *học viên* chứ
    không gộp theo rule, vì đơn vị cần xử lý là một con người, không phải một
    loại lỗi.
    """
    rows = conn.execute(
        """SELECT f.rule_code, f.student_id, f.severity,
                  s.name,
                  COUNT(*) AS occurrences,
                  MIN(f.created_at) AS first_at,
                  MAX(f.created_at) AS last_at,
                  GROUP_CONCAT(DISTINCT ses.date) AS dates,
                  MAX(f.id) AS latest_flag_id
           FROM anomaly_flags f
           LEFT JOIN students s ON s.student_id = f.student_id
           LEFT JOIN sessions ses ON ses.session_id = f.session_id
           WHERE f.resolved = ?
           GROUP BY f.rule_code, f.student_id
           ORDER BY CASE f.severity WHEN 'high' THEN 0 WHEN 'med' THEN 1 ELSE 2 END,
                    COUNT(*) DESC, MAX(f.created_at) DESC
           LIMIT 300""",
        (1 if resolved else 0,),
    ).fetchall()

    groups = []
    for row in rows:
        detail = conn.execute(
            """SELECT detail FROM anomaly_flags
               WHERE rule_code = ? AND student_id IS ? AND resolved = ?
               ORDER BY created_at DESC LIMIT 1""",
            (row["rule_code"], row["student_id"], 1 if resolved else 0),
        ).fetchone()
        item = dict(row)
        item["label"] = rules.RULE_LABEL_VI.get(row["rule_code"], row["rule_code"])
        item["label_short"] = rules.RULE_LABEL_SHORT_VI.get(row["rule_code"], row["rule_code"])
        item["latest_detail"] = detail["detail"] if detail else None
        item["dates"] = sorted(set((row["dates"] or "").split(","))) if row["dates"] else []
        groups.append(item)

    by_rule: dict[str, int] = {}
    for group in groups:
        by_rule[group["rule_code"]] = by_rule.get(group["rule_code"], 0) + group["occurrences"]

    return {
        "groups": groups,
        "totals": {
            "groups": len(groups),
            "flags": sum(g["occurrences"] for g in groups),
            "by_rule": by_rule,
        },
    }


class ResolveGroupIn(BaseModel):
    rule_code: str = Field(min_length=1, max_length=32)
    student_id: str | None = Field(default=None, max_length=32)
    note: str = Field(default="", max_length=300)


@app.post("/api/admin/anomalies/resolve-group")
def api_resolve_group(
    payload: ResolveGroupIn,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Xử lý cả nhóm flag giống nhau trong một lần.

    Bắt Labcoach bấm 17 lần cho 17 flag EARLY_DEPARTURE giống nhau thì kết quả thực tế là
    không ai bấm lần nào.
    """
    if payload.rule_code not in rules.RULE_SEVERITY:
        raise HTTPException(status_code=422, detail="Mã rule không hợp lệ")

    cur = conn.execute(
        """UPDATE anomaly_flags SET resolved = 1, resolved_by = ?, resolved_note = ?
           WHERE rule_code = ? AND student_id IS ? AND resolved = 0""",
        (admin.subject, payload.note, payload.rule_code, payload.student_id),
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Không còn flag nào chưa xử lý trong nhóm này")

    audit(
        conn, admin.subject, "resolve_flag_group",
        target=f"{payload.rule_code}@{payload.student_id or '-'}",
        detail=f"count={cur.rowcount};{payload.note}", ip=req_ip(request),
    )
    conn.commit()
    return {"ok": True, "resolved": cur.rowcount}


class ResolveIn(BaseModel):
    note: str = Field(default="", max_length=300)


@app.post("/api/admin/anomalies/{flag_id}/resolve")
def api_resolve_flag(
    flag_id: int,
    payload: ResolveIn,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    cur = conn.execute(
        """UPDATE anomaly_flags SET resolved = 1, resolved_by = ?, resolved_note = ?
           WHERE id = ? AND resolved = 0""",
        (admin.subject, payload.note, flag_id),
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Flag không tồn tại hoặc đã xử lý")
    audit(
        conn, admin.subject, "resolve_flag", target=str(flag_id),
        detail=payload.note, ip=req_ip(request),
    )
    conn.commit()
    return {"ok": True}


@app.get("/api/admin/audit")
def api_audit(
    limit: int = 200,
    _admin: Session = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?", (max(1, min(limit, 1000)),)
    ).fetchall()
    return {"entries": rows_to_dicts(rows)}


@app.get("/api/admin/export/attendance.csv")
def api_export_csv(
    _admin: Session = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
):
    rows = conn.execute(
        """SELECT a.id, s.date, s.start_time, a.student_id, st.name, a.call_index,
                  a.status, a.source, a.checkin_ts_ms, a.token_valid,
                  (SELECT GROUP_CONCAT(f.rule_code) FROM anomaly_flags f
                    WHERE f.attendance_id = a.id) AS flags
           FROM attendance a
           JOIN sessions s ON s.session_id = a.session_id
           JOIN students st ON st.student_id = a.student_id
           ORDER BY s.date, s.start_time, a.student_id, a.call_index"""
    ).fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["id", "date", "start_time", "student_id", "name", "call_index",
         "status", "source", "checkin_iso", "token_valid", "flags"]
    )
    for row in rows:
        writer.writerow(
            [
                row["id"], row["date"], row["start_time"], row["student_id"], row["name"],
                row["call_index"], row["status"], row["source"],
                datetime.fromtimestamp(row["checkin_ts_ms"] / 1000).isoformat(timespec="seconds"),
                row["token_valid"], row["flags"] or "",
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="attendance.csv"'},
    )


# --------------------------------------------------------------------------
# Tầng mô hình ngôn ngữ (§4.2)
# --------------------------------------------------------------------------
# Cửa kiểm tra SQL do mô hình sinh. Ba lớp, cố ý thừa:
#   1. Chỉ cho một câu, phải bắt đầu bằng SELECT hoặc WITH.
#   2. Chặn từ khoá ghi/DDL và các lệnh SQLite mở đường ra ngoài file db.
#   3. Chạy trên connection mở ở chế độ read-only của chính SQLite (`mode=ro`),
#      nên kể cả lọt qua hai lớp trên thì tầng driver vẫn từ chối mọi phép ghi.
# Lớp 3 mới là lớp thật; hai lớp trên để báo lỗi cho người dùng bằng tiếng Việt
# thay vì ném ra một exception của sqlite3.
_SQL_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|"
    r"reindex|analyze|begin|commit|rollback|savepoint)\b",
    re.IGNORECASE,
)


def _check_generated_sql(sql: str) -> str:
    """Trả về câu SQL đã chuẩn hoá, hoặc ném HTTPException 422 kèm lý do đọc được."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Mô hình không sinh được câu truy vấn.")
    if ";" in cleaned:
        raise HTTPException(status_code=422, detail="Chỉ chạy được một câu lệnh.")
    if not re.match(r"^\s*(select|with)\b", cleaned, re.IGNORECASE):
        raise HTTPException(status_code=422, detail="Chỉ chạy câu SELECT.")
    if _SQL_FORBIDDEN.search(cleaned):
        raise HTTPException(status_code=422, detail="Câu truy vấn chứa từ khoá không được phép.")
    return cleaned


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/api/admin/ask")
def api_ask(
    payload: AskIn,
    request: Request,
    admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Hỏi dữ liệu chuyên cần bằng tiếng Việt (§4.2).

    Trả về **cả câu SQL** chứ không chỉ kết quả. Labcoach phải nhìn được hệ thống
    đã hiểu câu hỏi thành cái gì - một bảng số không kèm câu truy vấn thì không
    kiểm chứng được, mà số liệu không kiểm chứng được là đúng thứ §1 nói tới.
    """
    if not llm.is_enabled(CONFIG):
        raise HTTPException(status_code=503, detail="Tầng mô hình đang tắt.")

    sql = llm.ask_sql(payload.question, CONFIG)
    if sql is None:
        raise HTTPException(status_code=503, detail="Ollama không phản hồi. Thử lại sau.")
    sql = _check_generated_sql(sql)

    # Kết nối riêng, mở read-only ở tầng SQLite. Không dùng `get_db` vì connection
    # đó ghi được.
    ro = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5.0)
    ro.row_factory = sqlite3.Row
    try:
        cur = ro.execute(sql)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(int(CONFIG["llm"].get("sql_row_limit", 200)))
    except sqlite3.Error as exc:
        raise HTTPException(status_code=422, detail=f"Câu truy vấn chạy lỗi: {exc}") from exc
    finally:
        ro.close()

    # Câu hỏi và câu SQL đã chạy đều vào audit: sau này có ai thắc mắc "con số đó
    # ở đâu ra" thì tra lại được đúng câu đã chạy, không phải đoán.
    audit(conn, admin.subject, "llm_ask",
          target=payload.question[:80], detail=sql[:200], ip=req_ip(request))
    conn.commit()

    return {"question": payload.question, "sql": sql, "columns": columns,
            "rows": rows_to_dicts(rows)}


class LeaveIn(BaseModel):
    text: str = Field(min_length=5, max_length=2000)


@app.post("/api/admin/parse-leave")
def api_parse_leave(
    payload: LeaveIn,
    _admin: Session = Depends(require_admin_write),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Bóc đơn xin phép viết tự do thành JSON có cấu trúc (§4.2).

    **Chỉ đề nghị, không ghi.** Labcoach soát rồi tự bấm điểm danh tay ở màn hình
    buổi học. Một dòng chuyên cần sai vì mô hình đọc nhầm ngày thì đúng bằng việc
    không có dòng nào.
    """
    if not llm.is_enabled(CONFIG):
        raise HTTPException(status_code=503, detail="Tầng mô hình đang tắt.")

    known = [r["student_id"] for r in conn.execute(
        "SELECT student_id FROM students WHERE active = 1 ORDER BY student_id"
    )]
    parsed = llm.parse_leave_request(payload.text, CONFIG, today=today_str(), known_student_ids=known)
    if parsed is None:
        raise HTTPException(status_code=503, detail="Ollama không phản hồi hoặc trả về sai định dạng.")

    # Đối chiếu mã học viên với danh sách lớp thật. Mô hình đọc ra một mã không có
    # trong lớp là chuyện thường (viết tắt, gõ nhầm) - nói ra chứ không im lặng nhận.
    sid = (parsed.get("student_id") or "").strip().upper() or None
    parsed["student_id"] = sid
    parsed["student_known"] = bool(sid and sid in known)
    return {"ok": True, "parsed": parsed, "note": "Đề nghị của mô hình — cần Labcoach xác nhận trước khi ghi."}


@app.get("/api/admin/llm-status")
def api_llm_status(_admin: Session = Depends(require_admin)):
    """Ollama sống chưa, model tải chưa. Để trang hỏi đáp báo đúng lý do khi hỏng."""
    return llm.health(CONFIG)


@app.get("/api/health")
def api_health(conn: sqlite3.Connection = Depends(get_db)):
    students = conn.execute("SELECT COUNT(*) AS n FROM students").fetchone()["n"]
    return {
        "ok": True,
        "students": students,
        "llm_enabled": llm.is_enabled(CONFIG),
        "subnet_enforced": bool(CONFIG["network"]["enforce_subnet"]),
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"ok": False, "error": exc.detail}, status_code=exc.status_code)
    if exc.status_code == 401:
        return RedirectResponse("/admin/login", status_code=303)
    return HTMLResponse(f"<h1>{exc.status_code}</h1><p>{exc.detail}</p>", status_code=exc.status_code)
