"""Ranh giới của tầng mô hình ngôn ngữ (§4.2).

Mô hình chạy local qua Ollama. Ranh giới quyền được giữ ở **tầng chữ ký hàm**, không
chỉ ở tầng quy ước:

- Không hàm nào trong file này nhận `conn`. Không tồn tại đường nào để tầng mô hình
  `INSERT`/`UPDATE`/`DELETE`. Muốn phá nguyên tắc thì phải sửa chữ ký hàm, và việc
  đó thấy được ngay khi review.
- Không quyết định `risk_level`. Mức rủi ro do `rules.py` tính xong rồi mới đưa vào
  đây làm dữ kiện.
- `ask_sql()` chỉ **sinh ra chuỗi SQL**; kiểm tra và thực thi là việc của `app.py`
  trên một kết nối read-only. Mô hình không tự chạy được câu nào.
- Đầu ra luôn là văn bản để người đọc lại, không bao giờ tự động gửi đi.

Mọi hàm trả `None` khi tầng mô hình tắt **hoặc** khi Ollama không trả lời. Đó là
hợp đồng §6 ("Ollama không phản hồi -> vẫn hiển thị mức rủi ro và rule_trace, chỉ
thiếu phần diễn giải"): mất tầng mô hình là mất phần diễn giải, không phải mất
trang.

Dùng `urllib` của thư viện chuẩn chứ không thêm dependency: cả hệ thống chạy trong
LAN lớp học, không CDN, không API key, và một dependency nữa là một thứ nữa phải
cài đúng vào hôm demo.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

STATUS_VI = {"present": "có mặt", "late": "đi muộn", "absent": "vắng"}
LEVEL_VI = {"ok": "ổn", "watch": "cần theo dõi", "at_risk": "nguy cơ rời lớp"}

# Câu mở đầu mọi prompt. Điều kiện §7.2 "Không bịa thông tin ngoài log" = 100%, nên
# ràng buộc phải nằm ngay trong system prompt chứ không phải trong lời dặn cuối.
_GROUNDING = (
    "Bạn viết cho Labcoach của một lớp học. Chỉ được dùng đúng những dữ kiện được "
    "cung cấp bên dưới. Tuyệt đối không suy đoán lý do vắng/muộn, không thêm sự "
    "kiện, không thêm con số nào không có trong dữ kiện. Nếu dữ kiện không đủ để "
    "kết luận, nói thẳng là chưa đủ dữ kiện. Viết tiếng Việt."
)


class LLMDisabled(RuntimeError):
    pass


def is_enabled(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("llm", {}).get("enabled", False))


def _cfg(cfg: dict[str, Any], key: str, default: Any) -> Any:
    return cfg.get("llm", {}).get(key, default)


def _strip_thinking(text: str) -> str:
    """Bỏ khối <think>…</think> của các model có chế độ suy luận.

    Đã tắt chế độ này qua tham số `think` của Ollama, nhưng vẫn cắt ở đây: model
    có thể đổi, và một câu chẩn đoán lẫn nguyên đoạn độc thoại nội tâm thì Labcoach
    đọc xong không hiểu gì.
    """
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _generate(
    prompt: str,
    cfg: dict[str, Any],
    *,
    system: str = _GROUNDING,
    temperature: float = 0.2,
    num_predict: int = 320,
    fmt: str | None = None,
) -> str | None:
    """Một lượt gọi Ollama. Trả None nếu tắt hoặc gọi không thành.

    Không raise ra ngoài: mọi caller đều nằm trên đường render một trang mà phần
    còn lại của trang vẫn đúng khi thiếu câu chữ.
    """
    if not is_enabled(cfg):
        return None

    body = {
        "model": _cfg(cfg, "model", "qwen3:8b"),
        "prompt": prompt,
        "system": system,
        "stream": False,
        "think": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
        },
    }
    if fmt:
        body["format"] = fmt

    url = _cfg(cfg, "base_url", "http://127.0.0.1:11434").rstrip("/") + "/api/generate"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=float(_cfg(cfg, "timeout_sec", 60))) as res:
            payload = json.loads(res.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None

    text = _strip_thinking(str(payload.get("response", "")))
    return text or None


# --------------------------------------------------------------------------
# Dữ kiện đưa cho mô hình
# --------------------------------------------------------------------------
def _day(iso: str | None) -> str:
    """2026-07-30 -> 30/07. Người Việt đọc ngày kiểu này, và tin nhắn gửi cho học
    viên mà ghi "ngày 2026-07-30" thì đọc như log máy."""
    if not iso or len(iso) < 10:
        return str(iso)
    return f"{iso[8:10]}/{iso[5:7]}"


def _facts(rule_trace: dict[str, Any], late_after_min: int) -> str:
    """Chuyển `rule_trace` thành bảng dữ kiện tiếng Việt.

    Đưa nguyên JSON cho mô hình thì nó bám vào tên khoá tiếng Anh và trả về câu
    nửa Việt nửa Anh. Diễn giải sẵn ở đây cũng thu hẹp chỗ để mô hình bịa: nó chỉ
    còn việc nối các dữ kiện này thành câu.

    `late_after_min` phải có mặt, không được bỏ. Một buổi trễ 8 phút có
    `late_min = 8` nhưng `status = 'present'` vì ngưỡng là 10 phút. Bản đầu của
    hàm này ghi "Số buổi đi muộn: 0" ngay trên một dòng lịch sử "muộn 8'" - bảng
    dữ kiện tự mâu thuẫn, và mô hình hoà giải mâu thuẫn đó bằng cách **bịa** ra
    "hai lần đi muộn". Lỗi bịa ấy là lỗi của bảng dữ kiện, không phải của mô hình.
    """
    counts = rule_trace.get("counts", {})
    lines = [
        f"- Mức rủi ro đã tính (do rule, không phải do bạn quyết): "
        f"{LEVEL_VI.get(rule_trace.get('level'), rule_trace.get('level'))}",
        f"- Cửa sổ xét: {counts.get('sessions_considered', 0)} buổi gần nhất "
        f"(tính đến {_day(rule_trace.get('as_of'))})",
        f"- Số buổi vắng: {counts.get('absent', 0)}",
        f"- Số buổi bị tính là ĐI MUỘN (đến trễ từ {late_after_min} phút trở lên): "
        f"{counts.get('late', 0)}",
    ]
    # "Vắng 3 buổi" + "chuỗi liên tiếp: 1" đứng cạnh nhau bị mô hình gộp thành
    # "vắng 3 buổi liên tiếp" - sai hẳn về mức nghiêm trọng. Nói thẳng ra là các
    # buổi vắng có liền nhau hay không, thay vì để mô hình tự suy từ hai con số.
    absent_total = counts.get("absent", 0)
    streak = rule_trace.get("absence_streak", 0)
    if absent_total > 1:
        if streak >= absent_total:
            lines.append(f"- Cả {absent_total} buổi vắng này LIỀN NHAU (chuỗi {streak} buổi liên tiếp)")
        elif streak >= 2:
            lines.append(
                f"- Các buổi vắng KHÔNG liền nhau hết; chuỗi liên tiếp dài nhất tính "
                f"đến buổi cuối là {streak} buổi"
            )
        else:
            lines.append("- Các buổi vắng NẰM RẢI RÁC, không buổi nào liền buổi nào")
    elif streak:
        lines.append(f"- Vắng liên tiếp tính đến buổi cuối: {streak} buổi")
    if rule_trace.get("increasing_lateness_streak"):
        # Nói "chuỗi 3 buổi tăng dần" mà không nói buổi nào bao nhiêu phút là để
        # trống một chỗ, và mô hình nhỏ lấp chỗ trống bằng số tự nghĩ ra ("3, 6 và
        # 10 phút" trong khi thực tế là 1, 6, 1, 4). Liệt kê thẳng từng con số ra
        # thì không còn gì để lấp.
        # Viết ở dạng câu tiếng Việt chứ không phải "24/07=1": mô hình nhỏ hay chép
        # nguyên xi dữ kiện vào câu trả lời, nên dữ kiện phải sẵn sàng để chép.
        minutes = [
            f"trễ {h.get('late_min')} phút ngày {_day(h.get('date'))}"
            for h in rule_trace.get("history", [])
            if h.get("source") != "manual" and h.get("late_min") is not None
        ]
        lines.append(
            f"- Chuỗi buổi có số phút muộn tăng dần: "
            f"{rule_trace['increasing_lateness_streak']} buổi liên tiếp"
        )
        # Chỉ liệt kê từng con số khi thực sự có một chuỗi cần giải thích. Chuỗi
        # dài 1 buổi thì danh sách này không giải thích gì, nó chỉ đưa cho mô hình
        # một dãy số để cộng lại thành "tổng thời gian trễ" - đúng cái nó đã làm.
        if minutes and rule_trace["increasing_lateness_streak"] >= 2:
            lines.append(
                "- Số phút đến trễ của từng buổi, đây là TOÀN BỘ con số về phút trễ, "
                "không có con số nào khác. KHÔNG được cộng các con số này lại với "
                "nhau, tổng của chúng không phải là một dữ kiện: " + ", ".join(minutes)
            )
    if rule_trace.get("early_departure_flags"):
        lines.append(
            f"- Số lần ghi nhận đầu giờ nhưng vắng ở lượt điểm danh thứ hai: "
            f"{rule_trace['early_departure_flags']}"
        )

    signals = rule_trace.get("signals", [])
    decisive = [s for s in signals if s.get("tier") == rule_trace.get("level")] or signals
    if decisive:
        lines.append("- Tín hiệu quyết định ra mức này:")
        for s in decisive:
            lines.append(f"    · {s.get('note')} (đo {s.get('value')}, ngưỡng {s.get('threshold')})")

    history = rule_trace.get("history", [])
    if history:
        marks = []
        for h in history:
            late = h.get("late_min") or 0
            status = STATUS_VI.get(h.get("status"), h.get("status"))
            if h.get("source") == "manual":
                # Bản ghi tay: `late_min` là khoảng cách tới lúc Labcoach bấm nút,
                # không phải giờ học viên đến. Đưa con số đó cho mô hình thì nó
                # viết vào tin nhắn gửi học viên câu "em đến trễ 922 phút".
                mark = f"{status} - buổi này Labcoach ghi nhận thủ công, nên hệ thống " \
                       "không có mốc giờ em đến; KHÔNG được suy ra là em vắng hay đi muộn"
            elif h.get("status") == "late":
                mark = f"{status} {late} phút"
            elif late:
                # Có trễ nhưng dưới ngưỡng: phải nói rõ là KHÔNG tính đi muộn, nếu
                # không thì dòng này mâu thuẫn với con số tổng ở trên.
                mark = f"{status} (đến trễ {late} phút, dưới ngưỡng nên không tính là đi muộn)"
            else:
                mark = f"{status} đúng giờ" if h.get("status") == "present" else status
            marks.append(f"{_day(h.get('date'))}: {mark}")
        lines.append("- Lịch sử từng buổi (cũ nhất trước): " + " | ".join(marks))

    return "\n".join(lines)


# --------------------------------------------------------------------------
# 1. Diễn giải chuỗi log thành câu chẩn đoán (§4.2)
# --------------------------------------------------------------------------
def write_diagnosis(rule_trace: dict[str, Any], cfg: dict[str, Any]) -> str | None:
    """Diễn giải một chuỗi log thành 1-2 câu cho người đọc.

    Trả về None khi tầng mô hình tắt hoặc Ollama im lặng: dashboard hiện
    `rule_trace` thay thế.
    """
    facts = _facts(rule_trace, int(cfg.get("checkin", {}).get("late_after_min", 10)))
    prompt = (
        f"DỮ KIỆN:\n{facts}\n\n"
        "Viết đúng 1-2 câu mô tả điều đang xảy ra với học viên này, cho Labcoach đọc "
        "trong 5 giây. Nêu đúng tên hiện tượng và các con số trong dữ kiện.\n"
        "- Chỉ được dùng những con số XUẤT HIỆN NGUYÊN VĂN trong phần DỮ KIỆN. "
        "Không tự cộng trừ, không quy đổi đơn vị, không tính ra con số mới.\n"
        "- Không khuyên nhủ, không đề xuất hành động, không chào hỏi.\n"
        "Chỉ trả về câu chẩn đoán, không thêm tiêu đề hay dấu đầu dòng."
    )
    # temperature 0: câu chẩn đoán không cần sáng tạo, nó cần đúng. Ở 0.2 các model
    # nhỏ thỉnh thoảng tự cộng số phút trễ lại thành một "tổng" không có trong log.
    return _generate(prompt, cfg, temperature=0.0, num_predict=200)


# --------------------------------------------------------------------------
# 2. Soạn tin nhắn cho học viên (§4.2, checklist §7.2)
# --------------------------------------------------------------------------
def draft_message(rule_trace: dict[str, Any], student_name: str, cfg: dict[str, Any]) -> str | None:
    """Soạn tin nhắn tiếng Việt theo hoàn cảnh từng ca, để Labcoach xem lại rồi gửi.

    Các ràng buộc dưới đây là `message_must` / `message_must_not` của golden set
    (§7.2) viết thẳng vào prompt. Đây là **bản nháp**: app không bao giờ tự gửi,
    Labcoach đọc lại và bấm gửi.
    """
    facts = _facts(rule_trace, int(cfg.get("checkin", {}).get("late_after_min", 10)))
    prompt = (
        f"DỮ KIỆN về học viên {student_name}:\n{facts}\n\n"
        "Soạn một tin nhắn ngắn (3-5 câu) Labcoach sẽ gửi riêng cho học viên này.\n"
        "BẮT BUỘC:\n"
        "- Xưng hô: gọi học viên là \"em\", người gửi xưng \"thầy/cô\".\n"
        "- Nêu cụ thể ít nhất một mốc thời gian hoặc con số có trong dữ kiện. Chỉ "
        "dùng con số xuất hiện nguyên văn trong dữ kiện, không tự tính ra số mới.\n"
        "- CÂU CUỐI CÙNG bắt buộc là một câu hỏi mở mời em kể lại tình hình, và "
        "bắt buộc kết thúc bằng dấu chấm hỏi \"?\". Tin nhắn không có dấu \"?\" "
        "là tin nhắn sai.\n"
        "- Giọng quan tâm, bình thường, như nhắn cho một người mình muốn giúp.\n"
        "TUYỆT ĐỐI KHÔNG:\n"
        "- Không giọng cảnh cáo, không dọa, không phê bình.\n"
        "- Không nhắc quy chế, điểm số, điều kiện dự thi hay hậu quả kỷ luật.\n"
        "- Không đoán lý do em vắng hay muộn. Chưa ai biết lý do - đó là lý do phải hỏi.\n"
        "Chỉ trả về nội dung tin nhắn, không thêm tiêu đề hay giải thích."
    )
    # 0.25 chứ không phải 0.4: tin nhắn cần ấm, nhưng ở 0.4 model 4B thỉnh thoảng
    # thêm một con số không có trong log - mà chỉ tiêu §7.2 về việc bịa là 100%,
    # không phải "thường là 100%". Một tin nhắn nhạt hơn vẫn gửi được; một tin nhắn
    # nêu sai số buổi vắng của học viên thì không.
    return _generate(prompt, cfg, temperature=0.25, num_predict=400)


# --------------------------------------------------------------------------
<<<<<<< HEAD
# 3. Diễn giải một flag bất thường
# --------------------------------------------------------------------------
# Điều mô hình KHÔNG được làm ở đây, viết thẳng vào prompt vì đây là chỗ dễ vượt
# ranh giới nhất: một câu "học viên này gian lận" đọc rất thuyết phục, mà bằng
# chứng thì chỉ đủ để nói "hai người dùng chung một máy".
_FLAG_RULES = (
    "- KHÔNG kết luận có gian lận hay không. Dữ kiện chỉ cho biết chuyện gì đã xảy "
    "ra, không cho biết vì sao. Hai người dùng chung một máy có thể là gian lận, "
    "cũng có thể là điện thoại hết pin.\n"
    "- KHÔNG đề xuất kỷ luật, không nhắc quy chế.\n"
    "- KHÔNG nói flag này nên đóng hay không - đó là quyết định của Labcoach.\n"
    "- Không thêm sự kiện, tên người, hay con số nào không có trong dữ kiện.\n"
)


# Mỗi rule nghĩa là gì và Labcoach làm được gì với nó.
#
# Không có phần này thì mô hình tự nghĩ ra việc cần làm, và nó nghĩ ra những thứ
# nghe hợp lý mà hệ thống không có: "đối chiếu với danh sách thiết bị được phép
# tại lab" - không tồn tại danh sách nào như thế. Nghiệp vụ này hệ thống biết
# chính xác, nên đưa thẳng cho mô hình thay vì để nó đoán.
RULE_CONTEXT_VI = {
    "DEVICE_REUSE": (
        "Nghĩa là: máy học viên vừa dùng ĐÃ được buộc cho một mã học viên KHÁC từ "
        "trước. Hệ thống chặn vì mỗi máy chỉ điểm danh cho một người.\n"
        "Cách gọi tên: người bị chặn là người VỪA QUÉT. Mã học viên xuất hiện trong "
        "dòng \"hệ thống ghi lại\" là CHỦ CŨ của máy, người đó không làm gì sai và "
        "không bị chặn. Đây cũng không phải lỗi - hệ thống cố ý từ chối.\n"
        "Labcoach làm được: hỏi hai bên có mượn máy nhau không; nếu là đổi máy thật "
        "thì vào Danh sách lớp bấm Unbind cho chủ cũ rồi cho quét lại; nếu học viên "
        "không kịp xử lý trong buổi thì điểm danh tay."
    ),
    "DEVICE_MISMATCH": (
        "Nghĩa là: chính học viên này đã buộc một máy từ trước, nhưng đang quét bằng "
        "máy khác. Hệ thống chặn.\n"
        "Cách gọi tên: đây KHÔNG phải lỗi, không phải trục trặc, không phải máy hỏng. "
        "Hệ thống cố ý từ chối theo quy tắc. Viết là \"hệ thống từ chối\" hoặc "
        "\"hệ thống chặn\", tuyệt đối không viết \"gặp lỗi\".\n"
        "Labcoach làm được: hỏi học viên có đổi/mất điện thoại không; nếu đúng thì "
        "Unbind để lần quét sau buộc vào máy mới; trong buổi thì điểm danh tay."
    ),
    "EARLY_DEPARTURE": (
        "Nghĩa là: học viên có mặt ở lượt điểm danh đầu giờ nhưng vắng ở lượt thứ hai "
        "gọi giữa/cuối buổi. Chuyện thiết bị không liên quan gì tới flag này.\n"
        "Labcoach làm được: hỏi học viên vì sao về sớm; nếu có lý do chính đáng thì "
        "ghi vào ghi chú xử lý khi đóng flag."
    ),
    "FINGERPRINT_MATCH": (
        "Nghĩa là: hai học viên có dấu vết trình duyệt giống nhau trong cùng buổi. "
        "Hệ thống CHỈ gắn flag, KHÔNG chặn ai - vì hai điện thoại cùng model, cùng hệ "
        "điều hành, cùng cỡ màn hình cho dấu vết giống nhau, mà lớp thì đầy máy giống "
        "nhau. Đây là tín hiệu yếu, phần lớn là trùng hợp.\n"
        "Labcoach làm được: xem hai người có ngồi cạnh nhau không; nếu hai máy khác "
        "nhau thật thì đóng flag."
    ),
    "IP_RATE_SPIKE": (
        "Nghĩa là: nhiều lượt quét dồn dập từ cùng một địa chỉ IP trong vài giây. Cả "
        "lớp dùng chung một wifi thì chuyện này xảy ra bình thường, nhất là ngay sau "
        "khi mã QR hiện lên.\n"
        "Labcoach làm được: hầu như luôn đóng được flag; chỉ xem kỹ nếu số lượt vượt "
        "xa số người thực có trong phòng."
    ),
    "TOKEN_GRACE_USED": (
        "Nghĩa là: học viên quét đúng mã nhưng chậm vài giây, rơi vào khoảng gia hạn. "
        "Hệ thống vẫn nhận. Đây là tín hiệu mức thấp, gần như luôn vô hại - mạng chậm "
        "hoặc bấm chậm.\n"
        "Labcoach làm được: đóng flag, trừ khi lặp lại rất nhiều lần ở cùng một người."
    ),
}


def _flag_facts(ctx: dict[str, Any]) -> str:
    """Bối cảnh một flag, viết thành dữ kiện tiếng Việt."""
    f = ctx.get("flag", {})
    lines = [
        f"- Loại: {f.get('label')} (mã kỹ thuật {f.get('rule_code')})",
        f"- Mức nghiêm trọng: {f.get('severity')}",
        f"- Học viên: {f.get('student_name') or '?'} ({f.get('student_id') or 'không rõ'})",
        f"- Buổi: {_day(f.get('date'))} lúc {f.get('start_time') or '?'}"
        + (f" tại {f['room']}" if f.get("room") else ""),
        f"- Hệ thống ghi lại: {f.get('detail') or '(không có mô tả)'}",
        f"- Trạng thái: {'đã xử lý' if f.get('resolved') else 'chưa xử lý'}",
    ]

    att = ctx.get("attendance")
    if att:
        lines.append(
            f"- Bản ghi điểm danh đi kèm: lượt {att.get('call_index')}, "
            f"trạng thái {STATUS_VI.get(att.get('status'), att.get('status'))}, "
            f"nguồn {'Labcoach nhập tay' if att.get('source') == 'manual' else 'học viên tự quét'}"
        )
    else:
        lines.append(
            "- KHÔNG có bản ghi điểm danh nào đi kèm: lượt check-in này đã bị CHẶN "
            "trước khi ghi, nên buổi đó học viên chưa được tính có mặt."
        )

    others = ctx.get("others_same_session") or []
    if others:
        who = ", ".join(f"{o.get('name') or '?'} ({o.get('student_id')})" for o in others)
        lines.append(f"- Cùng buổi, cùng loại flag này còn có: {who}")

    prior = [x for x in (ctx.get("student_other_flags") or []) if not x.get("resolved")]
    if prior:
        kinds = ", ".join(sorted({x.get("label", "") for x in prior}))
        lines.append(
            f"- Học viên này còn {len(prior)} flag khác chưa xử lý: {kinds}. "
            "(Đây là bối cảnh, KHÔNG phải nội dung của flag đang xét - đừng đề xuất "
            "việc cần kiểm dựa trên mấy flag này.)"
        )

    context = RULE_CONTEXT_VI.get(f.get("rule_code"))
    if context:
        lines.append("\nLOẠI FLAG NÀY NGHĨA LÀ GÌ VÀ XỬ LÝ RA SAO:\n" + context)

    return "\n".join(lines)


def explain_flag(ctx: dict[str, Any], cfg: dict[str, Any]) -> str | None:
    """Dựng lại chuyện đã xảy ra + đề xuất việc cần kiểm, cho một flag.

    Không nhận `conn`: bối cảnh do `app.py` truy vấn sẵn rồi truyền vào. Mô hình
    không tự đi hỏi database được thêm gì.
    """
    prompt = (
        f"DỮ KIỆN VỀ MỘT DẤU HIỆU BẤT THƯỜNG:\n{_flag_facts(ctx)}\n\n"
        "Viết cho Labcoach, đúng hai phần, mỗi phần 1-2 câu:\n"
        "CHUYỆN GÌ ĐÃ XẢY RA: kể lại theo trình tự, bằng tiếng Việt thường, "
        "không dùng mã kỹ thuật.\n"
        "NÊN KIỂM GÌ: 1-2 việc cụ thể, LẤY TỪ phần \"xử lý ra sao\" trong dữ kiện. "
        "Không tự nghĩ ra thao tác nào khác - hệ thống chỉ có đúng những thao tác đã "
        "liệt kê ở đó.\n\n"
        f"{_FLAG_RULES}"
        "Trả về đúng hai dòng, mỗi dòng bắt đầu bằng nhãn ở trên và dấu hai chấm."
    )
    return _generate(prompt, cfg, temperature=0.2, num_predict=320)


# --------------------------------------------------------------------------
# 4. Câu hỏi tự nhiên -> SQL read-only (§4.2)
=======
# 3. Câu hỏi tự nhiên -> SQL read-only (§4.2)
>>>>>>> 536153b69acb330f3a1329c9e7d083a56b7099be
# --------------------------------------------------------------------------
# Lược đồ đưa cho mô hình. Cắt còn các bảng trả lời được câu hỏi chuyên cần, và
# **không** có bảng nào chứa bí mật (admin_users, sessions_auth, qr_tokens): thứ
# không đưa vào prompt là thứ không thể rò ra qua một câu SQL sinh sai.
SQL_SCHEMA_HINT = """\
students(student_id TEXT PK, name TEXT, email TEXT, active INT, device_hash TEXT, device_locked_at INT)
sessions(session_id INT PK, date TEXT 'YYYY-MM-DD', start_time TEXT 'HH:MM', room TEXT,
         state TEXT 'planned|open|closed', call_index INT)
