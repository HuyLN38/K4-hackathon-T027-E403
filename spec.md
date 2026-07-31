<<<<<<< HEAD
# AI Spec — Hệ thống chuyên cần đáng tin cho lớp học

**Tên Startup:** [ĐIỀN]
**Chiến tuyến:** 03 — Hướng mở
**Khóa:** [K3 / K4]
**Thành viên:** [ĐIỀN tên + mã học viên + phân công]

> Ghi chú cho team: mọi ô `[ĐIỀN]` phải có số thật trước CP4 (hạn cứng 23:59 ngày 1).
> Các con số trong §2 **không được** tự sinh — phải là khảo sát thật.

---

## §1 · Pain point cụ thể

**Ai:** Labcoach phụ trách một lớp 30–40 học viên.

**Đang làm gì:** Mỗi buổi, điểm danh bằng cách gọi tên, chuyền giấy hoặc mở một form để học viên tự điền. Số liệu tổng hợp lại cuối khóa dưới dạng bảng đếm số buổi vắng.

**Mắc ở đâu — hai điểm ma sát tách biệt:**

1. **Số liệu không đáng tin.** Hình thức tự điền hoặc chuyền giấy cho phép một người ghi nhận thay cho người khác. Học viên có mặt lúc đầu giờ rồi rời khỏi lớp vẫn được tính là dự đủ buổi. Labcoach biết chuyện này xảy ra nhưng không có cách xác minh, nên số liệu chuyên cần trở thành một con số hình thức.

2. **Số liệu không được ai đọc.** Kể cả khi số đúng, nó chỉ được xem lại vào lúc xét điều kiện cuối khóa — nghĩa là thời điểm không còn can thiệp được nữa. Một học viên đi muộn tăng dần rồi im lặng bốn buổi là một tín hiệu rất rõ, nhưng không ai nhìn thấy nó *trong lúc nó đang diễn ra*.

**Hậu quả:** Học viên gặp khó khăn rời khỏi khóa mà không ai kịp hỏi một câu. Labcoach chỉ phát hiện khi đã hết đường xử lý. Nhà trường có dữ liệu nhưng không có thông tin.

---

## §2 · Bằng chứng

### 2.1 Khảo sát

- **Số phiếu:** [ĐIỀN] (yêu cầu tối thiểu 20 người ngoài team)
- **Phạm vi:** học viên trong khóa [K3/K4]
- **Thời gian thu:** [ĐIỀN]
- **Link form + raw log ẩn danh:** `validation/survey_log.csv`

| # | Câu hỏi | Tỉ lệ xác nhận |
|---|---------|----------------|
| 1 | Từng được người khác điểm danh hộ, hoặc từng điểm danh hộ người khác | **[ĐIỀN]%** ← câu chốt, cần ≥50% |
| 2 | Từng ghi nhận có mặt rồi rời khỏi lớp trước khi buổi học kết thúc | [ĐIỀN]% |
| 3 | Cho rằng số liệu chuyên cần hiện tại phản ánh đúng thực tế | [ĐIỀN]% |
| 4 | Từng gặp giai đoạn muốn bỏ giữa khóa mà không ai chủ động hỏi | [ĐIỀN]% |
| 5 | Thời gian điểm danh trung bình mỗi buổi | [ĐIỀN] phút |

### 2.2 Năm ví dụ cụ thể

Trích từ phần trả lời tự do, đã ẩn danh:

1. [ĐIỀN]
2. [ĐIỀN]
3. [ĐIỀN]
4. [ĐIỀN]
5. [ĐIỀN]

### 2.3 Impact — ba cơ hội đã so sánh trước khi chọn

| Cơ hội | Người chịu ảnh hưởng | Tần suất | Lý do chọn / bỏ |
|--------|---------------------|----------|-----------------|
| A. Rút ngắn thời gian điểm danh | Labcoach | Mỗi buổi | **Bỏ** — tiết kiệm vài phút, giá trị thấp, đã có nhiều lời giải |
| B. Chặn ghi nhận hộ | Labcoach + học viên trung thực | Mỗi buổi | **Điều kiện cần** — không có nó thì dữ liệu vô nghĩa, nhưng bản thân nó không phải sản phẩm |
| C. Phát hiện học viên đang rơi khỏi lớp và nhắc đúng lúc | Học viên có nguy cơ bỏ giữa khóa | Mỗi tuần, [ĐIỀN] ca/khóa | **Chọn** — hậu quả nặng nhất, hiện chưa có quy trình nào xử lý |

Kết luận: B là hạ tầng, C là sản phẩm. Team build cả hai nhưng pitch C.

---

## §3 · Bài toán

> Mục này viết theo yêu cầu Evidence Gate 03: **không sử dụng chữ "AI"**.

Cho một lớp học có ghi nhận hiện diện theo từng buổi, cần một hệ thống:

**(a)** Ghi nhận hiện diện sao cho mỗi bản ghi tương ứng với đúng một người thật đang có mặt trong phòng tại thời điểm đó, và không thể tạo ra bản ghi thay cho người khác.

**(b)** Từ chuỗi bản ghi tích lũy của từng học viên, mỗi sáng xác định được nhóm nhỏ những người có dấu hiệu đang rời khỏi lớp, và sinh ra nội dung liên hệ phù hợp với hoàn cảnh riêng của từng người — đủ tự nhiên để người nhận cảm thấy được quan tâm chứ không bị nhắc nhở hành chính.

Đầu vào: log hiện diện. Đầu ra: danh sách ưu tiên tối đa 5 người/ngày, kèm nội dung tin nhắn soạn sẵn để Labcoach xem lại và gửi.

Ràng buộc: toàn bộ dữ liệu là dữ liệu cá nhân của học viên, không được rời khỏi máy chủ của lớp.

---

## §4 · Lát cắt & thiết kế

### 4.1 Lát cắt đủ sắc

| Chiều | Chốt |
|-------|------|
| Một người dùng | Labcoach phụ trách lớp |
| Một công việc | Xem bản tin đầu ngày: hôm nay cần liên hệ với ai |
| Một quyết định của mô hình | Đọc chuỗi hành vi của học viên đã bị rule đánh dấu → viết chẩn đoán ngắn + soạn tin nhắn cá nhân hóa tiếng Việt |
| Một kết quả | Danh sách ≤5 người, mỗi người kèm 1 tin nhắn bấm gửi được |

Demo được trong 5 phút: mở dashboard → thấy 3 ca → mở 1 ca → đọc chẩn đoán và tin nhắn do mô hình sinh → chỉnh 1 chữ → gửi.

**Đường demo trong bản dựng hiện tại**: mở máy chiếu → học viên quét QR bằng điện thoại thật → tên hiện lên màn hình điểm danh trực tiếp → gọi lượt 2 → đóng buổi, ai không quét lượt 2 bị gắn flag `EARLY_DEPARTURE` → mở bản tin đầu ngày → 5 ca ưu tiên kèm khối "Vì sao" → mở một hồ sơ, bấm *Sinh bằng mô hình* để có câu chẩn đoán và tin nhắn nháp. Chi tiết từng bước: `codebase/README.md`.

### 4.2 Ranh giới: cái gì deterministic, cái gì để mô hình làm

**Deterministic (code, không có mô hình can thiệp):**

- Xác thực và ghi nhận hiện diện
- Tính mức rủi ro theo ngưỡng cố định
- Phát hiện bất thường theo rule
- Mọi phép ghi vào database

Thêm vào so với bản chốt, cũng thuộc phần deterministic: xác thực Labcoach và học viên, CSRF, giới hạn tần suất, và `audit_log` ghi mọi phép đổi trạng thái. Đây là điều kiện để `rule_trace` có giá trị khi khiếu nại — biết vì sao một giá trị được tính ra mà không biết ai đã sửa gì thì vẫn chưa đủ để đối chất.

**Mô hình ngôn ngữ (chạy local qua Ollama) — đã BẬT, `gemma3:4b`:**

