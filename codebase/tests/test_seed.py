"""Khởi tạo database: mặc định chỉ Labcoach, dữ liệu giả là tuỳ chọn.

Hai test cuối giữ một lỗi đã thực sự gây mất dữ liệu: `write_credentials()` từng
chốt đường dẫn theo `__file__`, nên một lần chạy thử với `ATTENDANCE_DB` trỏ sang
database tạm vẫn đè lên file mật khẩu của database thật - và PIN học viên chỉ lưu
bản băm nên mất là mất hẳn.
"""
from __future__ import annotations

import subprocess
import sqlite3
import sys
from pathlib import Path

import pytest
from conftest import CODEBASE


def run_seed(db_path: Path, *extra: str):
    """Chạy seed như người dùng thật chạy: một tiến trình riêng, DB riêng."""
    env = {"ATTENDANCE_DB": str(db_path), "PATH": "/usr/bin:/bin",
           "HOME": str(Path.home())}
    res = subprocess.run(
        [sys.executable, "seed_fake_data.py", "--reset", "--yes", *extra],
        cwd=CODEBASE, env=env, capture_output=True, text=True, timeout=300,
    )
    assert res.returncode == 0, res.stderr
    return res


def counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("admins", "students", "sessions", "attendance", "anomaly_flags")}
    finally:
        conn.close()


def test_default_creates_only_the_labcoach_account(tmp_path):
    db = tmp_path / "t.db"
    run_seed(db)
    c = counts(db)
    assert c["admins"] == 1
    assert c["students"] == 0, "mặc định không được tự tạo học viên"
    assert c["sessions"] == 0
    assert c["attendance"] == 0


def test_demo_data_flag_still_generates_the_full_class(tmp_path):
    """Bộ dữ liệu giả vẫn phải dựng được: eval/run_llm_eval.py chạy trên nó."""
    db = tmp_path / "t.db"
    run_seed(db, "--demo-data")
    c = counts(db)
    assert c["students"] == 40
    assert c["sessions"] >= 20
    assert c["attendance"] > 500
    assert c["anomaly_flags"] > 0, "seed phải sinh flag qua chính rule engine"


def test_credentials_file_follows_the_database_not_the_script(tmp_path):
    """Chạy với database tạm KHÔNG được đụng vào file mật khẩu của database thật.

    Đây là lỗi đã làm mất PIN của cả lớp một lần.
    """
    real = CODEBASE / "seed_credentials.txt"
    before = real.read_bytes() if real.exists() else None

    db = tmp_path / "t.db"
    run_seed(db)

    assert (tmp_path / "t_credentials.txt").exists(), "phải ghi cạnh database tạm"
    after = real.read_bytes() if real.exists() else None
    assert after == before, "file mật khẩu của database thật đã bị ghi đè"


def test_credentials_file_lists_no_student_pins_without_demo_data(tmp_path):
    db = tmp_path / "t.db"
    run_seed(db)
    text = (tmp_path / "t_credentials.txt").read_text(encoding="utf-8")
    assert "labcoach /" in text
    assert "PIN học viên" not in text, "không có học viên thì không có mục PIN"
