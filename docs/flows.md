# Luồng hệ thống — sơ đồ

Sơ đồ mermaid cho toàn bộ hệ thống chuyên cần. Đọc kèm `spec.md` §4.

Tầng mô hình ngôn ngữ **tắt** trong bản dựng này; chỗ nó sẽ nối vào được vẽ bằng
nét đứt để thấy ranh giới đã được giữ nguyên.

---

## 1 · Kiến trúc

```mermaid
flowchart TB
    subgraph phone["Điện thoại học viên"]
        cam["Camera quét QR"]
        page["Trang /checkin"]
    end

    subgraph screen["Máy chiếu lớp"]
        proj["/projector<br/>QR xoay mỗi 20s"]
    end

    subgraph server["Máy chủ trong LAN lớp — FastAPI :8000"]
        mw["Middleware<br/>chặn ngoài subnet"]
        api["API check-in"]
        tok["qrtoken.py<br/>phát / thu hồi token"]
        rule["rules.py<br/>deterministic"]
        qrmod["qr.py<br/>sinh QR, thư viện chuẩn"]
        db[("SQLite<br/>attendance.db")]
    end

    subgraph coach["Máy Labcoach"]
        dash["/admin<br/>bản tin đầu ngày"]
    end

    llm["Ollama qwen2.5:7b<br/>TẮT trong bản này"]

    cam --> page
    proj -.->|"hiện mã"| cam
    page -->|"POST /api/checkin"| mw
    mw --> api
    api --> tok
    api --> rule
    rule --> db
    tok --> db
    proj -->|"xin token mới"| tok
    tok --> qrmod
    qrmod -->|"SVG"| proj
    dash --> db
    rule -.->|"chỉ đọc, khi bật"| llm
    llm -.->|"diễn giải + tin nhắn"| dash

    style llm stroke-dasharray: 5 5,color:#888
    style db fill:#e8ecfb
```

Không có dịch vụ ngoài. Không API key. Toàn bộ chạy trên một máy trong LAN lớp học.

---

## 2 · Luồng check-in đầy đủ

```mermaid
sequenceDiagram
    autonumber
    actor HV as Học viên
    participant MC as Máy chiếu
    participant MW as Middleware subnet
    participant API as API check-in
    participant TK as qrtoken
    participant RL as rules
    participant DB as SQLite

    MC->>TK: xin token đang hoạt động
    TK->>DB: token còn sống?
    alt Còn sống
        DB-->>TK: token cũ
    else Hết hạn
        TK->>DB: INSERT token mới 128-bit
    end
    TK-->>MC: token + QR SVG
    MC-->>HV: hiện mã QR trên màn hình lớp

    HV->>MW: quét mã, mở /checkin?t=TOKEN
    MW->>MW: IP có trong subnet lớp?
    alt Ngoài dải mạng
        MW-->>HV: 403 — không ở trong phòng
    else Trong dải mạng
        MW->>API: cho qua
        HV->>API: POST mã học viên + fingerprint
        API->>API: kiểm tra tần suất theo IP và theo mã HV
        API->>DB: mã học viên có trong lớp?
        API->>TK: token hợp lệ cho buổi và lượt này?
        alt Token sai / hết hạn / bị thu hồi / đã dùng
            TK-->>HV: 400 — quét lại mã trên máy chiếu
        else Token hợp lệ
            API->>API: device_hash = SHA256(cookie server + fingerprint)
            alt Lệch thiết bị đã buộc của học viên này
                API->>DB: ghi flag DEVICE_MISMATCH
                API-->>HV: 409 — nhờ Labcoach xóa thiết bị, hoặc điểm danh tay
            else Máy này đã buộc cho học viên khác
                API->>DB: ghi flag DEVICE_REUSE
                API-->>HV: 409 — mỗi thiết bị chỉ điểm danh cho một người
            else Khớp, hoặc cả hai phía đều tự do
                API->>DB: INSERT attendance
                API->>TK: đánh dấu token đã dùng
                opt Lần check-in đầu tiên
                    API->>DB: buộc device_hash + ghi device_bindings
                end
                API->>RL: chạy rule bất thường
                RL->>DB: ghi flag nếu có
                API->>DB: ghi audit_log
                API-->>HV: 200 — đã ghi nhận (có mặt / muộn N phút)
            end
        end
    end
```

---

## 3 · Bốn lớp xác thực hiện diện

Mỗi lớp chặn một kiểu gian lận khác nhau, và không lớp nào tự đủ.