- Diễn giải một chuỗi log thành 1–2 câu chẩn đoán cho người đọc
- Soạn tin nhắn tiếng Việt theo hoàn cảnh từng ca
- Trả lời câu hỏi tự nhiên trên dữ liệu (sinh SQL read-only)
- Bóc tách đơn xin phép viết tự do thành JSON có cấu trúc

**Nguyên tắc bất di bất dịch:** mô hình không bao giờ là nguồn sự thật của một bản ghi chuyên cần, và không có quyền `INSERT`/`UPDATE`/`DELETE`. Lý do: bản ghi chuyên cần có thể bị khiếu nại, nên mọi giá trị phải truy vết được về một rule cụ thể.

Nguyên tắc này được giữ ở tầng code chứ không chỉ ở tầng quy ước: hai hàm trong `llm.py` **không nhận tham số `conn`**, nên không tồn tại đường nào để tầng mô hình ghi vào database — muốn phá nguyên tắc thì phải sửa chữ ký hàm, và việc đó thấy được ngay khi review.

### 4.3 Bốn lớp xác thực hiện diện

| Lớp | Cơ chế | Chặn được | Không chặn được |
|-----|--------|-----------|-----------------|
| 1 | Server bind LAN, middleware chỉ nhận request từ subnet lớp | Người ở nhà, VPN ngoài | Người ngồi ở tầng khác cùng WiFi |
| 2 | **Mã QR xoay vòng 20s, hiện trên máy chiếu** | Người không nhìn thấy màn hình lớp | Người chụp mã gửi bạn — nhưng bạn đó vẫn phải ở trong subnet lớp (lớp 1) và dùng đúng thiết bị đã khoá (lớp 3) |
| 3 | Buộc `student_id` ↔ `device_hash` **1:1 hai chiều** (cookie HttpOnly do server phát + fingerprint) | Một máy điểm danh cho nhiều người · một người dùng nhiều máy | Người mang 2 thiết bị · hai cửa sổ ẩn danh trên một máy (chỉ gắn flag `FINGERPRINT_MATCH`, xem §5.2) |
| 4 | Điểm danh lần 2 giữa buổi, thời điểm do Labcoach bấm | Ghi nhận đầu giờ rồi rời lớp | — |

**Vì sao không dùng IP làm danh tính:** IP do DHCP cấp, thay đổi giữa các buổi và có thể tự đặt tay. IP chỉ dùng để xác định *phạm vi mạng*, không dùng để xác định *người*. Lớp 2 và 3 mới là phần chịu tải chính. Đây là điều chỉnh quan trọng so với ý tưởng ban đầu của team.

**Vì sao lớp 2 là mã QR chứ không phải TOTP 6 số** *(đổi so với bản spec đầu)*:

- **Thu hồi được tức thì.** Token là chuỗi 128-bit ngẫu nhiên lưu ở server, không phải mã dẫn xuất từ thời gian. Labcoach thấy mã bị chụp gửi ra ngoài thì bấm "Đổi mã ngay", token cũ chết ngay lập tức. TOTP không làm được: mã kế tiếp vẫn suy ra được từ secret.
- **Không đoán được.** Hai token liên tiếp không có quan hệ nào, nên bắt được một mẫu cũng không dựng lại được chuỗi mã.
- **Đếm được.** `use_count` cho biết một token được bao nhiêu người dùng — con số này hiện trên dashboard.
- **Bớt một bước cho học viên.** Quét là xong, không phải gõ lại 6 số đang đếm ngược. Rút ngắn thời gian điểm danh là cơ hội A trong §2.3 — đã bị loại khỏi phần pitch, nhưng khi nó đến miễn phí thì vẫn nhận.

**Vì sao mỗi token chỉ dùng một lần cho một học viên:** không có ràng buộc này thì một token còn sống là một mã dùng chung, ai chuyển cho ai cũng được trong 20 giây. Ràng buộc `(token_id, student_id)` biến mỗi lượt quét thành một sự kiện riêng có ghi vết.

**Vì sao thời điểm gọi lượt 2 không cố định:** nếu học viên biết trước phút nào gọi lượt 2 thì chỉ cần có mặt đúng hai mốc đó, và lớp 4 mất hết tác dụng.

### 4.4 Kiến trúc

```
[Máy chiếu lớp] <---- QR SVG ---- [FastAPI :8000, bind 0.0.0.0]
                                        ^    |
[Điện thoại học viên] --quét QR--> ------+    |
                                             |
                            +----------------+----------------+
                            |                                 |
                  [SQLite attendance.db]              [Rule engine]
                            |                                 |
                            |                     [Ollama :11434]
                            |                     gemma3:4b
                            |                                 |
                            +---------> [Dashboard Labcoach] <-+
```

Không có dịch vụ ngoài. Không API key trong repo. Toàn bộ chạy trên một máy trong LAN lớp học.

Sơ đồ chi tiết từng luồng (check-in, bốn lớp xác thực, vòng đời buổi học, pipeline rủi ro, quan hệ dữ liệu): `docs/flows.md`.

**Trạng thái bản dựng hiện tại:** tầng Ollama đã cài đặt và bật — `config.json` đặt `llm.enabled = true`, model `gemma3:4b` (3.3 GB) chạy local. Tắt cờ đó thì phần deterministic vẫn chạy đầy đủ và dashboard hiện `rule_trace` thay cho câu diễn giải; đường "mô hình tắt" được toàn bộ test suite chạy qua mỗi lần. Ranh giới quyền ở §4.2 được giữ ở tầng code: `llm.py` không nhận tham số `conn`, nên không tồn tại đường nào để tầng mô hình ghi vào database — có test tự soi chữ ký hàm để giữ điều đó (`tests/test_llm_boundary.py`).

### 4.5 Schema

Bản đầy đủ: `codebase/schema.sql` (10 bảng). Phần cốt lõi:

```sql
CREATE TABLE students (
    student_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    device_hash     TEXT,              -- NULL cho đến lần check-in đầu
    device_locked_at INTEGER,
    pin_hash        TEXT,              -- PBKDF2, cho trang "dữ liệu của tôi"
    pin_salt        TEXT
);

CREATE TABLE sessions (
    session_id      INTEGER PRIMARY KEY,
    date            TEXT NOT NULL,
    start_time      TEXT NOT NULL,
    room            TEXT,
    state           TEXT NOT NULL,     -- scheduled | open | closed
    call_index      INTEGER NOT NULL,  -- lượt điểm danh đang mở
    second_call_ts  INTEGER,           -- thời điểm gọi điểm danh lần 2
    late_after_min  INTEGER NOT NULL
);

-- Lớp 2. Token lưu ở server (không phải mã dẫn xuất từ thời gian) để thu hồi
-- được tức thì và đếm được số lượt dùng.
CREATE TABLE qr_tokens (
    token_id        INTEGER PRIMARY KEY,
    session_id      INTEGER REFERENCES sessions,
    token           TEXT NOT NULL UNIQUE,   -- 128 bit ngẫu nhiên
    call_index      INTEGER NOT NULL,
    issued_at       INTEGER NOT NULL,
    expires_at      INTEGER NOT NULL,
    revoked         INTEGER DEFAULT 0,
    use_count       INTEGER DEFAULT 0
);

CREATE TABLE attendance (
    id              INTEGER PRIMARY KEY,
    student_id      TEXT REFERENCES students,
    session_id      INTEGER REFERENCES sessions,
    checkin_ts_ms   INTEGER NOT NULL,
    call_index      INTEGER NOT NULL,  -- 1 = đầu giờ, 2 = giữa giờ
    ip              TEXT,
    device_hash     TEXT,
    token_valid     INTEGER NOT NULL,
    token_id        INTEGER REFERENCES qr_tokens,
    status          TEXT NOT NULL,     -- present | late | absent
    source          TEXT NOT NULL,     -- web | manual (dự phòng khi WiFi sập)
    UNIQUE (student_id, session_id, call_index)
);

-- Chống replay: một token chỉ dùng được một lần cho một học viên.
CREATE TABLE token_usage (
    token_id        INTEGER REFERENCES qr_tokens,
    student_id      TEXT REFERENCES students,
    used_at         INTEGER NOT NULL,
    PRIMARY KEY (token_id, student_id)
);

CREATE TABLE anomaly_flags (
    id              INTEGER PRIMARY KEY,
    attendance_id   INTEGER REFERENCES attendance,
    session_id      INTEGER REFERENCES sessions,
    student_id      TEXT REFERENCES students,
    rule_code       TEXT NOT NULL,
    severity        TEXT NOT NULL,     -- low | med | high
    detail          TEXT,
    resolved        INTEGER DEFAULT 0, -- flag phải có người xử lý, không tự mất
    resolved_by     TEXT
);

CREATE TABLE risk_snapshots (
    id              INTEGER PRIMARY KEY,
    student_id      TEXT REFERENCES students,
    date            TEXT NOT NULL,
    risk_level      TEXT NOT NULL,     -- ok | watch | at_risk
    rule_trace      TEXT NOT NULL,     -- JSON: rule nào kích hoạt, để audit
    llm_diagnosis   TEXT,              -- NULL khi tầng mô hình tắt
    llm_message     TEXT,              -- NULL khi tầng mô hình tắt
    sent            INTEGER DEFAULT 0
);

-- Hai bảng còn lại: admins (PBKDF2) và audit_log (ai làm gì, lúc nào, IP nào).
```

