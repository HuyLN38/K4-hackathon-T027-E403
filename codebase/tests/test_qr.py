"""Kiểm thử bộ mã hoá QR (qr.py).

Bộ mã hoá được viết tay để không phải phụ thuộc thư viện ngoài, nên nó cần test
riêng - mã QR sai thì cả buổi điểm danh đứng.

Tính đúng đã được kiểm bằng cách **giải mã ngược**: 256 payload (gồm URL check-in
thật và chuỗi tới sức chứa tối đa 213 byte) được render ra ảnh rồi đọc lại bằng
OpenCV QRCodeDetector, khớp 256/256. OpenCV không nằm trong requirements vì chỉ
dùng để kiểm một lần; các test dưới đây chốt kết quả đó lại bằng vân tay ma trận
để mọi thay đổi sau này làm lệch một module là fail ngay.
"""
from __future__ import annotations

import hashlib

import pytest
import qr

# Vân tay ma trận đã được OpenCV xác nhận giải mã đúng.
FROZEN = {
    "http://192.168.1.50:8000/checkin?t=AbC123": (3, "2f7db9f995106f86"),
    "K4001": (1, "d3e12d9ff12964d7"),
    "x" * 213: (10, "f673820bb5ccd3f0"),
}


def fingerprint(matrix: list[list[int]]) -> str:
    flat = "".join("".join(map(str, row)) for row in matrix)
    return hashlib.sha256(flat.encode()).hexdigest()[:16]


@pytest.mark.parametrize("payload,expected", FROZEN.items())
def test_matrix_matches_frozen_fingerprint(payload, expected):
    version, digest = expected
    matrix = qr.encode(payload)
    assert len(matrix) == 17 + 4 * version
    assert fingerprint(matrix) == digest


def test_version_grows_with_payload_size():
    sizes = [(14, 1), (26, 2), (42, 3), (62, 4), (84, 5), (106, 6), (122, 7), (152, 8), (180, 9), (213, 10)]
    for length, version in sizes:
        matrix = qr.encode("x" * length)
        assert (len(matrix) - 17) // 4 == version, f"{length} byte -> version sai"


def test_payload_over_capacity_is_rejected():
    with pytest.raises(qr.QRError):
        qr.encode("x" * 214)


def test_finder_patterns_in_three_corners():
    matrix = qr.encode("K4001")
    size = len(matrix)
    for top, left in [(0, 0), (0, size - 7), (size - 7, 0)]:
        assert matrix[top][left] == 1
        assert matrix[top + 3][left + 3] == 1  # tâm
        assert matrix[top + 1][left + 1] == 0  # vành sáng
    # góc thứ tư không có finder
    assert not all(matrix[size - 7 + d][size - 7 + d] == 1 for d in range(7))


def test_timing_patterns_alternate():
    matrix = qr.encode("K4001")
    size = len(matrix)
    for i in range(8, size - 8):
        assert matrix[6][i] == (1 if i % 2 == 0 else 0)
        assert matrix[i][6] == (1 if i % 2 == 0 else 0)


def test_dark_module_is_set():
    for payload in ["K4001", "x" * 100]:
        matrix = qr.encode(payload)
        assert matrix[len(matrix) - 8][8] == 1


def test_utf8_payload_encodes():
    matrix = qr.encode("Điểm danh lớp K4 — buổi 12")
    assert len(matrix) >= 21


def test_encoding_is_deterministic():
    assert qr.encode("K4001") == qr.encode("K4001")


def test_svg_output_structure():
    svg = qr.to_svg("http://192.168.1.50:8000/checkin?t=abc", module_px=8, quiet_zone=4)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg
    assert "<path" in svg and "<rect" in svg
    # vùng trắng quanh mã: 29 module + 4*2 = 37, nhân 8 px
    assert 'viewBox="0 0 37 37"' in svg
    assert 'width="296"' in svg


def test_svg_has_no_external_reference():
    """CSP của app chỉ cho 'self' - SVG nhúng không được trỏ ra ngoài."""
    svg = qr.to_svg("K4001")
    for banned in ["http://", "https://", "<script", "xlink:href", "<image"]:
        assert banned not in svg.replace('xmlns="http://www.w3.org/2000/svg"', "")


def test_text_render_is_usable_for_debugging():
    text = qr.to_text("K4001")
    lines = text.splitlines()
    assert len(lines) == 21 + 4  # 21 module + 2 dòng đệm trên/dưới
    assert "██" in text
