"""Xác thực, phân quyền và các lớp phòng vệ ở tầng HTTP.

Chứa lớp 1 (phạm vi mạng) và lớp 3 (buộc thiết bị) của §4.3, cộng phần bảo vệ
tài khoản Labcoach mà spec chưa nói tới nhưng thiếu thì toàn bộ dashboard hở.

Nguyên tắc về danh tính thiết bị: nửa quyết định nằm ở **cookie do server phát**
(HttpOnly, client không đọc được, không đặt được bằng JavaScript), nửa còn lại là
fingerprint do trình duyệt gửi lên. Chỉ sửa user-agent thì không tạo được thiết bị
mới - phải xoá cả cookie, và xoá cookie thì sinh flag DEVICE_MISMATCH. Cách này khiến
chi phí gian lận cao hơn lợi ích thu được (spec §5.2).
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware

ADMIN_COOKIE = "lc_session"
STUDENT_COOKIE = "hv_session"
# Đặt khi học viên bấm Đăng xuất ở /me. Không có cờ này thì trang tự nhận lại
# thiết bị ngay lập tức và nút Đăng xuất thành nút không làm gì.
NO_AUTO_COOKIE = "hv_noauto"
DEVICE_COOKIE = "dev_id"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "x-csrf-token"

PBKDF2_ROUNDS = 200_000


# --------------------------------------------------------------------------
# Mật khẩu / PIN
# --------------------------------------------------------------------------
def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS)
    return digest.hex(), salt


def verify_password(password: str, pw_hash: str, salt: str) -> bool:
    try:
        candidate, _ = hash_password(password, salt)
    except ValueError:
        return False
    return hmac.compare_digest(candidate, pw_hash)


# --------------------------------------------------------------------------
# Danh tính thiết bị (lớp 3)
# --------------------------------------------------------------------------
def compute_device_hash(server_device_id: str, client_fingerprint: str) -> str:
    """Trộn nửa server phát với nửa trình duyệt gửi lên.

    Chỉ lưu hash, không lưu fingerprint thô: fingerprint là dữ liệu cá nhân và
    hệ thống không cần đọc lại nó, chỉ cần so khớp.
    """
    material = f"{server_device_id}:{client_fingerprint or 'nofp'}".encode()
    return hashlib.sha256(material).hexdigest()


def compute_fp_hash(client_fingerprint: str) -> str | None:
    """Băm riêng phần fingerprint, không trộn cookie.

    Dùng để phát hiện hai *profile trình duyệt* trên cùng một máy: cookie khác nhau
    nên device_hash khác nhau, nhưng fingerprint thì giống. Chỉ để **gắn flag**,
    không để chặn - hai điện thoại cùng model cho fingerprint giống nhau, chặn theo
    tín hiệu này là chặn oan bạn cùng lớp.
    """
    if not client_fingerprint:
        return None
    return hashlib.sha256(f"fp::{client_fingerprint}".encode()).hexdigest()


def new_device_id() -> str:
    return secrets.token_urlsafe(24)


# --------------------------------------------------------------------------
# Phiên đăng nhập, lưu trong tiến trình
# --------------------------------------------------------------------------
@dataclass
class Session:
    subject: str
    kind: Literal["admin", "student"]
    role: str
    created_at: float
    expires_at: float
    csrf: str


class SessionStore:
    """Phiên lưu trong RAM: khởi động lại server là đăng xuất toàn bộ.

    Chọn cách này thay vì cookie tự chứng thực để Labcoach thu hồi được phiên
    ngay lập tức, và để không phải quản lý khoá bí mật trên máy lớp học.
    """

    def __init__(self, ttl_sec: int = 8 * 3600) -> None:
        self._sessions: dict[str, Session] = {}
        self._ttl = ttl_sec

    def create(self, subject: str, kind: Literal["admin", "student"], role: str = "") -> tuple[str, Session]:
        self._reap()
        sid = secrets.token_urlsafe(32)
        now = time.time()
        session = Session(
            subject=subject,
            kind=kind,
            role=role,
            created_at=now,
            expires_at=now + self._ttl,
            csrf=secrets.token_urlsafe(24),
        )
        self._sessions[sid] = session
        return sid, session

    def get(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        session = self._sessions.get(sid)
        if session is None:
            return None
        if session.expires_at < time.time():
            self._sessions.pop(sid, None)
            return None
        return session

    def destroy(self, sid: str | None) -> None:
        if sid:
            self._sessions.pop(sid, None)

    def destroy_subject(self, subject: str) -> int:
        victims = [sid for sid, s in self._sessions.items() if s.subject == subject]
        for sid in victims:
            self._sessions.pop(sid, None)
        return len(victims)

    def _reap(self) -> None:
        now = time.time()
        for sid in [sid for sid, s in self._sessions.items() if s.expires_at < now]:
            self._sessions.pop(sid, None)


# --------------------------------------------------------------------------
# Giới hạn tần suất - cửa sổ trượt trong RAM
# --------------------------------------------------------------------------
class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_sec: float) -> bool:
        """True nếu còn quota. Gọi một lần cho mỗi request cần đếm."""
        now = time.time()
        bucket = self._hits[key]
        cutoff = now - window_sec
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


# --------------------------------------------------------------------------
# Phạm vi mạng (lớp 1)
# --------------------------------------------------------------------------
def parse_subnets(entries: list[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    nets = []
    for entry in entries:
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue
    return nets


def ip_in_subnets(ip: str, nets: list[Any]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in nets)


def client_ip(request: Request, trust_proxy: bool = False) -> str:
    """IP dùng để xác định *phạm vi mạng*, không dùng để xác định *người* (§4.3).

    Chỉ đọc X-Forwarded-For khi cấu hình bật: header này client tự đặt được,
    tin nó mặc định là tự vô hiệu hoá lớp 1.
    """
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


class SubnetGuardMiddleware(BaseHTTPMiddleware):
    """Chỉ nhận request phát ra từ dải mạng của lớp."""

    def __init__(self, app: Any, config: dict[str, Any]) -> None:
        super().__init__(app)
        net_cfg = config["network"]
        self.enabled = bool(net_cfg["enforce_subnet"])
        self.trust_proxy = bool(net_cfg["trust_proxy_header"])
        self.nets = parse_subnets(net_cfg["allowed_subnets"])

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)
        ip = client_ip(request, self.trust_proxy)
        if not ip_in_subnets(ip, self.nets):
            body = {
                "ok": False,
                "error": "outside_class_network",
                "message": "Thiết bị không nằm trong dải mạng của lớp.",
                "ip": ip,
            }
            if request.url.path.startswith("/api/"):
                return JSONResponse(body, status_code=403)
            return PlainTextResponse(
                f"403 - Thiết bị {ip} không nằm trong dải mạng của lớp học.\n"
                "Điểm danh chỉ hoạt động khi bạn dùng WiFi trong phòng.",
                status_code=403,
            )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """CSP đóng kín: toàn bộ CSS/JS là file tĩnh cùng gốc, không có CDN."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; form-action 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; object-src 'none'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=(self)")
        response.headers.setdefault("Cache-Control", "no-store")
        return response


# --------------------------------------------------------------------------
# CSRF - double submit, gắn với phiên
# --------------------------------------------------------------------------
def csrf_ok(request: Request, session: Session) -> bool:
    sent = request.headers.get(CSRF_HEADER, "")
    return bool(sent) and hmac.compare_digest(sent, session.csrf)


@dataclass
class Guards:
    """Gom các thành phần trạng thái để app và test dùng chung một chỗ."""

    sessions: SessionStore = field(default_factory=SessionStore)
    rate: RateLimiter = field(default_factory=RateLimiter)