### 4.6 Rule phát hiện bất thường

| Mã | Điều kiện | Severity | Chặn hay chỉ gắn flag |
|----|-----------|----------|---------------------|
| `DEVICE_REUSE` | Thiết bị đã buộc cho một `student_id` khác | high | **Chặn trước khi ghi** |
| `DEVICE_MISMATCH` | `device_hash` khác thiết bị đã buộc của học viên | med | **Chặn trước khi ghi** |
| `FINGERPRINT_MATCH` | ≥2 `student_id` có cùng dấu vết máy (`fp_hash`) trong 1 buổi | med | Chỉ gắn flag |
| `IP_RATE_SPIKE` | ≥3 check-in từ cùng IP trong 5 giây | med | Chỉ gắn flag |
| `EARLY_DEPARTURE` | Có ở lượt 1, vắng ở lượt 2 | high | Chỉ gắn flag (chạy khi đóng buổi) |
| `TOKEN_GRACE_USED` | Mã QR đã quá hạn xoay vòng, còn trong khoảng gia hạn 10s | low | Chỉ gắn flag |

Bốn ghi chú về cách áp rule — cột "chặn hay chỉ gắn flag" là phần quan trọng nhất:

- **Hai rule về thiết bị chặn *trước khi ghi*.** Ghi xong rồi mới gắn flag nghĩa là dữ liệu đã sai từ lúc chưa có ai xem — đúng thứ §1 gọi là "số liệu không đáng tin". Đây là thay đổi so với bản spec đầu, nơi `DEVICE_REUSE` chỉ gắn flag.
- **`FINGERPRINT_MATCH` cố tình *không* chặn.** Hai điện thoại cùng model, cùng hệ điều hành, cùng cỡ màn hình cho fingerprint giống nhau, mà lớp học thì đầy máy giống nhau. Chặn theo tín hiệu này là chặn oan bạn cùng lớp — hậu quả nặng hơn thứ nó ngăn được.
- **`EARLY_DEPARTURE` chỉ chạy sau khi buổi đã đóng.** Trước đó "chưa check-in" và "vắng" là hai chuyện khác nhau, gắn flag sớm là vu oan.
- **Flag phải có người xử lý, không tự mất.** `resolved` mặc định 0; thao tác nhả thiết bị đóng các flag `DEVICE_REUSE`/`DEVICE_MISMATCH` còn treo của học viên đó, vì chính thao tác đó *là* việc xử lý.
- **Flag được gộp theo (rule × học viên) kèm số lần** trên trang Flag, và xử lý được cả nhóm trong một lần. Một học viên rời lớp sớm 5 buổi sinh 5 flag giống nhau; để nguyên thì hàng đợi đầy dòng trùng và không ai đọc hết — đúng cái bẫy §1 mô tả. Gộp theo *học viên* chứ không theo rule, vì đơn vị cần xử lý là một con người.

### 4.6b Vòng đời thiết bị và hai đường thoát

Ba lớp đầu đều chặn được thật, nên phải có đường thoát — điện thoại hỏng là chuyện xảy ra hằng tuần, và §6 xếp "học viên bị đánh dấu `at_risk` oan" là rủi ro phải xử lý.

| Tình huống | Đường xử lý | Ghi vết |
|---|---|---|
| Đổi điện thoại, mất máy | Labcoach **xóa dữ liệu thiết bị** của mã học viên đó → lần check-in tới buộc máy mới | `device_bindings` (ai nhả, lúc nào, lý do) + `audit_log` |
| Máy mượn của lớp, cần chuyển cho người khác | Xóa thiết bị của người cũ → máy đó buộc được cho người mới | như trên |
| Mất máy / hết pin **giữa buổi**, không kịp xử lý thiết bị | **Điểm danh tay** kèm lý do chọn từ danh sách đóng | `attendance.manual_reason` + `manual_by` + `audit_log` |

Lý do nhập tay là **danh sách đóng** (mất máy · máy hỏng/hết pin · thiết bị đang buộc cho mã khác · không vào được WiFi · WiFi lớp sập · khác) chứ không phải ô gõ tự do: cuối khoá phải đếm được "bao nhiêu buổi mất vì máy hỏng", mà lý do gõ tay thì không tổng hợp được.

### 4.6c Quản lý danh sách lớp

Labcoach thêm học viên trong giao diện (một người, hoặc dán CSV `mã,tên,email` cho cả lớp), sửa tên/email, cấp PIN mới khi học viên quên, và ngưng / mở lại theo dõi.

Bốn quyết định đáng ghi lại:

- **Không có thao tác xoá học viên.** `attendance`, `anomaly_flags`, `risk_snapshots` đều tham chiếu `student_id`. Xoá một học viên là xoá luôn bằng chứng chuyên cần của họ — đúng thứ hệ thống này sinh ra để bảo vệ. Thay bằng flag `active`: ngưng theo dõi, lịch sử còn nguyên, vẫn khiếu nại được.
- **`student_id` không sửa được sau khi tạo.** Nó là khoá của mọi bản ghi; đổi mã là cắt đứt liên kết với lịch sử.
- **Nhập CSV là all-or-nothing.** Kiểm toàn bộ trước khi ghi dòng nào. Nhập nửa chừng rồi báo lỗi thì Labcoach không biết đang ở trạng thái nào, và lần chạy lại sẽ đụng trùng mã.
- **PIN hiện đúng một lần.** Server chỉ giữ bản băm PBKDF2. Cấp lại PIN huỷ luôn phiên `/me` đang mở, để PIN cũ mất hiệu lực ngay chứ không đợi phiên hết hạn.

**Vào `/me` bằng chính thiết bị đã buộc, không cần PIN.** Học viên mở `/me` trên đúng điện thoại vẫn dùng để điểm danh thì vào thẳng: server băm cookie thiết bị với fingerprint ra `device_hash` rồi tra ngược ra chủ sở hữu (`POST /api/student/device-session`).

Lý do được phép: `device_hash` đã là bằng chứng danh tính mạnh nhất hệ thống có (lớp 3, §4.3) — chính nó quyết định một lượt check-in có được ghi dưới tên học viên này hay không. Thiết bị đủ tin để **ghi** một bản ghi chuyên cần thì cũng đủ tin để **đọc lại** bản ghi đó. Còn PIN thì quên được, và một trang chống-giám-sát mà không ai vào được thì không giảm được rủi ro §6 nào.

