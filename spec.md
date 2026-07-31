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
  - *Phần Thật:* Trang check-in xác thực TOTP/Device Binding thật, FastAPI backend thật, Rule Engine deterministic thật, Ollama Qwen2.5 7B sinh chẩn đoán & tin nhắn thật, Dashboard của giảng viên thật.

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