```mermaid
flowchart TD
    start(["Có người muốn tạo một bản ghi hiện diện"]) --> L1

    L1{"Lớp 1<br/>Request phát từ subnet lớp?"}
    L1 -->|Không| B1["CHẶN<br/>người ở nhà, VPN ngoài"]
    L1 -->|Có| L2

    L2{"Lớp 2<br/>Token QR đang hiện trên máy chiếu?"}
    L2 -->|Không| B2["CHẶN<br/>người không nhìn thấy màn hình lớp"]
    L2 -->|Có| L3a

    L3a{"Lớp 3a<br/>Học viên này đã buộc máy khác?"}
    L3a -->|Rồi| B3["CHẶN + flag DEVICE_MISMATCH<br/>điểm danh hộ bằng máy khác"]
    L3a -->|Chưa/khớp| L3b

    L3b{"Lớp 3b<br/>Máy này đã buộc cho người khác?"}
    L3b -->|Rồi| B4["CHẶN + flag DEVICE_REUSE<br/>một máy cho nhiều người"]
    L3b -->|Chưa| L3c

    L3c{"Lớp 3c<br/>Có ai trong buổi cùng dấu vết máy?"}
    L3c -->|Có| B6["GHI + flag FINGERPRINT_MATCH<br/>hai cửa sổ ẩn danh? hay hai máy cùng model?<br/>để người xem quyết"]
    L3c -->|Không| REC["Ghi nhận lượt 1"]
    B6 --> REC

    REC --> L4{"Lớp 4<br/>Còn mặt ở lượt 2 giữa buổi?"}
    L4 -->|Không| B5["flag EARLY_DEPARTURE<br/>ghi nhận đầu giờ rồi rời lớp"]
    L4 -->|Có| OK(["Bản ghi đáng tin"])

    B3 --> ESC{{"Đường thoát<br/>xóa dữ liệu thiết bị · điểm danh tay"}}
    B4 --> ESC

    style B1 fill:#fdeae8
    style B2 fill:#fdeae8
    style B3 fill:#fdeae8
    style B4 fill:#fdeae8
    style B5 fill:#fdf1dc
    style B6 fill:#fdf1dc
    style OK fill:#e3f4ea
    style ESC fill:#e8ecfb
```

Đỏ = chặn trước khi ghi. Vàng = vẫn ghi nhưng để lại flag cho người xem.

**Hai lỗ còn lại, nói thẳng:**

1. **Chụp màn hình gửi cho bạn ở ngoài.** Bạn đó vẫn phải ở trong subnet lớp
   (lớp 1) và vẫn phải dùng đúng thiết bị đã buộc của chính chủ (lớp 3), nên
   đường này chỉ mở khi hai người cùng ở trong phòng và chuyền máy cho nhau —
   lúc đó lớp 3b chặn kèm flag `DEVICE_REUSE` mức high.
2. **Hai cửa sổ ẩn danh trên một điện thoại.** Mỗi cửa sổ một cookie nên
   `device_hash` khác nhau, server không có cách nào biết là cùng một máy. Chỉ
   **phát hiện** được qua `FINGERPRINT_MATCH`, không chặn — vì hai máy cùng model cũng
   cho fingerprint giống nhau, chặn là chặn oan bạn cùng lớp.

---

## 4 · Vòng đời buổi học

```mermaid
stateDiagram-v2
    [*] --> scheduled: Labcoach tạo buổi
    scheduled --> open: "Mở điểm danh"<br/>call_index = 1
    open --> open: token QR xoay mỗi 20s
    open --> second: "Gọi lượt 2"<br/>thu hồi token lượt 1
    second --> second: token lượt 2 xoay
    second --> closed: "Đóng buổi"
    open --> closed: "Đóng buổi"<br/>chưa gọi lượt 2
    closed --> [*]

    note right of second
        Thời điểm gọi lượt 2 do Labcoach
        bấm, không theo lịch cố định.
        Biết trước phút nào gọi thì
        lớp 4 mất hết tác dụng.
    end note

    note right of closed
        Đóng buổi mới chạy phát hiện EARLY_DEPARTURE.
        Trước đó "chưa check-in" và "vắng"
        là hai chuyện khác nhau.
    end note
```

---

## 5 · Từ log hiện diện tới bản tin đầu ngày