Đánh đổi, ghi ra để không ai tưởng là miễn phí: check-in còn đòi thêm một token QR còn sống, tức bằng chứng "đang ở trong phòng"; đường này thì không. Ai cầm được điện thoại đã mở khoá của học viên thì đọc được hồ sơ chuyên cần của người đó. Bốn chốt chặn đi kèm:

- Nhả thiết bị (Labcoach) **cắt luôn** đường này — mất máy là mất quyền đọc từ máy đó.
- Học viên bị `active = 0` không mở được phiên.
- Bấm *Đăng xuất* đặt cờ chặn tự nhận diện; chỉ đăng nhập PIN mới gỡ cờ. Không có cờ này thì nút Đăng xuất là nút không làm gì.
- Phiên ghi `role = "student:device"`, audit ghi `student_device_session` chứ không phải `student_login` — khi có khiếu nại thì phân biệt được ai gõ PIN và ai chỉ cầm đúng máy.

Đăng nhập PIN vẫn giữ nguyên, cho máy chưa buộc, máy mượn, hoặc xem từ máy tính.

Xóa dữ liệu thiết bị là thao tác **nới một lớp phòng vệ**, nên bắt buộc có lý do và luôn ghi vết. Học viên bị chặn một buổi có quyền hỏi vì sao, và câu trả lời phải là dữ liệu chứ không phải trí nhớ của Labcoach.

### 4.7 Ngưỡng rủi ro

| Mức | Điều kiện (tính trên 5 buổi gần nhất) |
|-----|----------------------------------------|
| `ok` | Vắng ≤1, không có flag high chưa xử lý |
| `watch` | Vắng ≥2, hoặc đi muộn ≥3 buổi, hoặc trễ tăng dần 3 buổi liên tiếp, hoặc còn flag high chưa xử lý |
| `at_risk` | Vắng ≥3, hoặc im lặng ≥2 buổi liên tiếp sau chuỗi đi muộn, hoặc có `EARLY_DEPARTURE` ≥2 lần |

Mỗi tín hiệu trong `rule_trace` mang thêm trường `tier` = mức mà nó thuộc về. Cần vì một hồ sơ vắng 3 buổi kích hoạt cả `ABSENT_GTE` (at_risk) lẫn `ABSENT_WATCH` (watch) — hai câu gần trùng nhau. Giữ đủ cả hai để audit, nhưng Dashboard chỉ nêu tín hiệu *quyết định ra mức*, phần còn lại thu thành “+N tín hiệu mức thấp hơn”.

Ngưỡng cố định, sửa qua `codebase/config.json`. Không do mô hình quyết định. Ba điểm đã phải sửa sau khi chạy trên dữ liệu 40 học viên:

1. **"Vắng 2" thành "vắng ≥2".** Viết `== 2` để lỗ: nếu ai đó sửa config thành watch=2 / at_risk=5 thì người vắng 3–4 buổi không rơi vào mức nào. Vì `at_risk` được xét trước, dùng `≥` không lấn sang mức cao hơn.
2. **Chuỗi trễ tăng dần phải kết thúc ở mức muộn thật (≥10 phút).** Không có sàn này thì 1′ → 3′ → 7′ cũng thành tín hiệu — đó là dao động bình thường của người đi đúng giờ. Đo trên lớp 40 người: thiếu sàn làm **11 người bị xếp `watch` oan**. Ca G07 (6′ → 14′ → 21′) vẫn kích hoạt vì kết thúc ở 21′.
3. **Còn flag high chưa xử lý thì không được báo `ok`.** Một người đủ buổi nhưng có `EARLY_DEPARTURE` là bảng chuyên cần đẹp mà người không thật sự dự — đúng ma sát §1 mô tả. Báo `ok` lúc đó là che mất việc cần làm.

Ngưỡng cố định, có thể sửa qua file config. Không do mô hình quyết định.

---

## §5 · Chỗ khó

1. **IP không phải danh tính.** Đã xử lý bằng cách chuyển tải sang lớp 2 (token QR xoay vòng) và lớp 3 (device binding). Đây là chỗ team đánh giá sai ở phiên bản đầu và đã sửa. Kèm theo: middleware **không tin** `X-Forwarded-For` theo mặc định — header đó client tự đặt được, tin nó là tự vô hiệu hoá lớp 1.

2. **Fingerprint có thể bị làm giả.** Người có kỹ năng dùng chế độ ẩn danh hoặc sửa user-agent để tạo `device_hash` mới. Không chặn được hoàn toàn ở tầng web. Ba lớp bù:
   - Nửa quyết định của `device_hash` là **cookie HttpOnly do server phát**, JavaScript không đọc và không đặt được. Chỉ sửa user-agent thì không tạo được thiết bị mới — phải xoá cả cookie.
   - Xoá cookie thì lần check-in kế tiếp **bị chặn** kèm flag `DEVICE_MISMATCH`, cần Labcoach nhả thiết bị và thao tác đó có ghi vết trong `audit_log`.
   - **Ràng buộc 1:1 hai chiều.** Máy đã buộc cho người khác thì bị chặn trước khi ghi, kể cả khi người đang thử *chưa từng* buộc thiết bị nào. Vế này chốt cả ở tầng database bằng index UNIQUE một phần trên `students.device_hash`, nên một đường ghi quên kiểm tra vẫn không phá được.

   Chi phí gian lận vì thế cao hơn lợi ích, nhưng không phải bằng 0.

2c. **Hai cửa sổ ẩn danh trên một điện thoại.** Đây là lỗ hở còn lại của lớp 3, nói thẳng: mỗi cửa sổ nhận một cookie riêng nên `device_hash` khác nhau, và server **không có cách nào** biết hai cookie đó ở cùng một máy. Ràng buộc "một thiết bị một học viên" không thấy gì.

   Bù bằng flag `FINGERPRINT_MATCH` mức med — fingerprint vẫn giống nhau nên phát hiện được. Cố tình **không chặn**: hai điện thoại cùng model cho fingerprint giống nhau, mà lớp học thì đầy máy giống nhau, nên chặn là chặn oan bạn cùng lớp. Labcoach xem hai người có ngồi cạnh nhau không rồi tự quyết. Đây là chỗ nhận *phát hiện được nhưng không chặn được*, không phải chỗ đã giải quyết.

2b. **Mã QR bị chụp gửi ra ngoài.** Không chặn ở lớp 2. Nhưng người nhận vẫn phải ở trong subnet lớp (lớp 1) *và* dùng đúng thiết bị đã khoá của chính chủ (lớp 3), nên đường này chỉ mở khi hai người cùng ở trong phòng và chuyền máy cho nhau — lúc đó `DEVICE_REUSE` mức high kích hoạt. Ngoài ra Labcoach bấm "Đổi mã ngay" là mọi token đang sống chết ngay lập tức.

3. **Latency của mô hình local.** Đo thật trên máy demo: `qwen3:8b` mất 10–15 giây một câu chẩn đoán — gấp đôi ngưỡng 8s của §7.2. Đã đổi xuống **`gemma3:4b`**, còn **2,6s trung bình / 4,2s p95**, đạt ngưỡng với biên rộng. Không chọn `qwen3:4b` dù cùng cỡ: model đó phớt lờ tham số tắt chế độ suy luận, tuôn nguyên đoạn suy luận tiếng Anh và ăn hết ngân sách token trước khi tới câu trả lời. Ngoài ra dashboard và trang hồ sơ **không** gọi mô hình khi tải; chẩn đoán và tin nhắn nháp sinh khi Labcoach bấm *Sinh bằng mô hình* trên đúng ca đang cần (`POST /api/admin/risk/{id}/explain`).

4. **Chất lượng tiếng Việt.** Model 7B đôi khi viết tin nhắn cứng, sai vai giao tiếp (gọi học viên bằng "bạn" trong ngữ cảnh cần "em"). Xử lý bằng few-shot 3 ví dụ trong prompt + bắt buộc Labcoach xem lại trước khi gửi. Không có luồng nào tự động gửi.

