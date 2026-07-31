"""Khởi tạo database.

**Mặc định chỉ tạo tài khoản Labcoach, không tạo học viên nào.** Lớp thật thì danh
sách học viên nhập từ giao diện (thêm từng người, hoặc dán CSV `mã,tên,email`), và
40 cái tên bịa lẫn vào danh sách thật là thứ rất khó gỡ ra sau - `student_id` khoá
mọi bản ghi chuyên cần nên không xoá học viên được, chỉ ngưng theo dõi.

`--demo-data` sinh thêm bộ dữ liệu giả: 40 học viên × 20 buổi, có cài sẵn pattern.
Dữ liệu **giả hoàn toàn**, không lấy từ `data/` và không phải người thật. Cần bộ
này khi demo, và khi chạy `eval/run_llm_eval.py` - bộ eval đó đo trên `attendance.db`
thật chứ không tự dựng dữ liệu như `run_eval.py`.

Cách sinh dữ liệu giả: mô phỏng lại đúng luồng check-in thật theo thứ tự thời gian,
rồi gọi `rules.evaluate_checkin` / `rules.detect_early_departures`. Flag bất thường
vì thế do chính rule engine sinh ra, không phải chèn tay - nếu rule sai thì dữ liệu
seed sai theo, và đó là điều muốn: seed đồng thời là một phép thử rule.

Chạy:
    python seed_fake_data.py --reset                  # chỉ Labcoach
    python seed_fake_data.py --reset --demo-data      # kèm 40 học viên giả
    python seed_fake_data.py --reset --admin-password 'mật-khẩu-của-bạn'
"""
from __future__ import annotations

import argparse
import hashlib
import random
import secrets
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import devices
import rules
from db import DB_PATH, connect, init_db, load_config, now_ms
from rules import session_start_ms
from security import hash_password

CFG = load_config()
RNG = random.Random(20260730)

HO = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Vũ", "Đặng", "Bùi", "Đỗ"]
DEM = ["Văn", "Thị", "Hữu", "Đức", "Minh", "Thanh", "Quang", "Ngọc", "Gia", "Khánh"]
TEN = [
    "An", "Bình", "Chi", "Dũng", "Duyên", "Giang", "Hà", "Hải", "Hạnh", "Hiếu",
    "Hoa", "Huy", "Khoa", "Lam", "Linh", "Long", "Mai", "Nam", "Nga", "Nhung",
    "Phong", "Phúc", "Quân", "Quyên", "Sơn", "Tâm", "Thảo", "Thắng", "Trang", "Trung",
    "Tuấn", "Uyên", "Vân", "Việt", "Vy", "Xuân", "Yến", "Đạt", "Kiên", "Ngân",
]

# Bảy kiểu hành vi, phân bố để bản tin đầu ngày có đủ ca ok / watch / at_risk.
ARCHETYPES = (
    ["ok"] * 22
    + ["watch_absent2", "watch_late3", "watch_increasing"] * 2
    + ["at_risk_absent3", "at_risk_silent_after_late", "at_risk_early_departure"] * 4
)


def make_names(n: int) -> list[str]:
    """Tên tiếng Việt, cố tình có trùng tên để kiểm chứng §5.5 (đối chiếu theo mã)."""
    names = []
    for i in range(n):
        names.append(f"{RNG.choice(HO)} {RNG.choice(DEM)} {TEN[i % len(TEN)]}")
    names[7] = names[3]  # hai học viên trùng tên hoàn toàn
    return names


def device_hash_for(student_id: str) -> str:
    return hashlib.sha256(f"seed-device::{student_id}".encode()).hexdigest()


def plan_for(archetype: str, idx: int, total_sessions: int) -> dict[int, tuple[str, int]]:
    """Kịch bản 5 buổi cuối: {chỉ số buổi -> (trạng thái, số phút trễ)}.

    Chỉ 5 buổi cuối được cài pattern vì cửa sổ rủi ro là 5 buổi (§4.7). Các buổi
    trước đó cho hành vi bình thường để lịch sử trông thật.
    """
    last5 = list(range(total_sessions - 5, total_sessions))
    plan: dict[int, tuple[str, int]] = {}

    if archetype == "ok":
        if idx % 3 == 0:
            plan[last5[1]] = ("late", 12)
    elif archetype == "watch_absent2":
        plan[last5[1]] = ("absent", 0)
        plan[last5[3]] = ("absent", 0)
    elif archetype == "watch_late3":
        for i in (0, 2, 4):
            plan[last5[i]] = ("late", 15)
    elif archetype == "watch_increasing":
        for i, minutes in zip((1, 2, 3), (7, 15, 24)):
            plan[last5[i]] = ("late", minutes)
    elif archetype == "at_risk_absent3":
        for i in (0, 2, 4):
            plan[last5[i]] = ("absent", 0)
    elif archetype == "at_risk_silent_after_late":
        # Chính là ca G07 trong spec §7.1: trễ tăng dần rồi im lặng hai buổi.
        for i, minutes in zip((0, 1, 2), (6, 14, 21)):
            plan[last5[i]] = ("late", minutes)
        plan[last5[3]] = ("absent", 0)
        plan[last5[4]] = ("absent", 0)
    elif archetype == "at_risk_early_departure":
        plan[last5[1]] = ("early_departure", 0)
        plan[last5[3]] = ("early_departure", 0)
    return plan