```mermaid
flowchart LR
    subgraph det["Deterministic — code, không có mô hình"]
        log[("attendance<br/>log hiện diện")]
        flags[("anomaly_flags<br/>6 rule")]
        win["Cửa sổ 5 buổi gần nhất"]
        sig["Đối chiếu ngưỡng<br/>trong config.json"]
        lvl{"Mức rủi ro"}
        snap[("risk_snapshots<br/>+ rule_trace")]
    end

    subgraph model["Tầng mô hình — TẮT"]
        diag["Chẩn đoán 1-2 câu"]
        msg["Tin nhắn tiếng Việt"]
    end

    subgraph out["Bản tin đầu ngày — trang Dashboard"]
        top["Tối đa 5 ca, xếp ưu tiên"]
        human["Labcoach đọc lại rồi gửi"]
    end

    log --> win
    flags --> win
    win --> sig --> lvl
    lvl -->|ok| snap
    lvl -->|watch| snap
    lvl -->|at_risk| snap
    snap --> top
    snap -.-> diag -.-> top
    snap -.-> msg -.-> top
    top --> human

    style model stroke-dasharray: 5 5
    style det fill:#f0f2f5
```

Khi tầng mô hình tắt, `top` vẫn đầy đủ: mức rủi ro và `rule_trace` là phần
deterministic. Mất đi là câu diễn giải và tin nhắn soạn sẵn — Labcoach tự viết
dựa trên khối "Vì sao" hiện trên dashboard.

**Không có luồng nào tự động gửi.** `human` là mắt bắt buộc trong chuỗi.

---

## 6 · Ranh giới quyền của mô hình

```mermaid
flowchart TD
    subgraph never["Mô hình KHÔNG BAO GIỜ được"]
        n1["INSERT / UPDATE / DELETE"]
        n2["Quyết định risk_level"]
        n3["Là nguồn sự thật của một bản ghi"]
        n4["Tự gửi tin cho học viên"]
    end

    subgraph may["Mô hình được phép"]
        y1["Đọc rule_trace đã tính xong"]
        y2["Viết câu diễn giải cho người đọc"]
        y3["Soạn nháp tin nhắn"]
    end

    reason["Vì sao: bản ghi chuyên cần có thể bị khiếu nại,<br/>nên mọi giá trị phải truy về được một rule cụ thể"]

    never --> reason
    may --> reason

    style never fill:#fdeae8
    style may fill:#e3f4ea
```

Ràng buộc này được giữ ở tầng code: `llm.py` không nhận tham số `conn`, nên
không có đường nào để tầng mô hình ghi vào database.

---

## 7 · Quan hệ dữ liệu

```mermaid
erDiagram
    students ||--o{ attendance : "có bản ghi"
    students ||--o{ anomaly_flags : "bị gắn flag"
    students ||--o{ risk_snapshots : "được xếp mức"
    students ||--o{ token_usage : "đã dùng token"
    students ||--o{ device_bindings : "buộc / nhả thiết bị"
    sessions ||--o{ attendance : "chứa"
    sessions ||--o{ qr_tokens : "phát"
    sessions ||--o{ anomaly_flags : "phát sinh trong"
    qr_tokens ||--o{ token_usage : "bị tiêu thụ bởi"
    attendance ||--o{ anomaly_flags : "kích hoạt"

    students {
        TEXT student_id PK
        TEXT name
        TEXT device_hash "UNIQUE khi NOT NULL - 1 thiết bị 1 học viên"
        INTEGER device_locked_at
        TEXT pin_hash "PBKDF2, cho trang /me"
    }
    device_bindings {
        INTEGER id PK
        TEXT device_hash
        INTEGER bound_at
        INTEGER released_at "NULL = đang hiệu lực"
        TEXT released_by
        TEXT release_note "bắt buộc khi nhả"
    }
    sessions {
        INTEGER session_id PK
        TEXT date
        TEXT start_time
        TEXT state "scheduled|open|closed"
        INTEGER call_index "lượt đang mở"
        INTEGER second_call_ts
    }
    qr_tokens {
        INTEGER token_id PK
        TEXT token "128-bit ngẫu nhiên"
        INTEGER call_index
        INTEGER expires_at
        INTEGER revoked
        INTEGER use_count
    }
    attendance {
        INTEGER id PK
        INTEGER call_index "1 đầu giờ, 2 giữa giờ"
        TEXT status "present|late|absent"
        TEXT source "web|manual"
        TEXT device_hash
        TEXT fp_hash "để bắt 2 profile cùng máy"
        TEXT manual_reason "lý do, khi nhập tay"
        TEXT manual_by "Labcoach nào nhập"
        INTEGER token_valid
    }
    anomaly_flags {
        INTEGER id PK
        TEXT rule_code
        TEXT severity "low|med|high"
        INTEGER resolved
    }
    risk_snapshots {
        INTEGER id PK
        TEXT risk_level "ok|watch|at_risk"
        TEXT rule_trace "JSON, để audit"
        TEXT llm_diagnosis "NULL khi mô hình tắt"
        INTEGER sent
    }
```

