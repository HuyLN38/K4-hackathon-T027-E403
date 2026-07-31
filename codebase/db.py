"""Lớp truy cập SQLite.

Mọi câu lệnh đều dùng tham số hoá (?) - không nối chuỗi SQL từ input người dùng.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BASE_DIR / "schema.sql"

# Cho phép trỏ sang database/config khác qua biến môi trường. Dùng cho test (mỗi
# lần chạy một DB riêng) và cho trường hợp một máy phục vụ nhiều lớp.
DB_PATH = Path(os.environ.get("ATTENDANCE_DB") or BASE_DIR / "attendance.db")
CONFIG_PATH = Path(os.environ.get("ATTENDANCE_CONFIG") or BASE_DIR / "config.json")

_config_cache: dict[str, Any] | None = None


def now_ms() -> int:
    return int(time.time() * 1000)


def load_config(reload: bool = False) -> dict[str, Any]:
    """Ngưỡng cố định đọc từ config.json (spec §4.7)."""
    global _config_cache
    if _config_cache is None or reload:
        _config_cache = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return _config_cache


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Mở một connection cho một request.

    `check_same_thread=False` là bắt buộc, không phải tuỳ chọn: FastAPI chạy
    dependency đồng bộ (`get_db`) ở một thread của threadpool rồi chạy thân
    endpoint ở thread khác, nên connection luôn có khả năng bị dùng ở thread khác
    thread đã tạo ra nó. Để mặc định thì mỗi khi có hai request chạy song song sẽ
    có request đổ 500 `SQLite objects created in a thread can only be used in that
    same thread` - và lớp 40 người quét QR cùng lúc thì đó là chuyện chắc chắn xảy
    ra, không phải rủi ro xa.

    An toàn ở đây vì hai lẽ: mỗi request dùng connection riêng của mình và các
    thread chạy *tuần tự* trong một request (dependency -> endpoint -> cleanup),
    không bao giờ đồng thời; và `sqlite3.threadsafety == 3` (serialized) trên bản
    SQLite đang dùng. Ghi đồng thời từ nhiều request do WAL + busy_timeout lo.
    """
    conn = sqlite3.connect(str(db_path or DB_PATH), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def query(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return conn.execute(sql, tuple(params)).fetchall()


def query_one(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return conn.execute(sql, tuple(params)).fetchone()


def execute(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    return conn.execute(sql, tuple(params))


def audit(
    conn: sqlite3.Connection,
    actor: str,
    action: str,
    target: str | None = None,
    detail: str | None = None,
    ip: str | None = None,
) -> None:
    """Ghi vết mọi hành động đổi trạng thái - phục vụ khiếu nại bản ghi chuyên cần."""
    conn.execute(
        "INSERT INTO audit_log (ts, actor, action, target, detail, ip) VALUES (?,?,?,?,?,?)",
        (now_ms(), actor, action, target, detail, ip),
    )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
