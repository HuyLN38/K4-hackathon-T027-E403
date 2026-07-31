# Prototype — hệ thống chuyên cần đáng tin cho lớp học

Mức prototype: **Working** cho phần deterministic, **chưa cài đặt** cho tầng mô hình
ngôn ngữ (xem [Phạm vi](#phạm-vi-cái-gì-chạy-cái-gì-không) bên dưới).

Sơ đồ luồng: [`../docs/flows.md`](../docs/flows.md) · Spec: [`../spec.md`](../spec.md)

---

## Chạy thử

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python seed_fake_data.py --reset          # 40 học viên giả × 20 buổi, in ra mật khẩu
python run.py                             # bind 0.0.0.0:8000, in ra IP LAN
```

### Tầng mô hình (tuỳ chọn)

App chạy đủ mà không cần Ollama — thiếu nó thì chỉ mất phần diễn giải, không mất
trang nào. Muốn bật:

```bash
brew install ollama                       # hoặc: curl -fsSL https://ollama.com/install.sh | sh
ollama serve &                            # nghe ở 127.0.0.1:11434
ollama pull gemma3:4b                     # 3.3 GB, tải một lần
```

`config.json` đã đặt sẵn `llm.enabled = true` và `model = "gemma3:4b"`. Đổi model
thì sửa đúng khoá đó. Tắt tầng này bằng `llm.enabled = false`; mọi trang vẫn chạy.

Trang **Trợ lý** (`/admin/assistant`) hiện trạng thái model ngay góc phải, nên
không phải đoán khi nó không trả lời.

Toàn bộ chạy local: không dịch vụ ngoài, không API key, dữ liệu học viên không rời
khỏi máy này.

`run.py` in ra ba địa chỉ:

| Bề mặt | Đường dẫn | Ai dùng |
|---|---|---|
| Điểm danh | `/` → quét QR → `/checkin?t=…` | Học viên, trên điện thoại |
| Máy chiếu | `/projector` | Labcoach chiếu lên màn hình lớp |
| Dashboard | `/admin` | Labcoach — bản tin đầu ngày |
| Flag | `/admin/anomalies` | Labcoach — hàng đợi flag bất thường, đã gộp |
| Trợ lý | `/admin/assistant` | Labcoach — hỏi dữ liệu bằng tiếng Việt, bóc đơn xin phép |
| Dữ liệu của tôi | `/me` | Học viên tự xem hồ sơ — vào thẳng nếu đang dùng đúng máy đã buộc |

`seed_fake_data.py` sinh mật khẩu Labcoach ngẫu nhiên và ghi toàn bộ PIN học viên
ra `seed_credentials.txt` (đã nằm trong `.gitignore`). Muốn đặt mật khẩu cố định:
`--admin-password 'chuỗi-của-bạn'`.

### Dữ liệu có bị mất khi khởi động lại không?

**Không.** `run.py` chỉ gọi `init_db()`, mà `schema.sql` toàn `CREATE TABLE IF NOT
EXISTS` — không có câu `DROP` nào. Tắt server rồi bật lại thì dữ liệu còn nguyên.

Chỗ duy nhất xoá dữ liệu là `seed_fake_data.py --reset`, và nó có ba lớp chặn:

| Lệnh | Kết quả |
|---|---|
| `python seed_fake_data.py` | Database đã có dữ liệu → **dừng**, in ra đang có bao nhiêu, không đụng gì |
| `python seed_fake_data.py --reset` | In ra sắp mất gì → **tự sao lưu** `attendance.db.bak-<thời-điểm>` → bắt gõ `xoa` để xác nhận |
| `python seed_fake_data.py --reset --yes` | Bỏ qua xác nhận (cho script tự động) — **vẫn sao lưu** |

Sao lưu là bắt buộc kể cả khi `--yes`: bản ghi chuyên cần có thể bị khiếu nại, nên
một lệnh gõ nhầm lúc 8h sáng không được phép là đường một chiều. Muốn khôi phục:
`cp attendance.db.bak-<thời-điểm> attendance.db`.

### Đường demo 5 phút

1. `/admin/sessions` → **Tạo buổi** cho hôm nay → **Mở điểm danh**
2. `/projector` → QR hiện lên, đổi mỗi 20 giây
3. Quét bằng điện thoại (cùng WiFi) → nhập mã học viên → thấy "đã ghi nhận"
4. `/admin/sessions` → **Xem** → thấy tên vừa hiện lên trong danh sách trực tiếp
5. **Gọi lượt 2** → quét lại → **Đóng buổi** → ai không quét lượt 2 bị gắn flag `EARLY_DEPARTURE`
6. `/admin` (Dashboard) → **Tính lại** → 5 ca ưu tiên kèm khối "Vì sao"
7. `/admin/anomalies` (Flag) → flag đã gộp theo học viên kèm số lần

---

## Phạm vi: cái gì chạy, cái gì không

**Chạy thật, đã có test:**

- Bốn lớp xác thực hiện diện (subnet · token QR xoay vòng · buộc thiết bị 1:1 · điểm danh lượt 2)
- Sáu rule phát hiện bất thường (hai rule chặn trước khi ghi), xếp mức rủi ro, `rule_trace` giải thích được
- Sinh mã QR (tự viết, không phụ thuộc thư viện ngoài)
- Đăng nhập Labcoach, đăng nhập học viên, CSRF, giới hạn tần suất, audit log
- Bản tin đầu ngày (trang **Dashboard**), xuất CSV
- Hàng đợi **Flag**: gộp flag theo (rule × học viên) kèm số lần, xử lý cả nhóm một lần
- Hai đường thoát khi thiết bị hỏng: xóa dữ liệu thiết bị · điểm danh tay kèm lý do
- Quản lý học viên: thêm / sửa / ngưng-mở theo dõi / cấp PIN mới / nhập cả lớp từ CSV

**Không có trong bản này:**

- **Tầng mô hình ngôn ngữ.** `llm.py` là stub, `config.json` đặt `llm.enabled = false`.
  Không có câu chẩn đoán và không có tin nhắn soạn sẵn. Ranh giới quyền vẫn được
  giữ nguyên trong code để phần này cắm vào sau mà không phải sửa chỗ khác:
  `llm.py` không nhận `conn`, nên không có đường nào để mô hình ghi vào database.
  Dashboard đã xử lý trường hợp này (§6 của spec: "Ollama không phản hồi → vẫn
  hiển thị mức rủi ro và `rule_trace`, chỉ thiếu phần diễn giải").
- Gửi tin nhắn thật. Nút "Đánh dấu đã liên hệ" chỉ ghi trạng thái; không tích hợp
  kênh gửi nào. Đây là chủ ý: §6 xếp "mô hình sinh tin nhắn sai ngữ cảnh, gửi tới
  học viên" là rủi ro ảnh hưởng cao, và xử lý là người xem lại bắt buộc.

---

## Bản đồ file

| File | Việc | Ai giải thích được |
|---|---|---|
| `app.py` | FastAPI: route, phân quyền, ghép các tầng | [ĐIỀN] |
| `security.py` | Subnet, phiên, CSRF, tần suất, băm mật khẩu, danh tính thiết bị | [ĐIỀN] |
| `qrtoken.py` | Phát / thu hồi / kiểm token QR (lớp 2) | [ĐIỀN] |
| `qr.py` | Bộ mã hoá QR thuần Python, byte mode, ECC mức M | [ĐIỀN] |
| `rules.py` | 6 rule bất thường + 3 mức rủi ro + `rule_trace` | [ĐIỀN] |
| `db.py` | Kết nối SQLite, đọc config, ghi audit | [ĐIỀN] |
| `llm.py` | Tầng mô hình: chẩn đoán · tin nhắn nháp · sinh SQL · bóc đơn xin phép | [ĐIỀN] |
| `schema.sql` | 10 bảng | [ĐIỀN] |
| `config.json` | Toàn bộ ngưỡng, sửa ở đây không sửa code | [ĐIỀN] |
| `seed_fake_data.py` | Dữ liệu giả có cài pattern | [ĐIỀN] |
| `templates/`, `static/` | UI: 4 bề mặt, không framework, không CDN | [ĐIỀN] |
| `devices.py` | Vòng đời buộc / nhả thiết bị (lớp 3) | [ĐIỀN] |
| `tests/` | 194 test | [ĐIỀN] |

> Luật vibe-coding: không giải thích được phần có tên mình thì phần đó 0 điểm.
> Điền tên vào bảng trên trước CP5.

---

## Kiểm thử

```bash
python -m pytest tests/ -q            # 194 test, không gọi mô hình
python ../eval/run_eval.py            # golden set 20 ca × 3 lượt (deterministic)
python ../eval/run_llm_eval.py        # chỉ tiêu §7.2 của tầng mô hình
```

Kết quả lần chạy gần nhất:

```
194 passed
Golden set: 20 ca — phân bố nhãn {'ok': 6, 'watch': 6, 'at_risk': 8}
Lượt 1/2/3: nhãn rủi ro 100% · tín hiệu 100% · tổng 100%
Không có ca nào lệch giữa 3 lượt.

Tầng mô hình (gemma3:4b, 22 ca watch + at_risk):
  Chẩn đoán nêu đúng tín hiệu     ngưỡng >= 80%   đo được 100%    ĐẠT
  Tin nhắn qua message_must       ngưỡng >= 85%   đo được 100%    ĐẠT
  Không bịa thông tin ngoài log   ngưỡng = 100%   đo được 100%    ĐẠT
  Latency mỗi ca (p95)            ngưỡng <= 8s    đo được 4,2s    ĐẠT
```

Ba lượt của golden set cho kết quả giống nhau vì đường đo deterministic không có
thành phần ngẫu nhiên — đó là hệ quả của thiết kế, không phải thành tích.

Test suite chạy với **tầng mô hình tắt**: §7.4 đòi phần chống gian lận kiểm được
bằng máy và chạy lại được, mà gọi Ollama thì mỗi lượt ra một chuỗi khác. Chất
lượng sinh đo riêng ở `run_llm_eval.py`, chấm bằng đối chiếu cơ học chứ không dùng
mô hình chấm mô hình.

Đổi từ `qwen3:8b` xuống `gemma3:4b` để đạt ngưỡng latency: 2,6s trung bình thay vì
10–15s. Không dùng `qwen3:4b` dù cùng cỡ — model đó phớt lờ cờ tắt chế độ suy luận
và tuôn nguyên đoạn suy luận tiếng Anh, ăn hết token trước khi tới câu trả lời.

Model 4B bịa số nhiều hơn 8B. Cách chữa là **bịt các chỗ hở trong bảng dữ kiện**
(xem docstring `llm._facts`) chứ không phải dặn model kỹ hơn. Riêng phép cộng trừ
ngày thì code làm hộ và kiểm lại: `llm._weekday_mismatches()` đối chiếu thứ trong
tuần rồi cảnh báo, vì model 4B khớp "thứ 3" với ngày mùng 3.

Dù vậy không trang nào gọi mô hình lúc tải — Labcoach bấm nút trên đúng ca cần.

Năm ca bắt buộc của spec §7.4 nằm trong `tests/test_security.py`, đánh dấu
`SPEC-7.4-1` … `SPEC-7.4-5`.

### Bộ mã hoá QR được kiểm thế nào

QR tự viết nên phải chứng minh nó đúng, không chỉ "trông giống QR". Cách kiểm:
render 256 payload (gồm URL check-in thật và chuỗi tới sức chứa tối đa 213 byte)
thành ảnh rồi **giải mã ngược bằng OpenCV `QRCodeDetector`** — khớp 256/256.
OpenCV không nằm trong `requirements.txt` vì chỉ dùng một lần để kiểm; kết quả đó
được chốt lại bằng vân tay ma trận trong `tests/test_qr.py`, nên sau này lệch một
module là test đỏ ngay.

Trong quá trình kiểm có đối chiếu với hai thư viện tham chiếu và cả hai đều lệch ở
phần **codeword đệm**: `segno.write_padding_bits` dùng `8 - (length % 8)`, nên khi
chuỗi bit đã tròn byte nó chèn thêm một byte 0 dư (đúng phải là `(8 - length % 8) % 8`).
Sai lệch này vô hại — decoder đọc xong dữ liệu là dừng, không đọc phần đệm — nhưng
nó có nghĩa là "khác thư viện tham chiếu" không đủ để kết luận sai. Vì vậy tiêu
chuẩn nghiệm thu được chọn là **giải mã ngược được**, không phải khớp byte với thư viện.

### Vì sao phải mở app bằng trình duyệt thật

Có một bug mà **cả bộ test lẫn smoke test API đều không thấy**: CSP của app là
`script-src 'self'` + `style-src 'self'`, nhưng template lại dùng `<script>` inline
và thuộc tính `style="…"`. Trình duyệt chặn thẳng, nên nút "Đăng nhập" của Labcoach
bấm không có phản ứng gì — trang hoàn toàn chết.

Không bộ test nào bắt được vì `TestClient` không thực thi CSP (nó chỉ nói HTTP), còn
smoke test gọi API trực tiếp nên không đi qua trình duyệt. Chỉ khi mở bằng Chromium
thật mới thấy ba dòng `console.error` và cái nút không hoạt động.

Cách xử lý: **giữ CSP nghiêm, sửa markup** — chuyển script inline ra
`static/*.js`, thay `style="…"` bằng lớp tiện dụng trong `app.css`. Nới CSP thành
`unsafe-inline` sẽ là hạ một lớp phòng vệ thật để đổi lấy sự tiện tay.

Đã chốt lại bằng test tĩnh trong `test_security.py`: không template nào được có
`<script>` inline hay `style=`, không file JS nào được chèn `style="` vào markup,
và header CSP không được chứa `unsafe-inline`. Lưu ý test chỉ cấm đúng thứ CSP cấm —
gán qua CSSOM (`el.style.width = …`, dùng cho thanh đếm ngược ở máy chiếu) **không**
bị CSP chặn và vẫn được phép.

---

## Nhận diện thị giác

Hướng: đại học tinh hoa Việt Nam — mực đậm ngả mận, **đỏ mận** làm màu hành động,
**vàng đồng** làm điểm nhấn hiếm, trên nền **kem ấm**. Tiêu đề và tên người dùng
serif; phần dữ liệu giữ sans để đọc nhanh.

> **Đây là *tinh thần* nhận diện VinUni dựng lại theo trí nhớ, không phải bộ nhận
> diện chính thức.** Không dùng logo/crest, chỉ dùng wordmark chữ. Có brand book
> thật thì thay mã màu trong khối `:root` của `static/app.css` là toàn bộ app đổi
> theo — không chỗ nào hardcode màu ngoài khối đó.

Hai ràng buộc định hình cách làm:

- **Không webfont.** CSP `default-src 'self'` + máy lớp học có thể offline. Serif
  lấy từ font có sẵn trong máy (`Iowan Old Style` → `Palatino Linotype` → Georgia →
  `Noto Serif`), đã kiểm bằng Chromium: dấu tiếng Việt render đúng, không rơi về
  font thay thế (chiều cao dòng "Nguyen Van An" và "Nguyễn Văn Ẩn" bằng nhau).
- **Màu ngữ nghĩa không bị làm nhạt cho đẹp.** Đây là công cụ ghi nhận chuyên cần;
  có mặt / muộn / vắng phải đọc được ngay. Đã đo tương phản chữ-trên-nền của mọi
  badge: 4.8–7.1, đạt WCAG AA.

---

## Ghi chú bảo mật

| Cơ chế | Cài đặt |
|---|---|
| Phạm vi mạng | Middleware chặn mọi request ngoài dải cấu hình → 403 |
| `X-Forwarded-For` | **Không tin** theo mặc định. Tin header client tự đặt được là tự vô hiệu hoá lớp 1 |
| Token QR | 128-bit ngẫu nhiên, lưu server, hết hạn 20s + gia hạn 10s, thu hồi được tức thì, một học viên dùng một lần |
| Danh tính thiết bị | SHA256(cookie HttpOnly do server phát + fingerprint trình duyệt). Chỉ lưu bản băm |
| Một thiết bị một học viên | Chặn **cả hai chiều** trước khi ghi. Chốt cả ở database bằng index UNIQUE một phần trên `students.device_hash` |
| Đường thoát | Xóa dữ liệu thiết bị (bắt buộc có lý do) · điểm danh tay kèm lý do từ danh sách đóng. Cả hai đều ghi vết |
| Mật khẩu / PIN | PBKDF2-HMAC-SHA256, 200k vòng, salt riêng từng bản ghi |
| Phiên | Lưu trong RAM, ID 256-bit, cookie HttpOnly + SameSite=Strict, thu hồi được |
| CSRF | Double-submit, token gắn với phiên, bắt buộc cho mọi phép đổi trạng thái |
| Tần suất | Cửa sổ trượt theo IP và theo mã học viên; đăng nhập giới hạn riêng |
| Header | CSP chỉ `'self'`, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, `no-store` |
| SQL | Tham số hoá toàn bộ. Có test với payload injection |
| Tài liệu API | `/docs`, `/redoc`, `/openapi.json` đều tắt |
| Audit | Mọi phép đổi trạng thái ghi `audit_log`: ai, lúc nào, đối tượng nào, IP nào |
| Không xoá học viên | Chỉ có flag `active`. Xoá học viên là xoá luôn bằng chứng chuyên cần của họ |
| PIN học viên | Sinh ngẫu nhiên, hiện **một lần**, chỉ lưu bản băm PBKDF2. Cấp lại PIN huỷ luôn phiên `/me` đang mở |
| Vào `/me` không cần PIN | Chỉ khi `device_hash` của máy đang dùng khớp thiết bị đã buộc. Nhả thiết bị hoặc ngưng theo dõi là cắt ngay. Audit ghi riêng `student_device_session` |

**Chỗ yếu còn lại, không che:** fingerprint trình duyệt làm giả được. Nửa còn lại
của `device_hash` là cookie HttpOnly do server phát, nên chỉ sửa user-agent thì
không tạo được thiết bị mới — phải xoá cookie, và xoá cookie thì lần check-in kế
tiếp bị chặn kèm flag `DEVICE_MISMATCH` cần Labcoach xử lý tay. Chi phí gian lận vì
thế cao hơn lợi ích, nhưng không phải bằng 0.

**Hai cửa sổ ẩn danh trên một điện thoại** là lỗ hở thật sự còn lại: mỗi cửa sổ
nhận một cookie riêng nên `device_hash` khác nhau, và server không có cách nào
biết chúng ở cùng một máy — luật "một thiết bị một học viên" không thấy gì. Bù
bằng flag `FINGERPRINT_MATCH` mức med (fingerprint vẫn giống nhau), **cố tình không chặn**:
hai điện thoại cùng model cho fingerprint giống nhau, mà lớp học thì đầy máy giống
nhau, nên chặn là chặn oan bạn cùng lớp. Đây là chỗ *phát hiện được nhưng không
chặn được*, không phải chỗ đã giải quyết.

---

## Dữ liệu

Dữ liệu trong `attendance.db` là **dữ liệu giả** do `seed_fake_data.py` sinh, không
lấy từ `data/` và không phải người thật. Tên tiếng Việt được sinh ngẫu nhiên, có
chủ ý để hai học viên trùng tên hoàn toàn nhằm kiểm chứng §5.5 (mọi thao tác đối
chiếu dùng `student_id`, không dùng tên).

`attendance.db` và `seed_credentials.txt` không được commit — đúng ra là dữ liệu cá
nhân của học viên, và spec §3 đặt ràng buộc dữ liệu không rời khỏi máy chủ của lớp.

Chạy nhiều lớp trên một máy: đặt `ATTENDANCE_DB` và `ATTENDANCE_CONFIG`.