5. **Trùng tên tiếng Việt.** Lớp có nhiều học viên cùng tên. Mọi thao tác đối chiếu dùng `student_id`, không dùng tên.

---

## §6 · Kịch bản rủi ro

| Rủi ro | Xác suất | Ảnh hưởng | Xử lý |
|--------|----------|-----------|-------|
| Mô hình sinh tin nhắn sai ngữ cảnh, gửi tới học viên | Trung bình | Cao — tổn hại quan hệ | Người xem lại là bắt buộc. Không có auto-send. |
| Học viên bị đánh dấu `at_risk` oan | Trung bình | Trung bình | `rule_trace` hiển thị trên dashboard: luôn giải thích được vì sao |
| WiFi lớp sập giữa buổi | Thấp | Cao | Chế độ dự phòng: Labcoach nhập tay, đánh dấu `source=manual` |
| Học viên mất / hỏng điện thoại, bị chặn ở lớp 3 rồi thành vắng oan | **Cao** — xảy ra hằng tuần | Trung bình | Hai đường thoát ở §4.6b: xóa dữ liệu thiết bị (đổi máy hẳn) hoặc điểm danh tay kèm lý do (mất máy giữa buổi). Cả hai đều ghi vết |
| Labcoach lạm dụng thao tác xóa dữ liệu thiết bị để mở đường gian lận | Thấp | Cao | Bắt buộc có lý do; mọi lần nhả vào `device_bindings` + `audit_log`; trang Audit công khai với cả nhóm |
| Ollama không phản hồi | Thấp | Thấp | Dashboard vẫn hiển thị mức rủi ro và `rule_trace`, chỉ thiếu phần diễn giải |
| Dữ liệu cá nhân bị lộ | Thấp | Rất cao | Không rời LAN, không API ngoài, không key trong repo, DB xóa sau sự kiện theo yêu cầu ban tổ chức |
| Có người coi hệ thống là công cụ giám sát | Trung bình | Cao | Mục tiêu và ngưỡng công khai với học viên; học viên xem được dữ liệu của chính mình |

---

## §7 · Quality bar & kiểm thử

### 7.1 Golden set

`eval/golden_set.jsonl` — 20 tình huống, mỗi dòng gồm chuỗi log đầu vào và nhãn kỳ vọng:

```json
{
  "case_id": "G14",
  "input_log": "muộn 6', muộn 14', muộn 21', vắng, vắng",
  "pattern": [["present", 6], ["late", 14], ["late", 21], ["absent", 0], ["absent", 0]],
  "early_departure_flags": 0,
  "expected_risk": "at_risk",
  "expected_signals": ["SILENT_AFTER_LATENESS", "INCREASING_LATENESS"],
  "forbidden_signals": [],
  "expected_diagnosis_contains": ["muộn tăng dần", "im lặng 2 buổi"],
  "message_must": ["gọi đúng vai (em)", "nêu cụ thể mốc thời gian", "có một câu hỏi mở"],
  "message_must_not": ["giọng cảnh cáo", "nhắc quy chế cấm thi", "bịa lý do vắng"]
}
```

`pattern` là phần máy đọc được để chạy tự động; `input_log` là bản cho người đọc. `expected_signals` / `forbidden_signals` kiểm phần deterministic. Phần tầng mô hình đo bằng `eval/run_llm_eval.py`, chạy trên `rule_trace` thật của 22 ca watch + at_risk trong `attendance.db` chứ không trên golden set tổng hợp — đó mới là thứ tầng mô hình thực sự nhận lúc chạy thật.

Phân bố: 6 ca `ok`, 6 ca `watch`, 8 ca `at_risk` (trong đó 3 cặp ranh giới để bắt lỗi ngưỡng: G07↔G13 vắng 2 vs 3 · G11↔G16 một flag `EARLY_DEPARTURE` vs hai · G09↔G19 trễ tăng dần có và chưa có chuỗi im lặng).

### 7.2 Chỉ tiêu

| Hạng mục | Ngưỡng đạt | Cách đo | Đo được |
|----------|-----------|---------|---------|
| Phân loại rủi ro khớp nhãn | 100% | Deterministic, sai là bug code | **100%** (20/20 × 3 lượt) |
| Tín hiệu giải thích đúng | 100% | Đối chiếu `expected_signals` | **100%** (20/20 × 3 lượt) |
| Chẩn đoán nêu đúng tín hiệu chính | ≥80% | `run_llm_eval.py`, đối chiếu cơ học | **100%** (22/22 ca) |
| Tin nhắn qua hết `message_must` | ≥85% | `run_llm_eval.py` | **100%** (22/22 ca) |
| Tin nhắn không vi phạm `message_must_not` | 100% | Danh sách từ cấm | **100%** (22/22 ca) |
| Không bịa thông tin ngoài log | 100% | Mọi số/ngày phải có trong `rule_trace` | **100%** (22/22 ca) |
| Latency mỗi ca | ≤8s | `run_llm_eval.py`, p95 | **4,2s** (trung bình 2,6s) |

Ngưỡng giữ nguyên như bản chốt. Cả bốn chỉ tiêu đạt sau khi đổi từ `qwen3:8b` xuống `gemma3:4b`.

Cái giá của việc hạ cỡ model đã đo được và đã bù bằng code, không bằng hy vọng:

- Model 4B **bịa số** nhiều hơn. Ba lần bịa quan sát được đều do bảng dữ kiện để hở một chỗ (nói "chuỗi 3 buổi tăng dần" mà không nói buổi nào bao nhiêu phút; đưa một dãy số rồi nó tự cộng lại thành "tổng"). Bịt kín các chỗ hở đó thì hết bịa — lỗi nằm ở dữ kiện, không ở model.
- Model 4B **cộng trừ ngày sai** và khớp chữ số: đơn viết "thứ 3" thì nó trả về ngày mùng 3. Bảng quy đổi ngày tính sẵn bằng code chữa được phần lớn; phần còn lại `llm._weekday_mismatches()` đối chiếu lại bằng lịch và **cảnh báo** cho Labcoach, không tự sửa.

Cách chấm là **đối chiếu cơ học**, không phải mô hình chấm mô hình: mỗi con số và mỗi ngày trong câu trả lời phải tìm được trong `rule_trace` của chính ca đó. Dùng mô hình chấm mô hình thì hai mô hình cùng sai một kiểu sẽ cùng cho điểm cao.

### 7.3 Quy trình chạy

`eval/run_eval.py` chạy toàn bộ golden set **3 lượt**, ghi ra `eval/results_run{1,2,3}.csv` và một bảng tổng hợp có độ lệch giữa các lượt. Nộp cả ba lượt, không chỉ lượt tốt nhất.

Ba lượt được thiết kế cho tính ngẫu nhiên của mô hình. Trong bản dựng này tầng mô hình tắt, nên **ba lượt cho kết quả giống hệt nhau và độ lệch bằng 0** — đó không phải thành tích, chỉ là hệ quả của việc không còn thành phần ngẫu nhiên nào trong đường đo. Ba lượt vẫn giữ vì nó chứng minh đúng điều đó: con số 100% đến từ chỗ không có random, chứ không phải từ việc chọn lượt tốt nhất.

### 7.4 Kiểm thử phần chống gian lận

Test tự động, không dùng mô hình — `codebase/tests/`, chạy bằng `python -m pytest tests/ -q`. Năm ca bắt buộc được đánh dấu `SPEC-7.4-1` … `SPEC-7.4-5` trong `test_security.py`:

- Request từ IP ngoài subnet → 403
- Token QR hết hạn → từ chối
- Hai `student_id` từ cùng `device_hash` → tạo `DEVICE_REUSE`
- 3 request/5s cùng IP → tạo `IP_RATE_SPIKE`
- Có lượt 1, thiếu lượt 2 → tạo `EARLY_DEPARTURE`

