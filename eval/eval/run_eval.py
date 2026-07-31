"""Chạy golden set qua bộ phân loại rủi ro (spec §7.3).

    python eval/run_eval.py

Chạy **3 lượt** và ghi ra `results_run{1,2,3}.csv` cùng một bảng tổng hợp có độ
lệch giữa các lượt, theo đúng quy trình §7.3.

Một điểm phải nói thẳng: bản dựng này **tắt tầng mô hình ngôn ngữ**, nên thứ đang
được đo là phần deterministic. Ba lượt vì thế cho kết quả giống nhau và độ lệch
bằng 0 - đó không phải thành tích, chỉ là hệ quả của việc không có gì ngẫu nhiên
trong đường đo. Ba lượt vẫn được giữ vì nó chứng minh đúng điều đó: 100% ở hạng
mục "phân loại rủi ro khớp nhãn" là do không có random, chứ không phải do chọn
lượt tốt nhất. Các hạng mục về chẩn đoán và tin nhắn trong §7.2 chưa đo được, và
được báo là chưa đo chứ không được cho điểm.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
CODEBASE = EVAL_DIR.parent / "codebase"
sys.path.insert(0, str(CODEBASE))

# DB tạm, phải đặt trước khi import db
_TMP = Path(tempfile.mkdtemp(prefix="eval-"))
os.environ["ATTENDANCE_DB"] = str(_TMP / "eval.db")

import rules  # noqa: E402
from db import connect, init_db, load_config, now_ms  # noqa: E402
from rules import session_start_ms  # noqa: E402

CFG = load_config()
AS_OF = "2026-08-01"
FIRST_DAY = date(2026, 7, 20)
RUNS = 3


def load_cases() -> list[dict]:
    with (EVAL_DIR / "golden_set.jsonl").open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_case(conn, student_id: str, case: dict) -> None:
    conn.execute(
        "INSERT INTO students (student_id, name, active, created_at) VALUES (?,?,1,?)",
        (student_id, f"Ca {case['case_id']}", now_ms()),
    )
    for offset, (status, late_min) in enumerate(case["pattern"]):
        day = (FIRST_DAY + timedelta(days=offset)).isoformat()
        row = conn.execute(
            "SELECT session_id FROM sessions WHERE date = ? AND start_time = '09:00'", (day,)
        ).fetchone()
        if row is None:
            cur = conn.execute(
                """INSERT INTO sessions (date, start_time, room, state, late_after_min)
                   VALUES (?, '09:00', 'Lab A', 'closed', 10)""",
                (day,),
            )
            session_id = cur.lastrowid
            start_ms = session_start_ms(day, "09:00")
            conn.execute(
                "UPDATE sessions SET opened_at=?, closed_at=?, second_call_ts=? WHERE session_id=?",
                (start_ms, start_ms + 7_200_000, start_ms + 3_600_000, session_id),
            )
        else:
            session_id = row["session_id"]

        if status != "absent":
            conn.execute(
                """INSERT INTO attendance
                   (student_id, session_id, checkin_ts_ms, call_index, ip, device_hash,
                    token_valid, token_id, status, source)
                   VALUES (?,?,?,1,'192.168.1.9',?,1,NULL,?,'web')""",
                (
                    student_id,
                    session_id,
                    session_start_ms(day, "09:00") + late_min * 60_000,
                    f"dev-{student_id}",
                    status,
                ),
            )

    # flag EARLY_DEPARTURE cài sẵn, gắn vào các buổi đầu của cửa sổ
    sessions = conn.execute(
        "SELECT session_id FROM sessions ORDER BY date LIMIT ?", (case["early_departure_flags"],)
    ).fetchall()
    for session in sessions:
        rules.raise_flag(conn, None, session["session_id"], student_id, "EARLY_DEPARTURE", "golden set")
    conn.commit()


def run_once(run_index: int, cases: list[dict]) -> list[dict]:
    db_path = _TMP / f"eval-run{run_index}.db"
    if db_path.exists():
        db_path.unlink()
    os.environ["ATTENDANCE_DB"] = str(db_path)

    import db as db_module

    db_module.DB_PATH = db_path
    init_db(db_path)
    conn = connect(db_path)

    results = []
    for index, case in enumerate(cases, start=1):
        student_id = f"E{index:03d}"
        build_case(conn, student_id, case)
        outcome = rules.compute_risk(conn, student_id, CFG, AS_OF)
        fired = {s["code"] for s in outcome.trace["signals"]}

        missing = [c for c in case["expected_signals"] if c not in fired]
        forbidden_hit = [c for c in case.get("forbidden_signals", []) if c in fired]
        level_ok = outcome.level == case["expected_risk"]

        results.append(
            {
                "case_id": case["case_id"],
                "input_log": case["input_log"],
                "expected_risk": case["expected_risk"],
                "actual_risk": outcome.level,
                "risk_match": int(level_ok),
                "expected_signals": "|".join(case["expected_signals"]),
                "fired_signals": "|".join(sorted(fired)),
                "missing_signals": "|".join(missing),
                "forbidden_fired": "|".join(forbidden_hit),
                "signals_ok": int(not missing and not forbidden_hit),
                "pass": int(level_ok and not missing and not forbidden_hit),
            }
        )

    conn.close()
    return results


def write_csv(path: Path, results: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)


def main() -> int:
    cases = load_cases()
    distribution: dict[str, int] = {}
    for case in cases:
        distribution[case["expected_risk"]] = distribution.get(case["expected_risk"], 0) + 1

    print(f"Golden set: {len(cases)} ca — phân bố nhãn {distribution}")
    print(f"Tầng mô hình ngôn ngữ: {'BẬT' if CFG['llm']['enabled'] else 'TẮT'}\n")

    all_runs = []
    for run_index in range(1, RUNS + 1):
        results = run_once(run_index, cases)
        write_csv(EVAL_DIR / f"results_run{run_index}.csv", results)
        risk_rate = sum(r["risk_match"] for r in results) / len(results)
        signal_rate = sum(r["signals_ok"] for r in results) / len(results)
        overall = sum(r["pass"] for r in results) / len(results)
        all_runs.append(results)
        print(
            f"Lượt {run_index}: nhãn rủi ro {risk_rate:.0%} · tín hiệu {signal_rate:.0%} · "
            f"tổng {overall:.0%}  -> results_run{run_index}.csv"
        )

    # Độ lệch giữa các lượt
    print("\nĐộ lệch giữa các lượt")
    print("-" * 72)
    unstable = []
    for i, case in enumerate(cases):
        levels = {run[i]["actual_risk"] for run in all_runs}
        if len(levels) > 1:
            unstable.append((case["case_id"], levels))
    if unstable:
        for case_id, levels in unstable:
            print(f"  {case_id}: {sorted(levels)}")
    else:
        print("  Không có ca nào lệch giữa 3 lượt (đường đo không có thành phần ngẫu nhiên).")

    # Bảng chỉ tiêu §7.2
    final = all_runs[-1]
    failures = [r for r in final if not r["pass"]]
    print("\nChỉ tiêu §7.2")
    print("-" * 72)
    risk_rate = sum(r["risk_match"] for r in final) / len(final)
    print(f"  Phân loại rủi ro khớp nhãn      ngưỡng 100%   đo được {risk_rate:.0%}"
          f"   {'ĐẠT' if risk_rate == 1 else 'KHÔNG ĐẠT'}")
    signal_rate = sum(r["signals_ok"] for r in final) / len(final)
    print(f"  Tín hiệu giải thích đúng         ngưỡng 100%   đo được {signal_rate:.0%}"
          f"   {'ĐẠT' if signal_rate == 1 else 'KHÔNG ĐẠT'}")
    print("  Chẩn đoán nêu đúng tín hiệu      ngưỡng >=80%  -> eval/run_llm_eval.py")
    print("  Tin nhắn qua message_must        ngưỡng >=85%  -> eval/run_llm_eval.py")
    print("  Không bịa thông tin ngoài log    ngưỡng 100%   -> eval/run_llm_eval.py")

    if failures:
        print(f"\n{len(failures)} ca KHÔNG ĐẠT")
        print("-" * 72)
        for row in failures:
            print(f"  {row['case_id']}  {row['input_log']}")
            print(f"      nhãn: mong {row['expected_risk']} / thực {row['actual_risk']}")
            if row["missing_signals"]:
                print(f"      thiếu tín hiệu: {row['missing_signals']}")
            if row["forbidden_fired"]:
                print(f"      tín hiệu không được có: {row['forbidden_fired']}")
        return 1

    print(f"\nTất cả {len(cases)} ca ĐẠT trên cả {RUNS} lượt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