attendance(id INT PK, student_id TEXT, session_id INT, checkin_ts_ms INT, call_index INT,
           status TEXT 'present|late|absent', source TEXT 'web|manual', manual_reason TEXT)
anomaly_flags(id INT PK, student_id TEXT, session_id INT, rule_code TEXT, severity TEXT 'low|med|high',
              detail TEXT, created_at INT, resolved INT)
risk_snapshots(id INT PK, student_id TEXT, date TEXT, risk_level TEXT 'ok|watch|at_risk', sent INT)

rule_code nhận các giá trị: DEVICE_REUSE, DEVICE_MISMATCH, IP_RATE_SPIKE,
EARLY_DEPARTURE, TOKEN_GRACE_USED, FINGERPRINT_MATCH.
<<<<<<< HEAD

QUAN TRỌNG - `device_hash` CHỈ có ở bảng `students`, KHÔNG có ở `sessions`.
"Chưa bind thiết bị" = `students.device_hash IS NULL`. Đừng join sang sessions.
=======
>>>>>>> 536153b69acb330f3a1329c9e7d083a56b7099be
"""

# Hai ví dụ mẫu, không phải lời dặn suông.
#
# Ví dụ 1 tồn tại vì đây là bẫy lớn nhất của lược đồ này: **vắng mặt không có dòng
# trong `attendance`**. Bản trước chỉ dặn bằng một câu văn xuôi và model vẫn viết
# `WHERE status = 'absent'` -> trả về 0 dòng cho đúng câu hỏi hay gặp nhất
# ("ai vắng nhiều nhất"). Một bảng rỗng trông y hệt một câu trả lời "không có ai",
# nên sai kiểu này nguy hiểm hơn là báo lỗi.
SQL_EXAMPLES = """\
VÍ DỤ 1 - "ai vắng nhiều nhất trong 5 buổi gần đây":
SELECT s.student_id, s.name, COUNT(*) AS so_buoi_vang
FROM students s
CROSS JOIN (SELECT session_id FROM sessions WHERE state = 'closed'
            ORDER BY date DESC LIMIT 5) recent