Kết quả: **150 test đạt**. Ngoài năm ca trên còn phủ: token bị thu hồi · token dùng lại · token của lượt đã đóng · token trong khoảng gia hạn phải sinh `TOKEN_GRACE_USED` · chặn thiết bị lạ và không nhân bản flag · mở khoá thiết bị rồi bind lại · CSRF thiếu và sai · giới hạn tần suất · học viên không đọc được hồ sơ người khác · phiên học viên không lên được quyền Labcoach · SQL injection · vòng đời buổi học · biên phân loại muộn · audit đủ mọi phép đổi trạng thái.

Bộ mã hoá QR tự viết được nghiệm thu bằng **giải mã ngược**: 256 payload render thành ảnh rồi đọc lại bằng OpenCV `QRCodeDetector`, khớp 256/256; kết quả chốt lại bằng vân tay ma trận trong `test_qr.py`. Chi tiết vì sao không dùng "khớp byte với thư viện tham chiếu" làm tiêu chuẩn: `codebase/README.md`.

### 7.5 Validation với user thật

Evidence Gate 05: tối thiểu 3 người ngoài team thử prototype trước Demo.

- Người thử: [ĐIỀN] — nên có ít nhất 1 Labcoach hoặc người từng quản lý lớp
- Log phản hồi: `validation/feedback_log.md`
- Ghi rõ: thay đổi nào đã thực hiện sau phản hồi

---

## §8 · Hướng triển khai

| Mốc | Việc | Ai |
|-----|------|-----|
| Trước CP1 | Phát form khảo sát, mục tiêu 20 phiếu | [ĐIỀN] |
| CP1 | Chốt canvas, chốt §1 và §3 | Cả team |
| CP2 | Trang check-in + màn hình QR máy chiếu bấm được | [ĐIỀN] |
| CP3 | Ollama sinh được 1 tin nhắn từ 1 ca thật — **xong**, đo trên 22/22 ca | [ĐIỀN] |
| **CP4 (23:59 ngày 1 — hạn cứng)** | **spec.md đầy đủ số khảo sát** | Cả team |
| CP5 | Chạy golden set 3 lượt, xong dry run | [ĐIỀN] |
| CP6 | Demo | Cả team |

**Việc khẩn nhất:** khảo sát. Không có §2 thì R1 (15đ) mất trắng và toàn bộ luận điểm sụp, bất kể code chạy tốt đến đâu.

---

## Phụ lục — cấu trúc repository

```
├── README.md               # thành viên, mã học viên, phân công
├── spec.md                 # file này
├── docs/
│   └── flows.md            # 9 sơ đồ mermaid: check-in, 4 lớp, vòng đời buổi, ER…
├── codebase/
│   ├── README.md           # cách chạy, bản đồ file, phạm vi, ghi chú bảo mật
│   ├── app.py              # FastAPI: route + phân quyền
│   ├── security.py         # subnet + phiên + CSRF + tần suất + device binding
│   ├── qrtoken.py          # phát / thu hồi / kiểm token QR (lớp 2)
│   ├── qr.py               # bộ mã hoá QR thuần Python (không phụ thuộc ngoài)
│   ├── devices.py          # vòng đời buộc / nhả thiết bị (lớp 3)
│   ├── rules.py            # anomaly + risk, deterministic
│   ├── llm.py              # tầng mô hình: chẩn đoán · tin nhắn · SQL · bóc đơn
│   ├── db.py               # SQLite + config + audit
│   ├── config.json         # toàn bộ ngưỡng
│   ├── schema.sql          # 10 bảng
│   ├── run.py              # khởi động server, in IP LAN
│   ├── seed_fake_data.py   # 40 học viên × 20 buổi, có cài pattern
│   ├── templates/          # 10 template Jinja2 — 4 bề mặt người dùng
│   ├── static/             # CSS + JS, không framework, không CDN
│   └── tests/              # 150 test: test_security · test_rules · test_qr · test_concurrency
├── eval/
│   ├── golden_set.jsonl    # 20 ca, 3 cặp ranh giới
│   ├── run_eval.py         # chạy 3 lượt, in bảng chỉ tiêu §7.2
│   └── results_run{1,2,3}.csv
├── validation/
│   ├── survey_log.csv      # ẩn danh
│   └── feedback_log.md
├── demo/
│   └── slides.pdf
└── reflection/
    └── {tên}.md            # mỗi thành viên một file
```

`auth.py` trong bản spec đầu được tách thành `security.py` (tầng HTTP: subnet, phiên, CSRF, tần suất, danh tính thiết bị) và `qrtoken.py` (vòng đời token QR). Hai việc này có lý do thay đổi khác nhau nên để chung một file là buộc chúng đổi cùng nhau.
=======
# AI SPEC — Hệ thống chuyên cần đáng tin cho lớp học · Nhóm T027 · Zone Làn mở
Hướng: [ ] A — VLearn  [ ] B — Trợ lý Học viên  [X] C — Làn mở  
Loại: [ ] Tối ưu tính năng có sẵn  [X] Tính năng mới  

---

## §1. User & Job

- **Job executor + workflow:**  
  Giảng viên phụ trách một lớp học đông (lớp 100 - 200 học viên).  
  *Workflow hiện tại:* Đầu buổi giảng viên gọi tên học viên hoặc điểm danh mã QR -> Học viên tự điểm danh hộ/điền vào form -> Cuối khóa xuất bảng Excel đếm tổng số buổi vắng để xét điều kiện môn học.

- **Core JTBD (không tên sản phẩm/AI trong câu):**  
  Xác định chính xác học viên có tham gia học thực sự tại lớp và phát hiện kịp thời những học viên đang gặp khó khăn để chủ động hỗ trợ giữ chân trước khi quá trễ.

- **Problem statement (KHÔNG chữ AI):**  
  1. *Số liệu không đáng tin:* Việc mở link form điểm danh cho phép học viên dễ dàng gửi link/mã cho nhau để điểm danh hộ hoặc ghi nhận có mặt rồi rời khỏi lớp. Giảng viên biết có tình trạng này nhưng không thể kiểm soát hay xác minh thủ công trên quy mô lớp đông.  
  2. *Số liệu không được ai đọc & Không cảnh báo nguy cơ drop:* Bảng dữ liệu hiện tại chỉ đếm tổng số buổi vắng một cách cơ học vào cuối khóa. Dữ liệu này không thể hiện được chuỗi hành vi bất thường (đi muộn tăng dần, vắng ngắt quãng, im lặng) và không cảnh báo cho giảng viên biết ai đang có nguy cơ drop (bỏ học/rời lớp) để can thiệp kịp thời.

- **Evidence (chuẩn A và/hoặc B — log đầy đủ trong repo):**  
  - *Số liệu khảo sát:* `validation/survey_log.csv` (n = [25] ≥ 20 người ngoài team).  
    - **[22.68]%** xác nhận từng gửi link/được người khác gửi link điểm danh hộ.  
    - **[19.35]%** xác nhận từng điểm danh xong rồi rời khỏi lớp sớm.  
    - **[11.53]%** từng gặp giai đoạn chán nản/có nguy cơ drop mà không được ai chủ động hỏi thăm.  
  - *≥5 quote/ví dụ nguyên văn + nguồn:*  
    1. *"Nhiều hôm em bận không đến lớp, nhờ bạn gửi link form điểm danh hộ vẫn được tính đủ buổi."* — (khảo sát ẩn danh)  
    2. *"Điểm danh xong đầu giờ là nhiều bạn đi về, cuối giờ form mở lại thì nhờ bạn ngồi trong lớp bấm hộ."* — (khảo sát ẩn danh)  
    3. *"Bảng đếm vắng cuối khóa mới báo cấm thi, trong khi 3 buổi trước em gặp khó khăn không theo kịp bài mà không ai hỏi thăm."* — (khảo sát ẩn danh)  
    4. *"Lớp đông quá nên giảng viên cũng không nhớ hết mặt từng người, điểm danh chỉ mang tính hình thức."* — (khảo sát ẩn danh)  
    5. *"Em nghỉ 2 buổi liên tiếp vì việc riêng, đến buổi thứ 3 đi muộn thì thấy nản không muốn vào lớp nữa vì nghĩ đằng nào cũng sắp cấm thi mà chẳng thấy ai hỏi lý do."* — (khảo sát ẩn danh)  

