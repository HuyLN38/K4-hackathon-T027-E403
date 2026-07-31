"""Đo tầng mô hình ngôn ngữ theo chỉ tiêu §7.2.

Ba chỉ tiêu spec đặt ra cho tầng này:

  - Chẩn đoán nêu đúng tín hiệu quyết định        >= 80%
  - Tin nhắn qua hết `message_must`                >= 85%
  - Không bịa thông tin ngoài log                  = 100%

Cách chấm ở đây là **đối chiếu cơ học**, không phải mô hình chấm mô hình: mỗi con
số xuất hiện trong câu trả lời phải tìm được trong `rule_trace` của chính ca đó.
Chấm bằng mô hình thì hai mô hình cùng sai một kiểu sẽ cùng cho điểm cao.

Chạy trên dữ liệu thật trong `attendance.db` chứ không phải golden set tổng hợp:
`rule_trace` là thứ tầng mô hình thực sự nhận vào lúc chạy thật.

    python eval/run_llm_eval.py            # tất cả ca watch + at_risk
    python eval/run_llm_eval.py --limit 5
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

CODEBASE = Path(__file__).resolve().parent.parent / "codebase"
sys.path.insert(0, str(CODEBASE))

import llm  # noqa: E402
import rules  # noqa: E402
from db import connect, load_config  # noqa: E402

# Từ ngữ mang giọng cảnh cáo / nhắc quy chế - `message_must_not` của §7.2.
FORBIDDEN = [
    "cảnh cáo", "kỷ luật", "cấm thi", "quy chế", "vi phạm", "buộc thôi học",
    "đình chỉ", "trừ điểm", "hậu quả", "nghiêm khắc", "yêu cầu giải trình",
]
# Xưng hô bắt buộc.
ADDRESS = ["em"]

# Ngân sách latency §7.2 cho một ca.
LATENCY_BUDGET_SEC = 8.0


def numbers_in(text: str) -> set[int]:
    """Mọi số nguyên xuất hiện trong câu, bỏ số nằm trong ngày dd/mm."""
    without_dates = re.sub(r"\b\d{1,2}/\d{1,2}\b", " ", text)
    return {int(n) for n in re.findall(r"\b\d+\b", without_dates)}


def grounded_numbers(trace: dict, cfg: dict) -> set[int]:
    """Tập số hợp lệ: mọi con số có thật trong rule_trace hoặc trong ngưỡng cấu hình.

    Hai nhóm dưới đây từng bị bộ chấm này báo nhầm là "bịa":

    - **Ngưỡng cấu hình** (`late_after_min` = 10). Nó nằm trong bảng dữ kiện đưa
      cho mô hình ("đến trễ từ 10 phút trở lên"), nên mô hình nhắc lại là đúng.
    - **Ngày viết tắt.** Câu "ngày 24, 28 và 30/07" là tiếng Việt bình thường,
      nhưng regex ngày chỉ bắt "30/07"; 24 và 28 rơi xuống thành số trần. Nên
      phải nhận cả ngày-trong-tháng của các buổi có trong lịch sử.
    """
    counts = trace.get("counts", {})
    ok = {
        counts.get("absent", 0), counts.get("late", 0), counts.get("sessions_considered", 0),
        trace.get("absence_streak", 0), trace.get("increasing_lateness_streak", 0),
        trace.get("early_departure_flags", 0), len(trace.get("history", [])),
        int(cfg.get("checkin", {}).get("late_after_min", 10)),
        int(cfg.get("risk", {}).get("window_sessions", 5)),
    }
    for s in trace.get("signals", []):
        ok.add(s.get("value"))
        ok.add(s.get("threshold"))
    for h in trace.get("history", []):
        if h.get("late_min"):
            ok.add(h["late_min"])
        date = h.get("date") or ""
        if len(date) >= 10:
            ok.add(int(date[8:10]))   # ngày trong tháng
            ok.add(int(date[5:7]))    # tháng
    return {int(n) for n in ok if isinstance(n, (int, float))}


def dates_in(text: str) -> set[str]:
    return set(re.findall(r"\b(\d{1,2}/\d{1,2})\b", text))


def grounded_dates(trace: dict) -> set[str]:
    out = set()
    for h in trace.get("history", []):
        d = h.get("date") or ""
        if len(d) >= 10:
            out.add(f"{int(d[8:10])}/{int(d[5:7])}")
            out.add(f"{d[8:10]}/{d[5:7]}")
    return out


def check_case(student_id: str, name: str, trace: dict, diagnosis: str, message: str,
               cfg: dict) -> dict:
    res = {"student_id": student_id, "problems": []}
    allowed_n, allowed_d = grounded_numbers(trace, cfg), grounded_dates(trace)

    # --- 1. chẩn đoán có nêu tín hiệu quyết định không ---
    decisive = [s for s in trace.get("signals", []) if s.get("tier") == trace.get("level")]
    if diagnosis and decisive:
        # Coi là "nêu đúng" khi câu chẩn đoán chứa giá trị đo được của ít nhất một
        # tín hiệu quyết định - đó là con số Labcoach cần thấy.
        res["diagnosis_names_signal"] = any(
            str(s.get("value")) in diagnosis for s in decisive
        )
    else:
        res["diagnosis_names_signal"] = bool(diagnosis) and not decisive

    # --- 2. tin nhắn qua message_must ---
    low = (message or "").lower()
    res["msg_address"] = any(w in low.split() or f" {w} " in f" {low} " for w in ADDRESS)
    res["msg_concrete"] = bool(dates_in(message or "") or numbers_in(message or ""))
    res["msg_open_question"] = "?" in (message or "")
    res["msg_no_threat"] = not any(w in low for w in FORBIDDEN)
    res["message_ok"] = all(
        [res["msg_address"], res["msg_concrete"], res["msg_open_question"], res["msg_no_threat"]]
    )

    # --- 3. không bịa: mọi số / ngày phải có trong rule_trace ---
    for label, text in (("chẩn đoán", diagnosis or ""), ("tin nhắn", message or "")):
        for n in numbers_in(text) - allowed_n:
            res["problems"].append(f"{label}: số {n} không có trong log")
        for d in dates_in(text) - allowed_d:
            res["problems"].append(f"{label}: ngày {d} không có trong log")
    res["grounded"] = not res["problems"]
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Đo tầng mô hình theo §7.2")
    ap.add_argument("--limit", type=int, default=0, help="chỉ chạy N ca đầu")
    ap.add_argument("--as-of", default="2026-07-30")
    args = ap.parse_args()

    cfg = load_config()
    if not llm.is_enabled(cfg):
        print("Tầng mô hình đang TẮT trong config.json — không đo được.")
        return 2
    hp = llm.health(cfg)
    if not hp["reachable"] or not hp["model_ready"]:
        print(f"Ollama chưa sẵn sàng: {hp}")
        return 2

    conn = connect()
    students = [r["student_id"] for r in conn.execute(
        "SELECT student_id FROM students WHERE active = 1 ORDER BY student_id")]

    cases = []
    for sid in students:
        risk = rules.compute_risk(conn, sid, cfg, args.as_of)
        if risk.level != "ok":
            row = conn.execute("SELECT name FROM students WHERE student_id = ?", (sid,)).fetchone()
            cases.append((sid, row["name"], risk))
    if args.limit:
        cases = cases[: args.limit]

    print(f"Model: {hp['model']} · {len(cases)} ca (watch + at_risk) · tính đến {args.as_of}")
    print("=" * 74)

    results = []
    for i, (sid, name, risk) in enumerate(cases, 1):
        t0 = time.perf_counter()
        diagnosis = llm.write_diagnosis(risk.trace, cfg)
        t1 = time.perf_counter()
        message = llm.draft_message(risk.trace, name, cfg)
        t2 = time.perf_counter()
        r = check_case(sid, name, risk.trace, diagnosis or "", message or "", cfg)
        # §7.2 đo latency "mỗi ca". Một ca = một câu chẩn đoán, vì đó là thứ sinh
        # ra cho mọi ca trong bản tin. Tin nhắn đo riêng: nó chỉ sinh khi Labcoach
        # thực sự định nhắn cho người đó.
        r["sec_diagnosis"] = t1 - t0
        r["sec_message"] = t2 - t1
        # Giữ nguyên văn hai đoạn model sinh ra. Với eval của mô hình ngôn ngữ thì
        # chính câu chữ là bằng chứng: một điểm số không cho ai kiểm lại được là
        # bạn đang tin bộ chấm chứ không phải tin mô hình.
        r["name"] = name
        r["level"] = risk.level
        r["diagnosis"] = diagnosis or ""
        r["message"] = message or ""
        results.append(r)
        mark = "OK " if (r["diagnosis_names_signal"] and r["message_ok"] and r["grounded"]) else "XEM"
        print(f"[{i:>2}/{len(cases)}] {mark} {sid} {name} ({risk.level})"
              f"  chẩn đoán {r['sec_diagnosis']:.1f}s · tin nhắn {r['sec_message']:.1f}s")
        if not r["grounded"]:
            for p in r["problems"]:
                print(f"          ! {p}")
        if not r["message_ok"]:
            miss = [k.replace("msg_", "") for k in
                    ("msg_address", "msg_concrete", "msg_open_question", "msg_no_threat")
                    if not r[k]]
            print(f"          ! tin nhắn thiếu: {', '.join(miss)}")

    n = len(results) or 1
    pct = lambda key: 100.0 * sum(1 for r in results if r[key]) / n  # noqa: E731
    d_pct, m_pct, g_pct = pct("diagnosis_names_signal"), pct("message_ok"), pct("grounded")

    diag_times = sorted(r["sec_diagnosis"] for r in results)
    msg_times = sorted(r["sec_message"] for r in results)
    p95 = diag_times[min(len(diag_times) - 1, int(len(diag_times) * 0.95))]
    mean = sum(diag_times) / len(diag_times)

    print("\nChỉ tiêu §7.2")
    print("-" * 74)
    for label, got, need in (
        ("Chẩn đoán nêu đúng tín hiệu", d_pct, 80.0),
        ("Tin nhắn qua message_must", m_pct, 85.0),
        ("Không bịa thông tin ngoài log", g_pct, 100.0),
    ):
        print(f"  {label:<34} ngưỡng >={need:>5.0f}%   đo được {got:>5.1f}%   "
              f"{'ĐẠT' if got >= need else 'CHƯA ĐẠT'}")
    # Ngưỡng latency bám vào p95 chứ không phải trung bình: một ca chậm gấp ba
    # vẫn làm người dùng bỏ đi, mà trung bình thì giấu mất ca đó.
    print(f"  {'Latency mỗi ca (chẩn đoán, p95)':<34} ngưỡng <={LATENCY_BUDGET_SEC:>4.0f}s   "
          f"đo được {p95:>5.1f}s   {'ĐẠT' if p95 <= LATENCY_BUDGET_SEC else 'CHƯA ĐẠT'}")
    print(f"\n  chẩn đoán: trung bình {mean:.1f}s · nhanh nhất {diag_times[0]:.1f}s · "
          f"chậm nhất {diag_times[-1]:.1f}s")
    print(f"  tin nhắn : trung bình {sum(msg_times)/len(msg_times):.1f}s · "
          f"chậm nhất {msg_times[-1]:.1f}s")

    ok = d_pct >= 80 and m_pct >= 85 and g_pct >= 100 and p95 <= LATENCY_BUDGET_SEC

    # Ghi kết quả ra file để dashboard đọc lại.
    #
    # Không có bước này thì con số §7.2 chỉ tồn tại trong terminal của người vừa
    # chạy - tức là với người dùng app, cả tầng eval coi như không tồn tại. Kèm
    # mốc thời gian và tên model để không ai nhìn một con số cũ mà tưởng là số của
    # bản đang chạy.
    payload = {
        "measured_at": time.time(),
        "model": hp["model"],
        "cases": len(results),
        "as_of": args.as_of,
        "criteria": [
            {"label": "Chẩn đoán nêu đúng tín hiệu", "unit": "%", "value": round(d_pct, 1),
             "threshold": 80.0, "compare": "gte", "ok": d_pct >= 80},
            {"label": "Tin nhắn qua message_must", "unit": "%", "value": round(m_pct, 1),
             "threshold": 85.0, "compare": "gte", "ok": m_pct >= 85},
            {"label": "Không bịa thông tin ngoài log", "unit": "%", "value": round(g_pct, 1),
             "threshold": 100.0, "compare": "gte", "ok": g_pct >= 100},
            {"label": "Latency mỗi ca (p95)", "unit": "s", "value": round(p95, 1),
             "threshold": LATENCY_BUDGET_SEC, "compare": "lte", "ok": p95 <= LATENCY_BUDGET_SEC},
        ],
        "all_ok": ok,
    }
    # Chi tiết từng ca đi kèm, để mở dashboard là đọc được model đã viết gì và ca
    # nào hỏng ở đâu - không phải chạy lại script rồi đọc terminal.
    payload["cases_detail"] = [
        {
            "student_id": r["student_id"], "name": r["name"], "level": r["level"],
            "diagnosis": r["diagnosis"], "message": r["message"],
            "diagnosis_names_signal": r["diagnosis_names_signal"],
            "message_ok": r["message_ok"], "grounded": r["grounded"],
            "problems": r["problems"],
            "message_missing": [
                k.replace("msg_", "") for k in
                ("msg_address", "msg_concrete", "msg_open_question", "msg_no_threat")
                if not r[k]
            ],
            "sec_diagnosis": round(r["sec_diagnosis"], 1),
            "sec_message": round(r["sec_message"], 1),
        }
        for r in results
    ]

    eval_dir = Path(__file__).resolve().parent
    out = eval_dir / "llm_eval_latest.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV mở được bằng Excel, mỗi ca một dòng kèm nguyên văn model sinh ra.
    csv_path = eval_dir / "llm_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(payload["cases_detail"][0].keys()))
        writer.writeheader()
        for row in payload["cases_detail"]:
            writer.writerow({**row, "problems": " | ".join(row["problems"]),
                             "message_missing": " | ".join(row["message_missing"])})

    # Lịch sử: MỖI LẦN CHẠY MỘT DÒNG, ghi thêm chứ không ghi đè.
    #
    # Cần vì chỉ tiêu "không bịa" dao động: cùng một model, có lượt 100%, có lượt
    # 95.5%. Một lần chạy không phải sự thật về chất lượng, phân bố qua nhiều lượt
    # mới là. Không có file này thì không ai biết con số đang xem là lượt may hay
    # lượt xấu.
    history = eval_dir / "llm_eval_history.jsonl"
    with history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "measured_at": payload["measured_at"], "model": payload["model"],
            "cases": payload["cases"],
            **{c["label"]: c["value"] for c in payload["criteria"]},
            "all_ok": ok,
        }, ensure_ascii=False) + "\n")

    runs = sum(1 for _ in history.open(encoding="utf-8"))
    print(f"\nĐã ghi:")
    print(f"  {out.name:<26} tổng hợp + chi tiết từng ca (trang Trợ lý đọc file này)")
    print(f"  {csv_path.name:<26} mỗi ca một dòng, kèm nguyên văn model sinh ra")
    print(f"  {history.name:<26} lịch sử {runs} lượt chạy, để theo dõi dao động")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
