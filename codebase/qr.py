"""Bộ mã hoá QR thuần Python - byte mode, mức sửa lỗi M, version 1-10.

Không phụ thuộc thư viện ngoài: máy chạy demo trong phòng lab có thể không có
mạng để cài package, mà màn hình máy chiếu là thứ không được phép hỏng.

Version 10 chứa được 213 byte - thừa cho URL check-in trong LAN.
Mức M sửa được ~15% module hỏng, đủ cho ảnh chụp màn hình máy chiếu chéo góc.

Đầu ra là SVG: nét sắc ở mọi độ phân giải máy chiếu, và nhúng thẳng vào HTML
được nên không cần thêm một lượt request ảnh.
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# GF(256), đa thức nguyên thuỷ 0x11D
# --------------------------------------------------------------------------
_EXP = [0] * 512
_LOG = [0] * 256


def _init_gf() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_gf()


def _mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator_poly(n: int) -> list[int]:
    g = [1]
    for i in range(n):
        nxt = [0] * (len(g) + 1)
        for j, coef in enumerate(g):
            nxt[j] ^= coef
            nxt[j + 1] ^= _mul(coef, _EXP[i])
        g = nxt
    return g


def _rs_ecc(data: list[int], n_ec: int) -> list[int]:
    g = _generator_poly(n_ec)
    rem = [0] * n_ec
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(n_ec):
            rem[i] ^= _mul(g[i + 1], factor)
    return rem


# --------------------------------------------------------------------------
# Bảng tham số, mức sửa lỗi M
#   version: (ecc_codewords_mỗi_block, [(số_block, data_codewords_mỗi_block), ...])
# --------------------------------------------------------------------------
_ECC_M: dict[int, tuple[int, list[tuple[int, int]]]] = {
    1: (10, [(1, 16)]),
    2: (16, [(1, 28)]),
    3: (26, [(1, 44)]),
    4: (18, [(2, 32)]),
    5: (24, [(2, 43)]),
    6: (16, [(4, 27)]),
    7: (18, [(4, 31)]),
    8: (22, [(2, 38), (2, 39)]),
    9: (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}

_ALIGN: dict[int, list[int]] = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
}

_REMAINDER_BITS: dict[int, int] = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}

_ECC_M_FORMAT_BITS = 0b00  # mức M


class QRError(ValueError):
    pass


# --------------------------------------------------------------------------
# Tầng dữ liệu
# --------------------------------------------------------------------------
def _count_bits(version: int) -> int:
    return 8 if version <= 9 else 16


def _total_data_codewords(version: int) -> int:
    _, groups = _ECC_M[version]
    return sum(count * size for count, size in groups)


def _choose_version(nbytes: int) -> int:
    for version in sorted(_ECC_M):
        need = 4 + _count_bits(version) + 8 * nbytes
        if need <= _total_data_codewords(version) * 8:
            return version
    raise QRError(f"Dữ liệu {nbytes} byte vượt sức chứa version 10 mức M (213 byte)")


def _encode_data(payload: bytes, version: int) -> list[int]:
    """Byte mode -> chuỗi codeword đã chèn đệm."""
    total_bits = _total_data_codewords(version) * 8
    bits: list[int] = []

    def push(value: int, width: int) -> None:
        for i in range(width - 1, -1, -1):
            bits.append((value >> i) & 1)

    push(0b0100, 4)  # chỉ báo byte mode
    push(len(payload), _count_bits(version))
    for byte in payload:
        push(byte, 8)

    push(0, min(4, total_bits - len(bits)))  # ký tự kết thúc
    while len(bits) % 8:
        bits.append(0)
    for i in range((total_bits - len(bits)) // 8):  # codeword đệm luân phiên
        push(0xEC if i % 2 == 0 else 0x11, 8)

    return [int("".join(str(b) for b in bits[i : i + 8]), 2) for i in range(0, len(bits), 8)]


def _interleave(codewords: list[int], version: int) -> list[int]:
    n_ec, groups = _ECC_M[version]
    blocks: list[list[int]] = []
    pos = 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(codewords[pos : pos + size])
            pos += size

    ecc_blocks = [_rs_ecc(block, n_ec) for block in blocks]

    out: list[int] = []
    for i in range(max(len(b) for b in blocks)):
        for block in blocks:
            if i < len(block):
                out.append(block[i])
    for i in range(n_ec):
        for ecc in ecc_blocks:
            out.append(ecc[i])
    return out


# --------------------------------------------------------------------------
# Tầng ma trận
# --------------------------------------------------------------------------
def _blank(size: int) -> tuple[list[list[int]], list[list[bool]]]:
    return [[0] * size for _ in range(size)], [[False] * size for _ in range(size)]


def _draw_finder(m: list[list[int]], res: list[list[bool]], top: int, left: int, size: int) -> None:
    for r in range(-1, 8):
        for c in range(-1, 8):
            rr, cc = top + r, left + c
            if not (0 <= rr < size and 0 <= cc < size):
                continue
            if 0 <= r < 7 and 0 <= c < 7:
                dark = r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4)
            else:
                dark = False  # vành phân cách
            m[rr][cc] = 1 if dark else 0
            res[rr][cc] = True


def _draw_function_patterns(version: int) -> tuple[list[list[int]], list[list[bool]]]:
    size = 17 + 4 * version
    m, res = _blank(size)

    _draw_finder(m, res, 0, 0, size)
    _draw_finder(m, res, 0, size - 7, size)
    _draw_finder(m, res, size - 7, 0, size)

    centers = _ALIGN[version]
    for r in centers:
        for c in centers:
            if (r < 8 and c < 8) or (r < 8 and c > size - 9) or (r > size - 9 and c < 8):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    m[r + dr][c + dc] = 0 if max(abs(dr), abs(dc)) == 1 else 1
                    res[r + dr][c + dc] = True

    for i in range(8, size - 8):  # timing pattern
        val = 1 if i % 2 == 0 else 0
        m[6][i], res[6][i] = val, True
        m[i][6], res[i][6] = val, True

    m[size - 8][8], res[size - 8][8] = 1, True  # dark module

    for i in range(9):  # vùng format
        res[8][i] = True
        res[i][8] = True
    for i in range(8):
        res[size - 1 - i][8] = True
        res[8][size - 1 - i] = True

    if version >= 7:  # vùng version info
        for i in range(18):
            res[i // 3][size - 11 + i % 3] = True
            res[size - 11 + i % 3][i // 3] = True

    return m, res


def _place_data(m: list[list[int]], res: list[list[bool]], data: list[int], version: int) -> None:
    size = len(m)
    bits: list[int] = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    bits.extend([0] * _REMAINDER_BITS[version])

    idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:  # bỏ qua cột timing dọc
            col -= 1
        for i in range(size):
            row = size - 1 - i if upward else i
            for cc in (col, col - 1):
                if not res[row][cc]:
                    m[row][cc] = bits[idx] if idx < len(bits) else 0
                    idx += 1
        upward = not upward
        col -= 2


_MASKS = [
    lambda i, j: (i + j) % 2 == 0,
    lambda i, j: i % 2 == 0,
    lambda i, j: j % 3 == 0,
    lambda i, j: (i + j) % 3 == 0,
    lambda i, j: (i // 2 + j // 3) % 2 == 0,
    lambda i, j: (i * j) % 2 + (i * j) % 3 == 0,
    lambda i, j: ((i * j) % 2 + (i * j) % 3) % 2 == 0,
    lambda i, j: ((i + j) % 2 + (i * j) % 3) % 2 == 0,
]


def _apply_mask(m: list[list[int]], res: list[list[bool]], pattern: int) -> list[list[int]]:
    rule = _MASKS[pattern]
    return [
        [cell ^ 1 if not res[i][j] and rule(i, j) else cell for j, cell in enumerate(row)]
        for i, row in enumerate(m)
    ]


def _penalty(m: list[list[int]]) -> int:
    size = len(m)
    score = 0

    # Quy tắc 1: dãy >=5 module cùng màu
    for line in list(m) + [list(col) for col in zip(*m)]:
        run_val, run_len = line[0], 1
        for cell in line[1:]:
            if cell == run_val:
                run_len += 1
            else:
                if run_len >= 5:
                    score += 3 + (run_len - 5)
                run_val, run_len = cell, 1
        if run_len >= 5:
            score += 3 + (run_len - 5)

    # Quy tắc 2: khối 2x2 cùng màu
    for i in range(size - 1):
        for j in range(size - 1):
            if m[i][j] == m[i][j + 1] == m[i + 1][j] == m[i + 1][j + 1]:
                score += 3

    # Quy tắc 3: hoa văn giống finder pattern
    p1 = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    p2 = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for line in list(m) + [list(col) for col in zip(*m)]:
        for j in range(size - 10):
            window = line[j : j + 11]
            if window == p1 or window == p2:
                score += 40

    # Quy tắc 4: tỉ lệ module tối lệch khỏi 50%
    dark = sum(sum(row) for row in m)
    percent = dark * 100 / (size * size)
    score += 10 * (int(abs(percent - 50)) // 5)

    return score


def _format_bits(mask: int) -> int:
    fmt = (_ECC_M_FORMAT_BITS << 3) | mask
    rem = fmt << 10
    for i in range(4, -1, -1):
        if rem & (1 << (i + 10)):
            rem ^= 0b10100110111 << i
    return ((fmt << 10) | rem) ^ 0b101010000010010


def _place_format(m: list[list[int]], mask: int) -> None:
    """Ghi 15 bit format vào hai bản sao, bit cao nhất trước."""
    size = len(m)
    bits = _format_bits(mask)
    for i in range(15):
        bit = (bits >> (14 - i)) & 1
        # bản sao 1: vòng quanh finder trái trên
        if i < 6:
            m[8][i] = bit
        elif i == 6:
            m[8][7] = bit
        elif i == 7:
            m[8][8] = bit
        elif i == 8:
            m[7][8] = bit
        else:
            m[14 - i][8] = bit
        # bản sao 2: cột dưới finder trái dưới, rồi hàng cạnh finder phải trên.
        # Chỉ 7 ô ở nhánh dưới - ô thứ 8 là dark module, không phải bit format.
        if i < 7:
            m[size - 1 - i][8] = bit
        else:
            m[8][size - 15 + i] = bit


def _place_version(m: list[list[int]], version: int) -> None:
    if version < 7:
        return
    size = len(m)
    rem = version << 12
    for i in range(5, -1, -1):
        if rem & (1 << (i + 12)):
            rem ^= 0b1111100100101 << i
    bits = (version << 12) | rem
    for i in range(18):
        bit = (bits >> i) & 1
        m[i // 3][size - 11 + i % 3] = bit
        m[size - 11 + i % 3][i // 3] = bit


def encode(payload: str | bytes, version: int | None = None) -> list[list[int]]:
    """Trả về ma trận QR, 1 = module tối."""
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    version = version or _choose_version(len(data))
    if version not in _ECC_M:
        raise QRError(f"Chỉ hỗ trợ version 1-10, nhận {version}")

    codewords = _interleave(_encode_data(data, version), version)
    m, res = _draw_function_patterns(version)
    _place_data(m, res, codewords, version)

    best, best_score = None, None
    for mask in range(8):
        candidate = _apply_mask(m, res, mask)
        _place_format(candidate, mask)
        _place_version(candidate, version)
        score = _penalty(candidate)
        if best_score is None or score < best_score:
            best, best_score = candidate, score
    assert best is not None
    return best


# --------------------------------------------------------------------------
# Kết xuất
# --------------------------------------------------------------------------
def to_svg(
    payload: str | bytes,
    module_px: int = 8,
    quiet_zone: int = 4,
    dark: str = "#000000",
    light: str = "#ffffff",
) -> str:
    """SVG nhúng thẳng vào HTML - không cần request ảnh riêng."""
    matrix = encode(payload)
    size = len(matrix)
    total = size + quiet_zone * 2
    px = total * module_px

    segments: list[str] = []
    for r, row in enumerate(matrix):
        c = 0
        while c < size:
            if row[c]:
                start = c
                while c < size and row[c]:
                    c += 1
                segments.append(f"M{start + quiet_zone} {r + quiet_zone}h{c - start}v1h-{c - start}z")
            else:
                c += 1

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{px}" height="{px}" '
        f'viewBox="0 0 {total} {total}" shape-rendering="crispEdges" role="img" '
        f'aria-label="Mã QR điểm danh">'
        f'<rect width="{total}" height="{total}" fill="{light}"/>'
        f'<path fill="{dark}" d="{"".join(segments)}"/>'
        f"</svg>"
    )


def to_text(payload: str | bytes) -> str:
    """Kết xuất terminal - tiện khi debug không có trình duyệt."""
    matrix = encode(payload)
    pad = "  " * (len(matrix) + 4)
    lines = [pad, pad]
    for row in matrix:
        lines.append("    " + "".join("██" if cell else "  " for cell in row) + "    ")
    lines.extend([pad, pad])
    return "\n".join(lines)