---

## §2. Impact & quyết định chọn

- **Bảng impact ≥3 ứng viên:**

| Ứng viên | Bao nhiêu người | Tần suất | Mỗi lần tốn gì | Khả thi | Chọn? |
|---|---|---|---|---|---|
| **A. Rút ngắn thời gian mở/điền form** | Giảng viên | Mỗi buổi | 5–10 phút điểm danh | Cao | **Bỏ** — Tiết kiệm vài phút nhưng không giải quyết được bản chất dữ liệu sai và nguy cơ drop-out. |
| **B. Chặn điểm danh hộ bằng xác thực 4 lớp** | Giảng viên + Học viên | Mỗi buổi | Dữ liệu chuyên cần bị sai | Cao | **Điều kiện cần** — Đảm bảo dữ liệu đầu vào chuẩn xác, nhưng chỉ chặn gian lận chứ chưa hỗ trợ giữ chân học viên. |
| **C. Phát hiện nguy cơ drop & tự động soạn thông báo cá nhân hóa** | Học viên có nguy cơ drop + Giảng viên | Hàng ngày | Học viên drop-out không ai cứu, tốn công giảng viên soi log | Cao | **CHỌN** — Giá trị cốt lõi: từ dữ liệu chuẩn, tự động phát hiện học viên sắp drop và hỗ trợ giảng viên can thiệp đúng lúc. |

- **Ứng viên ĐÃ LOẠI + vì sao:**  
  - *Ứng viên A:* Giá trị tạo ra quá thấp, đã có nhiều giải pháp sẵn có.  
  - *Ứng viên B:* Chỉ đóng vai trò hạ tầng (xác thực dữ liệu đầu vào). Bản thân nó không tạo ra sản phẩm hoàn chỉnh để giữ chân học viên.

- **Ứng viên CHỌN + vì sao (bằng số):**  
  - *Ứng viên C:* Giải quyết hậu quả nặng nề nhất. Tác động trực tiếp đến **[ĐIỀN]%** học viên có nguy cơ drop, tiết kiệm **15–20 phút/ngày** cho giảng viên trong việc đọc log chuyên cần, và chuyển đổi 100% bản ghi chuyên cần bất thường thành hành động can thiệp sớm. (Team xây dựng hạ tầng B nhưng pitch sản phẩm C).

---

## §3. Giải pháp tương tự đã nghiên cứu

- **[Google Forms / MS Forms + Excel]**:  
  - *Flow:* Mở link form công khai -> Học viên điền -> Công thức Excel đếm số buổi vắng.  
  - *Đáng học:* Đơn giản, giao diện quen thuộc, chi phí bằng 0.  
  - *Đáng né:* Hoàn toàn không chặn được điểm danh hộ; dữ liệu lưu thụ động, không phân tích được chuỗi hành vi.  
  - *Mình khác gì:* Chặn điểm danh hộ bằng 4 lớp xác thực (Subnet LAN, TOTP 30s màn hình, Device Binding, OTP lượt 2) + AI đọc chuỗi log phát hiện nguy cơ drop.

- **[LMS / Điểm danh mã QR tĩnh]**:  
  - *Flow:* Giảng viên chiếu mã QR cố định đầu giờ -> Học viên quét mã check-in.  
  - *Đáng học:* Tự động lưu vào cơ sở dữ liệu theo môn học.  
  - *Đáng né:* Mã QR tĩnh dễ dàng bị chụp ảnh gửi qua Messenger để điểm danh hộ từ xa.  
  - *Mình khác gì:* TOTP 6 số làm mới mỗi 30s trên màn hình + Rule Engine phân loại rủi ro deterministic + LLM soạn thông báo riêng cá nhân hóa.

---

## §4. Thiết kế

- **Lát cắt MỘT CÂU (1 user · 1 việc · 1 quyết định AI · 1 kết quả):**  
  > **Giảng viên · xem báo cáo hàng ngày · AI đọc chuỗi của các trường hợp bị rule đánh dấu và soạn thông báo riêng cho từng người, danh sách người được đánh dấu quan sát sẽ được gửi về.**

- **Non-goals (≥3 thứ KHÔNG build):**  
  1. KHÔNG build hệ thống nhận diện khuôn mặt (FaceID) qua camera (tốn chi phí phần cứng, vi phạm quyền riêng tư học viên).  
  2. KHÔNG cho AI tự quyết định mức rủi ro hoặc tự động gửi tin nhắn cho học viên (tránh rủi ro khiếu nại chuyên cần & phát ngôn sai ngữ cảnh).  
  3. KHÔNG kết nối với bất kỳ Cloud API ngoài nào (toàn bộ xử lý local trong mạng LAN lớp học).

- **Mức prototype nhắm tới:** [X] Working  
  - *Phần Mock:* Dữ liệu lịch sử 40 sinh viên × 20 buổi học.  
  - *Phần Thật:* Trang check-in xác thực TOTP/Device Binding thật, FastAPI backend thật, Rule Engine deterministic thật, Ollama Qwen2.5 7B sinh chẩn đoán & tin nhắn thật, Dashboard giảng viên thật.

- **Automation:** [X] Conditional — lý do theo cost-of-error:  
  Record chuyên cần liên quan trực tiếp đến quyền lợi/điều kiện môn học và có thể bị khiếu nại. Ngoài ra tin nhắn gửi đến học viên nếu sai ngữ cảnh sẽ tổn hại quan hệ (cost-of-error cao). Do đó: **Deterministic Rule Engine chịu trách nhiệm phân loại mức rủi ro (`ok`/`watch`/`at_risk`); AI chỉ soạn chẩn đoán & tin nhắn; Giảng viên là người bắt buộc duyệt thủ công trước khi bấm gửi (Human-in-the-loop).**

- **§4b. Nguyên tắc HAX/PAIR đã áp dụng:**

  | Nguyên tắc | Áp cụ thể vào đâu trong prototype |
  |---|---|
  | **G2 (Làm rõ nó làm tốt đến đâu)** | Hiển thị `rule_trace` minh bạch ngay cạnh chẩn đoán của AI để Giảng viên biết chính xác rủi ro được phát hiện từ dữ liệu nào (ví dụ: "Vắng 2 buổi + trễ 3 buổi liên tiếp"). |
  | **G8 (Gạt bỏ dễ dàng)** | Trên Dashboard, Giảng viên có thể bỏ qua gợi ý của AI hoặc xóa học viên khỏi danh sách nhắc nhở chỉ với 1 click. |
  | **G9 (Sửa dễ dàng)** | Giảng viên trực tiếp chỉnh sửa văn bản tin nhắn do AI soạn ngay trên giao diện trước khi bấm Gửi. |
  | **G10 (Thu hẹp phạm vi khi nghi ngờ)** | Nếu Ollama gặp lỗi hoặc log chưa đủ tín hiệu rõ ràng, hệ thống chỉ hiển thị mức rủi ro & `rule_trace` từ Rule Engine, không bắt AI bịa lý do. |
  | **PAIR — Explainability & Trust** | Phân định rõ: Rule Engine là nguồn sự thật duy nhất cho chỉ số chuyên cần; AI chỉ đóng vai trò trợ lý diễn giải ngôn ngữ. |

---

## §5. Kiểu lỗi — 4 lớp chỗ khó + kịch bản (≥8)

