"""Khởi động server cho lớp học.

    python run.py                 # bind 0.0.0.0:8000, cả LAN vào được
    python run.py --port 9000
    python run.py --host 127.0.0.1  # chỉ máy này, dùng khi chạy test

Bind 0.0.0.0 là cố ý: điện thoại học viên phải gọi được tới máy này. Lớp bảo vệ
không phải là "không ai thấy server" mà là middleware chặn subnet (§4.3 lớp 1).
"""
from __future__ import annotations

import argparse
import socket

import uvicorn

from db import init_db


def lan_ip() -> str:
    """IP LAN của máy này - in ra để Labcoach biết mở máy chiếu ở địa chỉ nào."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))  # không gửi gói nào, chỉ để lấy route
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Server chuyên cần lớp học")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    init_db()
    ip = lan_ip()
    print("=" * 62)
    print(f"  Học viên   : http://{ip}:{args.port}/")
    print(f"  Máy chiếu  : http://{ip}:{args.port}/projector")
    print(f"  Labcoach   : http://{ip}:{args.port}/admin")
    print("=" * 62)
    uvicorn.run("app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