---

## 8 · Máy chiếu xoay token

```mermaid
sequenceDiagram
    autonumber
    participant P as Trang /projector
    participant S as Server
    participant D as SQLite

    P->>S: GET /api/projector/token
    S->>D: token còn sống của lượt hiện tại?
    D-->>S: token + expires_at
    S-->>P: token, QR SVG, expires_in_ms, số người đã điểm danh

    loop Mỗi 200ms, đếm ngược cục bộ
        P->>P: cập nhật thanh tiến trình
    end
    Note over P: Đếm ngược ở client để thanh chạy mượt,<br/>nhưng server vẫn là nguồn sự thật của hạn dùng

    P->>S: xin lại khi còn <250ms
    S->>D: hết hạn -> INSERT token mới
    S-->>P: token mới

    opt Labcoach thấy mã bị chụp gửi ra ngoài
        P->>S: POST rotate-token
        S->>D: revoked = 1 cho mọi token đang sống
        S->>D: INSERT token mới
        S-->>P: mã mới, mã cũ chết ngay
    end
```

---

## 9 · Vòng đời thiết bị của một học viên

```mermaid
stateDiagram-v2
    [*] --> ChuaBuoc: Học viên mới vào lớp
    ChuaBuoc --> DaBuoc: Check-in lần đầu<br/>ghi device_bindings

    DaBuoc --> DaBuoc: Check-in bằng đúng máy đó
    DaBuoc --> BiChan: Dùng máy khác<br/>flag DEVICE_MISMATCH
    BiChan --> DaBuoc: Vẫn còn máy cũ, quay lại dùng

    BiChan --> ChuaBuoc: Labcoach xóa dữ liệu thiết bị<br/>ghi released_at + lý do
    DaBuoc --> ChuaBuoc: Xóa chủ động (đổi máy, trả máy mượn)

    BiChan --> DiemDanhTay: Mất máy giữa buổi<br/>không kịp xử lý thiết bị
    DiemDanhTay --> BiChan: Bản ghi tay xong,<br/>thiết bị vẫn chưa nhả

    note right of ChuaBuoc
        Máy vừa nhả cũng tự do:
        buộc được cho học viên khác.
        Cần cho trường hợp máy
        mượn của lớp.
    end note

    note right of DiemDanhTay
        source=manual · token_valid=0
        device_hash=NULL · có lý do
        -> không bao giờ lẫn với
        bằng chứng hệ thống tự thu.
    end note
```

## 10 · Hai đường thoát khi thiết bị không dùng được

```mermaid
flowchart TD
    problem(["Học viên không điểm danh được<br/>vì thiết bị"]) --> which{"Còn dùng máy đó<br/>về sau nữa không?"}

    which -->|"Không — đổi máy hẳn, mất máy"| release["Labcoach: Xóa thiết bị<br/>ở trang Danh sách lớp"]
    release --> note1["Bắt buộc nhập lý do"]
    note1 --> free["Học viên buộc máy mới ở lần check-in tới<br/>Máy cũ buộc được cho người khác"]
    free --> trace1["device_bindings + audit_log"]

    which -->|"Còn — chỉ hết pin, để quên hôm nay"| manual["Labcoach: Điểm danh tay<br/>ở màn hình buổi học"]
    manual --> reason["Chọn lý do từ danh sách đóng<br/>mất máy · máy hỏng · không vào WiFi · WiFi sập"]
    reason --> rec["Bản ghi source=manual kèm lý do"]
    rec --> trace2["manual_reason + manual_by + audit_log"]

    trace1 --> ok(["Học viên không bị vắng oan,<br/>và mọi thao tác nới phòng vệ đều truy được"])
    trace2 --> ok

    style problem fill:#fdf1dc
    style ok fill:#e3f4ea
    style release fill:#e8ecfb
    style manual fill:#e8ecfb
```

Lý do nhập tay là **danh sách đóng**, không phải ô gõ tự do: cuối khoá phải đếm
được "bao nhiêu buổi mất vì máy hỏng", mà lý do gõ tay thì không tổng hợp được.