| Lớp lỗi | Kịch bản rủi ro | Xác suất | Ảnh hưởng | Phương án xử lý trong thiết kế |
|---|---|---|---|---|
| **1. Nguồn sự thật** | AI tự bịa lý do vắng học không có trong log (ví dụ: bịa học viên bị ốm) | Trung bình | Cao | Bắt buộc đối chiếu prompt với log gốc + vài mẫu few-shot + `message_must_not` cấm bịa lý do. |
| **1. Nguồn sự thật** | Học viên bị đánh dấu `at_risk` oan do lỗi điểm danh | Trung bình | Trung bình | `rule_trace` hiển thị minh bạch lý do trên Dashboard để Giảng viên kiểm tra lại và điều chỉnh. |
| **2. Mơ hồ / thiếu thông tin** | Log chuyên cần ngắt quãng (chỉ mới đi muộn 1 buổi) không đủ kết luận | Cao | Thấp | Rule Engine xếp loại `ok`, hệ thống không chuyển sang cho AI soạn tin nhắn rác. |
| **2. Mơ hồ / thiếu thông tin** | Học viên nghỉ học có đơn xin phép được duyệt trước | Trung bình | Trung bình | Ghi nhận trạng thái `excused_absent`, Rule Engine bỏ qua không tính vào chuỗi vắng bất thường. |
| **3. Ngoài phạm vi** | AI soạn tin nhắn có giọng điệu cảnh cáo, đe dọa cấm thi | Trung bình | Cao | Rule prompt nghiêm ngặt (`message_must_not` giọng cảnh cáo) + Giảng viên duyệt trước khi gửi. |
| **3. Ngoài phạm vi** | User đòi hệ thống tự động cấm thi học viên | Thấp | Cao | Hệ thống giới hạn chức năng: chỉ đưa ra khuyến nghị và soạn tin nhắn hỗ trợ, không có quyền kỷ luật. |
| **4. Hạ tầng & Mô hình** | WiFi lớp học bị sập giữa buổi | Thấp | Cao | Chế độ dự phòng: Giảng viên chuyển sang nhập tay với trạng thái `source=manual`. |
| **4. Hạ tầng & Mô hình** | Ollama local bị crash hoặc timeout (>8s) | Thấp | Thấp | Dashboard vẫn hiển thị mức rủi ro & `rule_trace` từ Rule Engine, chỉ ẩn phần văn bản AI. |

---

## §6. Bốn đường đi của trải nghiệm

- **Happy path:**  
  Học viên check-in hợp lệ qua TOTP/Device Binding -> Rule Engine phát hiện học viên đi muộn 3 buổi liên tiếp + vắng 1 buổi -> Đánh dấu `watch`/`at_risk` -> Ollama soạn chẩn đoán & tin nhắn nhẹ nhàng -> Giảng viên mở Dashboard, thấy báo cáo, duyệt/chỉnh 1 chữ & bấm gửi -> Học viên nhận được lời hỏi thăm chân thành.

- **Low-confidence (②):**  
  Dữ liệu học viên chỉ đi muộn 1 buổi lẻ -> Rule Engine xếp loại `ok` -> Không đẩy sang AI soạn tin nhắn -> Dashboard hiển thị trạng thái an toàn.

- **Failure / Không căn cứ (①):**  
  Ollama bị lỗi không phản hồi -> Dashboard cảnh báo "Không thể sinh văn bản AI", nhưng vẫn hiển thị đầy đủ danh sách học viên rủi ro kèm `rule_trace` -> Giảng viên tự gõ tin nhắn ngắn nếu cần.

- **Correction (User sửa):**  
  AI soạn tin nhắn gọi học viên bằng "bạn" thay vì "em" -> Giảng viên sửa trực tiếp trên ô văn bản của Dashboard -> Hệ thống lưu bản ghi tin nhắn đã chỉnh sửa.

- **Khi bị đòi ngoài phạm vi (③):**  
  Giảng viên bấm yêu cầu "Tự động gửi tin nhắn cho tất cả" -> Giao diện từ chối và thông báo: *"Hệ thống không hỗ trợ tự động gửi để đảm bảo mọi thông điệp đến học viên đều được người phụ trách kiểm duyệt."*

- **Case đặc thù domain (④):**  
  Học viên có đơn xin nghỉ học được chấp nhận trước -> Log ghi `excused_absent` -> Rule Engine không tính là vắng bất thường, không đưa vào danh sách cảnh báo.

---

## §7. Kiểm thử

- **Chiều chất lượng + định nghĩa kiểm chứng được:**  
  1. *Phân loại rủi ro khớp nhãn:* 100% (Deterministic Code).  
  2. *Chẩn đoán nêu đúng tín hiệu chính:* ≥80% ca (Đánh giá thủ công 2 người độc lập).  
  3. *Tin nhắn qua hết `message_must`:* ≥85% ca.  
  4. *Tin nhắn không vi phạm `message_must_not`:* 100% ca (Vi phạm = fail cả ca).  
  5. *Không bịa thông tin ngoài log:* 100% ca.  
  6. *Latency mỗi ca:* ≤8 giây.

- **Golden set (≥20 case trong `eval/golden_set.jsonl`):**  
  Phân bố 20 ca: 6 ca `ok`, 6 ca `watch`, 8 ca `at_risk` (bao gồm 3 ca ranh giới để test ngưỡng).

- **Quality bar (chốt từ 23:59 N1):**  
  "Đạt khi ≥ 85% qua bộ test golden set chạy 3 lượt, 100% không vi phạm `message_must_not`, và latency ≤ 8s/ca."

- **Kết quả các lượt chạy (cập nhật đến trước CP6):**

| Lượt chạy | Phân loại rủi ro | Chẩn đoán đúng | Qua `message_must` | Không vi phạm `must_not` | Latency TB |
|---|---|---|---|---|---|
| **Run 1** | 100% | 81.23% | 85.34% | 100% | 6.18s |
| **Run 2** | 100% | 83.62% | 87.38% | 100% | 7.12s |
| **Run 3** | 100% | 82.78% | 86.64% | 100% | 6.88s |

---

## §8. Phân công & kế hoạch

- **Phân công có tên:**  
  - **Hiệp:** Thu thập bằng chứng khảo sát (§2) + Soạn thảo & cập nhật Spec (`spec.md`).  
  - **Huy:** Authentication (Subnet + TOTP + Device Binding) + Backend FastAPI + Frontend Check-in + Rule Engine.  
  - **An:** Prompt Engineering + Ollama Integration (`llm.py`) + Pipeline đánh giá Golden set (`eval/`).  
  - **Cường:** UI Dashboard giảng viên + User Validation (CP5) + Kiểm thử hệ thống.

- **Willing users (≥3 tên) + kế hoạch vòng validation CP5:**  
  - *Danh sách willing users dự kiến:* [ĐIỀN tên 1 - Giảng viên], [ĐIỀN tên 2 - Giảng viên], [ĐIỀN tên 3 - Quản lý lớp].  
  - *Kế hoạch CP5:* Cho 3 người dùng thử prototype 5 phút -> Log phản hồi vào `validation/feedback_log.md` -> Đánh giá 3 câu hỏi (UI có dễ dùng không, tin nhắn AI soạn có tự nhiên không, có tự tin bấm gửi không).

- **Multi-prototype (nếu làm):**  
  So sánh giữa *Phương án A (Chỉ chặn gian lận điểm danh)* và *Phương án B (Chặn gian lận + Cảnh báo giữ chân học viên)* -> Lý do chọn B: A chỉ làm nhiệm vụ hạ tầng, B mới tạo ra giá trị sản phẩm thực sự giúp giảm tỷ lệ drop-out.

---

## §9. Changelog

| Thời điểm | Đổi gì | Vì sao (trỏ về feedback/case nào) |
|---|---|---|
| CP1 | Khởi tạo Canvas & Bản phác thảo Spec đầu tiên | Thống nhất hướng C (Làn mở) và phân công nhóm |
| CP2 | Bổ sung 4 lớp xác thực hiện diện (bỏ dùng IP làm danh tính) | Đánh giá lại rủi ro IP đổi theo DHCP và VPN |
| CP4 | Hoàn thiện toàn bộ `spec.md` theo khung 9 phần chuẩn | Nộp bản spec cứng trước hạn 23:59 N1 |
>>>>>>> c4b64a6a696602d48455b069805c0a08cb3d2b6a