WHERE s.active = 1
  AND NOT EXISTS (SELECT 1 FROM attendance a
                  WHERE a.student_id = s.student_id
                    AND a.session_id = recent.session_id
                    AND a.call_index = 1 AND a.status != 'absent')
GROUP BY s.student_id
ORDER BY so_buoi_vang DESC
LIMIT 200

VÍ DỤ 2 - "có bao nhiêu flag chưa xử lý, chia theo loại":
SELECT rule_code, COUNT(*) AS so_luong
FROM anomaly_flags
WHERE resolved = 0
GROUP BY rule_code
ORDER BY so_luong DESC
LIMIT 200
<<<<<<< HEAD

VÍ DỤ 3 - "những học viên nào chưa bind thiết bị":
SELECT student_id, name
FROM students
WHERE active = 1 AND device_hash IS NULL
ORDER BY student_id
LIMIT 200
=======
>>>>>>> 536153b69acb330f3a1329c9e7d083a56b7099be
"""


def ask_sql(question: str, cfg: dict[str, Any]) -> str | None:
    """Sinh **một** câu SELECT trả lời câu hỏi tiếng Việt của Labcoach.

    Chỉ trả về chuỗi SQL. Hàm này không nhận `conn` và không chạy gì - việc kiểm
    tra và thực thi thuộc `app.py`, trên kết nối read-only. Mô hình sinh SQL sai
    hay sinh SQL độc đều không tự làm gì được: nó chỉ đang đề nghị một chuỗi.
    """
    prompt = (
        f"LƯỢC ĐỒ SQLite:\n{SQL_SCHEMA_HINT}\n"
        "QUY TẮC NGHIỆP VỤ QUAN TRỌNG NHẤT:\n"
        "Học viên vắng thì KHÔNG có dòng nào trong bảng attendance. Không bao giờ "
        "đếm vắng bằng `status = 'absent'` - phải dùng NOT EXISTS đối chiếu với "
        "bảng sessions, như ví dụ 1 dưới đây.\n\n"
        f"{SQL_EXAMPLES}\n"
        f"CÂU HỎI: {question}\n\n"
        "Viết đúng MỘT câu lệnh SELECT của SQLite trả lời câu hỏi trên.\n"
        "- Chỉ SELECT. Không INSERT/UPDATE/DELETE/DROP/ATTACH/PRAGMA.\n"
        "- Luôn có LIMIT, tối đa 200 dòng.\n"
        "- Chỉ lấy các cột câu hỏi thực sự cần. Nếu câu hỏi nhóm theo một tiêu chí "
        "(theo loại, theo buổi) thì GROUP BY đúng tiêu chí đó, đừng thêm cột khác "
        "vào GROUP BY vì nó làm vỡ nhóm.\n"
        "- Lấy kèm students.name khi kết quả liệt kê từng học viên.\n"
        "- Không dấu chấm phẩy, không giải thích, không markdown. Chỉ câu SQL."
    )
    sql = _generate(prompt, cfg, temperature=0.0, num_predict=300)
    if sql is None:
        return None
    # Model hay bọc trong ```sql dù đã dặn. Gỡ ở đây rẻ hơn là bắt Labcoach thấy lỗi.
    sql = re.sub(r"^```(?:sql)?|```$", "", sql.strip(), flags=re.MULTILINE).strip()
    return sql or None


# --------------------------------------------------------------------------
<<<<<<< HEAD
# 5. Bóc tách đơn xin phép viết tự do -> JSON có cấu trúc (§4.2)
=======
# 4. Bóc tách đơn xin phép viết tự do -> JSON có cấu trúc (§4.2)
>>>>>>> 536153b69acb330f3a1329c9e7d083a56b7099be
# --------------------------------------------------------------------------
LEAVE_CATEGORIES = ["ốm", "việc gia đình", "lịch trùng", "đi lại", "khác"]

# Phân biệt hai nhóm hay bị lẫn: "ốm" là chính học viên ốm; đi chăm/đưa người nhà
# đi khám là "việc gia đình". Model 4B xếp nhầm nếu chỉ đưa danh sách tên nhóm.
LEAVE_CATEGORY_HINT = """\
- "ốm": chính HỌC VIÊN bị ốm, sốt, đau, phải đi khám cho bản thân.
- "việc gia đình": việc của người nhà - đưa bố/mẹ/em đi khám, đám tang, đám cưới,
  chăm người nhà ốm. Người đi khám không phải học viên thì thuộc nhóm này.