def describe_existing() -> dict[str, int] | None:
    """Đếm dữ liệu đang có trong database, None nếu database chưa tồn tại."""
    if not DB_PATH.exists():
        return None
    conn = connect()
    try:
        counts = {}
        for table in ("students", "sessions", "attendance", "anomaly_flags"):
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except Exception:
                counts[table] = 0
        return counts
    finally:
        conn.close()


def backup_db() -> Path:
    """Sao lưu trước khi xoá. Bản ghi chuyên cần có thể bị khiếu nại, nên một lệnh
    gõ nhầm không được phép là đường một chiều."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = DB_PATH.with_name(f"{DB_PATH.name}.bak-{stamp}")
    shutil.copy2(DB_PATH, target)
    return target


def wipe_db() -> None:
    DB_PATH.unlink()
    for suffix in ("-wal", "-shm"):
        extra = Path(str(DB_PATH) + suffix)
        if extra.exists():
            extra.unlink()


def write_credentials(admin_password: str, pins: dict[str, str]) -> Path:
    """Ghi file mật khẩu **cạnh database**, không phải cạnh script.

    Bản trước chốt đường dẫn theo `__file__`, nên một lần chạy thử với
    `ATTENDANCE_DB` trỏ sang database tạm vẫn đè lên file mật khẩu của database
    thật - và PIN học viên chỉ lưu bản băm nên không lấy lại được. File mật khẩu
    phải đi theo database mà nó mô tả.
    """
    creds = DB_PATH.parent / f"{DB_PATH.stem}_credentials.txt"
    if DB_PATH.name == "attendance.db":
        creds = DB_PATH.parent / "seed_credentials.txt"   # giữ tên cũ cho db mặc định
    lines = [
        "# Tài khoản khởi tạo - KHÔNG commit file này (đã có trong .gitignore)",
        f"labcoach / {admin_password}",
    ]
    if pins:
        lines += ["", "# PIN học viên (trang /me)",
                  *[f"{sid} / {pin}" for sid, pin in pins.items()]]
    creds.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return creds


def seed(
    reset: bool,
    admin_password: str | None,
    assume_yes: bool = False,
    demo_data: bool = False,
) -> None:
    """Khởi tạo database.

    Mặc định chỉ tạo **tài khoản Labcoach** trên một database trống: lớp thật thì
    danh sách học viên nhập từ giao diện (thêm từng người hoặc dán CSV), và 40 cái
    tên bịa lẫn vào danh sách thật là thứ rất khó gỡ ra sau.

    `demo_data=True` sinh lại bộ dữ liệu giả đầy đủ (40 học viên × 20 buổi có cài
    sẵn pattern) - cần cho việc demo và cho `eval/run_llm_eval.py`, vì bộ eval đó
    chạy trên `attendance.db` thật chứ không tự dựng dữ liệu như `run_eval.py`.
    """
    existing = describe_existing()
    has_data = bool(existing and existing["students"])

    if not reset and has_data:
        print(
            "Database đã có dữ liệu:\n"
            f"  {existing['students']} học viên · {existing['sessions']} buổi · "
            f"{existing['attendance']} bản ghi điểm danh · {existing['anomaly_flags']} flag\n\n"
            "Script này chỉ sinh dữ liệu vào database TRỐNG. Chọn một trong hai:\n"
            "  • Giữ dữ liệu đang có  -> không cần chạy gì cả, cứ `python run.py`\n"
            "  • Bỏ hết và sinh lại   -> `python seed_fake_data.py --reset`\n",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if reset and has_data:
        # Xoá dữ liệu chuyên cần là không đảo ngược được. Bắt xác nhận và luôn
        # sao lưu trước - một lệnh gõ nhầm lúc 8h sáng không được phép mất cả khoá.
        print(
            "SẮP XOÁ TOÀN BỘ database hiện tại:\n"
            f"  {existing['students']} học viên · {existing['sessions']} buổi · "
            f"{existing['attendance']} bản ghi điểm danh · {existing['anomaly_flags']} flag"
        )
        saved = backup_db()
        print(f"  Đã sao lưu: {saved.name}")
        if not assume_yes:
            if input("  Gõ 'xoa' để xác nhận: ").strip().lower() != "xoa":
                print("Đã huỷ, không xoá gì cả.")
                raise SystemExit(1)
        wipe_db()
    elif reset and DB_PATH.exists():
        wipe_db()  # database rỗng, xoá thẳng không cần hỏi

    init_db()
    conn = connect()
    total_sessions = 20
    ts = now_ms()

    # ---------------- tài khoản Labcoach ----------------
    admin_password = admin_password or secrets.token_urlsafe(9)
    pw_hash, pw_salt = hash_password(admin_password)
    conn.execute(
        """INSERT INTO admins (username, display_name, pw_hash, pw_salt, role, created_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(username) DO UPDATE SET pw_hash = excluded.pw_hash,
                                               pw_salt = excluded.pw_salt""",
        ("labcoach", "Labcoach lớp K4", pw_hash, pw_salt, "owner", ts),
    )

    # Đường mặc định dừng ở đây: database có Labcoach, chưa có học viên nào.
    if not demo_data:
        conn.commit()
        conn.close()
        creds = write_credentials(admin_password, {})
        print("Đã tạo tài khoản Labcoach. Chưa có học viên nào - đó là chủ ý.")
        print("\nThêm học viên ở  Danh sách lớp: từng người, hoặc dán CSV `mã,tên,email`.")
        print("Muốn bộ dữ liệu giả để demo:  python seed_fake_data.py --reset --demo-data")
        print(f"\nTài khoản Labcoach:  labcoach / {admin_password}")
        print(f"Đã ghi: {creds}")
        return

    # ---------------- học viên ----------------
    names = make_names(40)
    students = []
    pins = {}
    for i, name in enumerate(names, start=1):
        student_id = f"K4{i:03d}"
        pin = f"{RNG.randint(0, 999999):06d}"
        pin_hash, pin_salt = hash_password(pin)
        pins[student_id] = pin
        archetype = ARCHETYPES[(i - 1) % len(ARCHETYPES)]
        students.append({"student_id": student_id, "name": name, "archetype": archetype})
        conn.execute(
            """INSERT INTO students
               (student_id, name, email, pin_hash, pin_salt, active, created_at)
               VALUES (?,?,?,?,?,1,?)""",
            (student_id, name, f"{student_id.lower()}@example.invalid", pin_hash, pin_salt, ts),
        )

    # ---------------- buổi học ----------------
    session_ids = []
    today = date.today()
    day = today - timedelta(days=1)
    dates: list[date] = []
    while len(dates) < total_sessions:
        if day.weekday() < 5:  # chỉ ngày trong tuần
            dates.append(day)
        day -= timedelta(days=1)
    dates.reverse()

    for d in dates:
        cur = conn.execute(
            """INSERT INTO sessions (date, start_time, room, state, late_after_min)
               VALUES (?,?,?,'scheduled',?)""",
            (d.isoformat(), "09:00", "Lab A", int(CFG["checkin"]["late_after_min"])),
        )
        session_ids.append(cur.lastrowid)
    conn.commit()

    # Buổi hôm nay để demo trực tiếp: để trạng thái scheduled, Labcoach tự mở.
    conn.execute(
        """INSERT INTO sessions (date, start_time, room, state, late_after_min)
           VALUES (?,?,?,'scheduled',?)""",
        (today.isoformat(), "09:00", "Lab A", int(CFG["checkin"]["late_after_min"])),
    )
    conn.commit()

    plans = {
        s["student_id"]: plan_for(s["archetype"], i, total_sessions)
        for i, s in enumerate(students)
    }

    # ---------------- phát lại luồng check-in theo thứ tự thời gian ----------------
    device_reuse_session = session_ids[total_sessions - 4]
    ip_spike_session = session_ids[total_sessions - 2]
    grace_session = session_ids[total_sessions - 3]
    manual_session = session_ids[total_sessions - 5]

    for s_idx, session_id in enumerate(session_ids):
        session_row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        start_ms = session_start_ms(session_row["date"], session_row["start_time"])
        conn.execute(
            "UPDATE sessions SET state = 'open', opened_at = ?, call_index = 1 WHERE session_id = ?",
            (start_ms, session_id),
        )

        present_call1: list[str] = []
        for st_idx, student in enumerate(students):
            student_id = student["student_id"]
            planned = plans[student_id].get(s_idx)
            behaviour, late_min = planned if planned else ("present", 0)

            if behaviour == "absent":
                continue

            if behaviour == "late":
                offset_ms = late_min * 60_000
            else:
                offset_ms = RNG.randint(-6, 8) * 60_000  # tới sớm/đúng giờ

            checkin_ts = start_ms + offset_ms
            device_hash = device_hash_for(student_id)
            ip = f"192.168.1.{20 + st_idx}"
            token_in_grace = False

            # --- pattern cài sẵn ---
            if session_id == device_reuse_session and st_idx == 5:
                # Mượn máy của bạn để điểm danh. Rule mới CHẶN trước khi ghi, nên
                # kết quả thật là: một flag DEVICE_REUSE không gắn vào bản ghi nào, rồi
                # Labcoach điểm danh tay. Dựng đúng chuỗi đó thay vì chèn một bản
                # ghi web mà luồng thật không còn tạo ra được.
                # (Flag được gắn ở cuối, sau bước nhả thiết bị - nhả sẽ đóng mọi flag
                #  DEVICE_REUSE/DEVICE_MISMATCH còn treo của học viên đó.)
                conn.execute(
                    """INSERT INTO attendance
                       (student_id, session_id, checkin_ts_ms, call_index, ip, device_hash,
                        token_valid, token_id, status, source, manual_reason, manual_by)
                       VALUES (?,?,?,1,NULL,NULL,0,NULL,'present','manual',?,'labcoach')""",
                    (
                        student_id, session_id, checkin_ts,
                        "Thiết bị đã buộc cho mã khác / chờ nhả thiết bị — mượn máy của bạn",
                    ),
                )
                present_call1.append(student_id)
                continue
            if session_id == ip_spike_session and st_idx in (10, 11, 12):
                ip = "192.168.1.77"
                checkin_ts = start_ms + 120_000 + st_idx  # dồn trong vài giây
            if session_id == grace_session and st_idx in (3, 17):
                token_in_grace = True
            # Một ca mất điện thoại, điểm danh tay - để bản demo có sẵn bản ghi tay.
            if session_id == manual_session and st_idx == 8:
                conn.execute(
                    """INSERT INTO attendance
                       (student_id, session_id, checkin_ts_ms, call_index, ip, device_hash,
                        token_valid, token_id, status, source, manual_reason, manual_by)
                       VALUES (?,?,?,1,NULL,NULL,0,NULL,?,'manual',?,'labcoach')""",
                    (
                        student_id, session_id, checkin_ts, "present",
                        "Mất / không mang điện thoại — để máy ở nhà",
                    ),
                )
                present_call1.append(student_id)
                continue

            status = rules.classify_status(
                session_row, checkin_ts, int(session_row["late_after_min"])
            )
            cur = conn.execute(
                """INSERT INTO attendance
                   (student_id, session_id, checkin_ts_ms, call_index, ip, device_hash,
                    token_valid, token_id, status, source, user_agent)
                   VALUES (?,?,?,1,?,?,1,NULL,?,'web','seed/1.0')""",
                (student_id, session_id, checkin_ts, ip, device_hash, status),
            )
            attendance_id = cur.lastrowid

            locked = conn.execute(
                "SELECT device_hash FROM students WHERE student_id = ?", (student_id,)
            ).fetchone()["device_hash"]
            if not locked:
                devices.bind(conn, student_id, device_hash)

            rules.evaluate_checkin(conn, attendance_id, CFG, token_in_grace=token_in_grace)
            present_call1.append(student_id)

        # --- lượt điểm danh thứ hai, thời điểm ngẫu nhiên giữa buổi ---
        second_ts = start_ms + RNG.randint(45, 95) * 60_000
        conn.execute(
            "UPDATE sessions SET call_index = 2, second_call_ts = ? WHERE session_id = ?",
            (second_ts, session_id),
        )
        for student_id in present_call1:
            behaviour = (plans[student_id].get(s_idx) or ("present", 0))[0]
            if behaviour == "early_departure":
                continue  # đầu giờ có, giữa giờ không -> rule EARLY_DEPARTURE sẽ bắt
            if RNG.random() < 0.005:
                continue  # nhiễu tự nhiên: thỉnh thoảng có người về sớm thật
            conn.execute(
                """INSERT INTO attendance
                   (student_id, session_id, checkin_ts_ms, call_index, ip, device_hash,
                    token_valid, token_id, status, source, user_agent)
                   VALUES (?,?,?,2,?,?,1,NULL,'present','web','seed/1.0')""",
                (
                    student_id,
                    session_id,
                    second_ts + RNG.randint(5, 240) * 1000,
                    f"192.168.1.{20 + next(i for i, s in enumerate(students) if s['student_id'] == student_id)}",
                    device_hash_for(student_id),
                ),
            )

        conn.execute(
            "UPDATE sessions SET state = 'closed', closed_at = ? WHERE session_id = ?",
            (second_ts + 3_600_000, session_id),
        )
        conn.commit()
        rules.detect_early_departures(conn, session_id)
        conn.commit()

    # ---------------- nhả thiết bị ----------------
    # Lịch sử ở trên dùng device_hash tổng hợp, nên nếu để nguyên thì mọi học viên
    # đang bị buộc vào một thiết bị không tồn tại: điện thoại thật vào sẽ bị chặn
    # ngay lần đầu và không ai demo được.
    # Đi qua devices.release() chứ không UPDATE thẳng, để lịch sử device_bindings
    # có cả vế nhả - màn hình hồ sơ học viên nhờ đó có dữ liệu thật để hiện.
    # Các dòng attendance cũ vẫn giữ device_hash của chúng, nên flag trong lịch sử
    # không mất.
    for student in students:
        devices.release(
            conn, student["student_id"], actor="seed",
            note="khởi tạo dữ liệu giả - nhả để thiết bị thật buộc được ở buổi demo",
        )
    conn.commit()

    # ---------------- hai lần thử bị chặn ở lớp 3 ----------------
    # Gắn sau bước nhả, vì nhả thiết bị đóng mọi flag DEVICE_REUSE/DEVICE_MISMATCH còn
    # treo. Cả hai đều là flag "chặn trước khi ghi": attendance_id NULL, đúng thứ
    # luồng thật sinh ra khi một thiết bị bị dùng cho hai người.
    rules.raise_flag(
        conn, None, device_reuse_session, students[5]["student_id"], "DEVICE_REUSE",
        f"Chặn check-in: thiết bị đã buộc cho {students[4]['student_id']}",
    )
    # Ca này không được điểm danh tay nên thành vắng - cho thấy vì sao cần đường thoát.
    rules.raise_flag(
        conn, None, grace_session, students[28]["student_id"], "DEVICE_MISMATCH",
        "Chặn check-in: thiết bị khác thiết bị đã buộc, chờ Labcoach nhả thiết bị",
    )
    conn.commit()

    # ---------------- bản tin đầu ngày ----------------
    top = rules.build_briefing(conn, CFG, date.today().isoformat(), actor="seed")

    counts = conn.execute(
        """SELECT risk_level, COUNT(*) AS n FROM risk_snapshots
           WHERE date = ? GROUP BY risk_level""",
        (date.today().isoformat(),),
    ).fetchall()
    flags = conn.execute(
        "SELECT rule_code, COUNT(*) AS n FROM anomaly_flags GROUP BY rule_code ORDER BY rule_code"
    ).fetchall()
    attendance_rows = conn.execute("SELECT COUNT(*) AS n FROM attendance").fetchone()["n"]
    conn.close()

    creds = write_credentials(admin_password, pins)

    print(f"Đã sinh {len(students)} học viên, {total_sessions} buổi đã đóng + 1 buổi hôm nay.")
    print(f"Bản ghi attendance: {attendance_rows}")
    print("Mức rủi ro hôm nay: " + ", ".join(f"{r['risk_level']}={r['n']}" for r in counts))
    print("Flag bất thường: " + ", ".join(f"{r['rule_code']}={r['n']}" for r in flags))
    print(f"Bản tin đầu ngày: {len(top)} ca ưu tiên")
    print(f"\nTài khoản Labcoach:  labcoach / {admin_password}")
    print(f"Toàn bộ PIN học viên: {creds}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Khởi tạo database. Mặc định chỉ tạo tài khoản Labcoach."
    )
    parser.add_argument("--reset", action="store_true", help="xoá database cũ trước khi sinh")
    parser.add_argument("--admin-password", default=None, help="mật khẩu Labcoach (mặc định: sinh ngẫu nhiên)")
    parser.add_argument("--yes", action="store_true",
                        help="bỏ qua bước xác nhận khi xoá (dùng cho script tự động)")
    parser.add_argument("--demo-data", action="store_true",
                        help="sinh thêm 40 học viên giả × 20 buổi có cài sẵn pattern "
                             "(để demo và để chạy eval/run_llm_eval.py)")
    args = parser.parse_args()
    seed(reset=args.reset, admin_password=args.admin_password, assume_yes=args.yes,
         demo_data=args.demo_data)