- "lịch trùng": trùng lịch thi, lịch học môn khác, lịch làm việc.
- "đi lại": kẹt xe, hỏng xe, tàu/xe trễ, thời tiết.
- "khác": không rơi vào bốn nhóm trên.
"""

_DOW_VI = ["thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ Nhật"]
# Học viên viết "thứ 3" bằng chữ số nhiều hơn viết "thứ Ba". Bảng chỉ ghi dạng chữ
# thì model 4B đi khớp chữ SỐ trong "thứ 3" với ngày 08-03 - lệch đúng một ngày và
# lệch một cách rất khó thấy. Ghi cả hai dạng cạnh nhau thì không còn gì để khớp nhầm.
_DOW_NUM_VI = ["thứ 2", "thứ 3", "thứ 4", "thứ 5", "thứ 6", "thứ 7", "chủ nhật"]


def _weekday_vi(iso: str) -> str:
    from datetime import date
    y, m, d = (int(x) for x in iso.split("-"))
    return _DOW_VI[date(y, m, d).weekday()]


def _date_table(today: str) -> str:
    """Bảng quy đổi ngày tương đối, tính sẵn bằng code.

    Model 4B cộng trừ ngày sai - nó trả "mai" ra đúng ngày hôm nay. Số học lịch là
    thứ code làm chuẩn xác tuyệt đối, nên không có lý do gì giao cho mô hình.

    Bảng phải NGẮN. Bản đầu liệt kê 14 ngày tới và model coi cả bảng là câu trả
    lời - trả về 15 ngày cho một đơn xin nghỉ hai buổi. Bảng càng dài thì càng
    giống một danh sách để chép.
    """
    from datetime import date, timedelta
    y, m, d = (int(x) for x in today.split("-"))
    base = date(y, m, d)
    rows = [f"  hôm nay = {base}", f"  mai = {base + timedelta(days=1)}",
            f"  ngày kia = {base + timedelta(days=2)}"]
    # Lần xuất hiện kế tiếp của mỗi thứ trong tuần - đủ cho "thứ 3 tuần sau".
    for i in range(1, 8):
        nxt = base + timedelta(days=i)
        w = nxt.weekday()
        rows.append(f"  {_DOW_NUM_VI[w]} = {_DOW_VI[w]} kế tiếp = {nxt}")
    return (
        "BẢNG QUY ĐỔI NGÀY (chỉ để TRA CỨU, tuyệt đối không chép cả bảng vào "
        "câu trả lời):\n" + "\n".join(rows) + "\n"
    )


def parse_leave_request(
<<<<<<< HEAD
    text: str,
    cfg: dict[str, Any],
    *,
    today: str,
    roster: list[dict[str, Any]] | None = None,
=======
    text: str, cfg: dict[str, Any], *, today: str, known_student_ids: list[str] | None = None
>>>>>>> 536153b69acb330f3a1329c9e7d083a56b7099be
) -> dict[str, Any] | None:
    """Bóc một đơn xin phép viết tự do thành JSON có cấu trúc.

    Đầu ra là **đề nghị** để Labcoach soát rồi mới ghi. Mô hình không được ghi
    thẳng vào `attendance`: một dòng chuyên cần sai vì mô hình đọc nhầm ngày là
    đúng thứ §1 gọi là "số liệu không đáng tin".

    Trả None khi tắt / Ollama im lặng / model trả về không phải JSON.
    """
<<<<<<< HEAD
    # Đưa cả mã lẫn tên: học viên nhắn "em Nguyễn Văn An xin nghỉ" nhiều hơn là
    # nhớ đúng mã của mình. Việc đối chiếu tên -> mã vẫn do CODE làm ở app.py, ở
    # đây chỉ giúp mô hình chép đúng tên có thật thay vì tên nó nghe nhầm.
    roster_block = ""
    if roster:
        rows = ", ".join(f"{r['student_id']}={r['name']}" for r in roster[:200])
        roster_block = f"DANH SÁCH LỚP (mã=tên): {rows}\n"

    prompt = (
        f"Hôm nay là {today} ({_weekday_vi(today)}).\n{_date_table(today)}{roster_block}"
=======
    roster = ""
    if known_student_ids:
        roster = "Mã học viên hợp lệ: " + ", ".join(known_student_ids[:200]) + "\n"

    prompt = (
        f"Hôm nay là {today} ({_weekday_vi(today)}).\n{_date_table(today)}{roster}"
>>>>>>> 536153b69acb330f3a1329c9e7d083a56b7099be
        f"ĐƠN XIN PHÉP (học viên viết tự do):\n\"\"\"\n{text.strip()}\n\"\"\"\n\n"
        "Bóc thành JSON đúng các khoá sau:\n"
        '{"student_id": string|null, "student_name": string|null, '
        '"dates": [chuỗi "YYYY-MM-DD"], "category": một trong '
        f"{json.dumps(LEAVE_CATEGORIES, ensure_ascii=False)}, "
        '"reason_text": string, "has_evidence": true|false, "confidence": 0.0-1.0, '
        '"missing": [tên các trường đơn không nói rõ]}\n'
        f"Cách chọn category:\n{LEAVE_CATEGORY_HINT}"
        "- \"dates\" CHỈ chứa những ngày đơn thực sự xin nghỉ, thường là 1-2 ngày. "
        "Ngày tương đối (\"mai\", \"thứ 3 tuần sau\") tra trong BẢNG QUY ĐỔI NGÀY, "
        "không tự cộng trừ. Không đưa ngày nào đơn không nhắc tới.\n"
        "- \"student_id\" chỉ điền khi đơn viết rõ mã. Đơn không ghi mã thì để null, "
        "tuyệt đối không chọn bừa một mã trong danh sách lớp.\n"
<<<<<<< HEAD
        "- \"student_name\" chép tên người xin nghỉ đúng như đơn viết. Nếu tên đó "
        "có trong DANH SÁCH LỚP thì chép y hệt cách viết trong danh sách. Không có "
        "tên trong đơn thì để null.\n"
=======
>>>>>>> 536153b69acb330f3a1329c9e7d083a56b7099be
        "- Trường nào đơn không nói thì để null và ghi tên nó vào \"missing\". "
        "Không đoán, không điền thay.\n"
        "- reason_text chép lại nguyên văn lý do trong đơn, không diễn giải.\n"
        "Chỉ trả JSON."
    )
    raw = _generate(prompt, cfg, temperature=0.0, num_predict=400, fmt="json")
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    # Chuẩn hoá: model có thể trả category lạ hoặc dates là chuỗi đơn.
    if data.get("category") not in LEAVE_CATEGORIES:
        data["category"] = "khác"
    dates = data.get("dates")
    if isinstance(dates, str):
        dates = [dates]
    data["dates"] = [d for d in (dates or []) if isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)]

    # `missing` tính lại bằng code, không dùng giá trị model trả về. Đây là phép
    # đối chiếu cơ học "trường này có rỗng không" - model vẫn báo thiếu student_id
    # ngay trong lượt nó vừa bóc ra đúng mã, và một cảnh báo sai chỗ này khiến
    # Labcoach đi hỏi lại học viên một thứ mà đơn đã ghi rõ.
    data["missing"] = [
        field for field, value in (
            ("student_id", data.get("student_id")),
            ("student_name", data.get("student_name")),
            ("dates", data["dates"]),
            ("reason_text", data.get("reason_text")),
        )
        if not value
    ]
    data["date_warnings"] = _weekday_mismatches(text, data["dates"])
    return data


def _weekday_mismatches(text: str, dates: list[str]) -> list[str]:
    """Đơn nhắc thứ mấy mà ngày bóc ra rơi vào thứ khác thì nói ra.

    Vì sao cần: model 4B **khớp chữ số**. Đơn viết "thứ 3 với thứ 5 tuần sau" thì
    nó trả về ngày 03 và ngày 05 của tháng, lệch đúng một ngày so với thứ Ba và
    thứ Năm thật - kiểu sai rất khó thấy bằng mắt, mà hậu quả là điểm danh nhầm
    buổi. Bảng quy đổi tính sẵn trong prompt vẫn không chữa được.

    Đối chiếu thứ trong tuần là phép tính lịch thuần tuý, code làm đúng 100%. Chỗ
    nào mô hình yếu mà code chắc thì để code kiểm lại - đó cũng là lý do hàm này
    chỉ *cảnh báo* chứ không tự sửa ngày: sửa hộ là lại đoán thay người viết đơn.
    """
    from datetime import date

    low = text.lower()
    mentioned = {
        i for i, (num, name) in enumerate(zip(_DOW_NUM_VI, _DOW_VI))
        if num in low or name.lower() in low
    }
    if not mentioned:
        return []

    warnings = []
    for iso in dates:
        try:
            y, m, d = (int(x) for x in iso.split("-"))
            weekday = date(y, m, d).weekday()
        except ValueError:
            continue
        if weekday not in mentioned:
            want = ", ".join(sorted(_DOW_NUM_VI[i] for i in mentioned))
            warnings.append(
                f"Đơn nhắc {want}, nhưng ngày {d:02d}/{m:02d} lại là "
                f"{_DOW_NUM_VI[weekday]} — kiểm lại với học viên."
            )
    return warnings


# --------------------------------------------------------------------------
# Kiểm tra sức khoẻ - dùng cho trang trạng thái và cho eval
# --------------------------------------------------------------------------
def health(cfg: dict[str, Any]) -> dict[str, Any]:
    """Ollama có chạy không và model đã tải chưa. Không bao giờ raise."""
    if not is_enabled(cfg):
        return {"enabled": False, "reachable": False, "model_ready": False, "model": None}

    model = _cfg(cfg, "model", "qwen3:8b")
    url = _cfg(cfg, "base_url", "http://127.0.0.1:11434").rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5) as res:
            tags = json.loads(res.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return {"enabled": True, "reachable": False, "model_ready": False, "model": model}

    names = {m.get("name", "") for m in tags.get("models", [])}
    ready = model in names or f"{model}:latest" in names
    return {"enabled": True, "reachable": True, "model_ready": ready, "model": model}
