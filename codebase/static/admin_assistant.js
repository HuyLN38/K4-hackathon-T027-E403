/* Trang trợ lý: hai tính năng dùng mô hình ngôn ngữ (§4.2).
 *
 * Cả hai đều mất hàng chục giây vì mô hình chạy local trên CPU/GPU của máy này.
 * Nút phải khoá lại và nói rõ đang chờ - không có phản hồi thì người dùng bấm
 * lại lần nữa, và lần nữa, mỗi lần thêm một lượt sinh vào hàng đợi.
 */

const CATEGORY_HINT = {
  'ốm': 'sức khoẻ',
  'việc gia đình': 'gia đình',
  'lịch trùng': 'trùng lịch khác',
  'đi lại': 'đi lại',
  'khác': 'chưa phân loại được',
};

async function checkStatus() {
  try {
    const s = await api('/api/admin/llm-status');
    const node = $('#llm-status');
    if (!s.enabled) {
      node.innerHTML = '<span class="badge">mô hình tắt</span>';
    } else if (!s.reachable) {
      node.innerHTML = '<span class="badge high">Ollama không chạy</span>';
    } else if (!s.model_ready) {
      node.innerHTML = `<span class="badge med">chưa tải ${esc(s.model)}</span>`;
    } else {
      node.innerHTML = `<span class="badge ok">sẵn sàng</span>
        <span class="mono hint">${esc(s.model)}</span>`;
    }
  } catch { $('#llm-status').textContent = ''; }
}

/** Khoá nút + đếm giây, vì một lượt sinh mất 10-30s. */
function busy(btn, hint, label) {
  btn.disabled = true;
  const started = Date.now();
  hint.textContent = `${label}…`;
  const timer = setInterval(() => {
    hint.textContent = `${label}… ${Math.round((Date.now() - started) / 1000)}s`;
  }, 1000);
  return () => { clearInterval(timer); btn.disabled = false; hint.textContent = ''; };
}

// ---------------- hỏi dữ liệu ----------------
async function runQuestion() {
  const question = $('#q-text').value.trim();
  if (!question) { $('#q-text').focus(); return; }
  setAlert($('#q-msg'), '');
  $('#q-out').innerHTML = '';
  const done = busy($('#q-run'), $('#q-hint'), 'Đang sinh câu truy vấn và chạy');

  try {
    const r = await api('/api/admin/ask', { method: 'POST', body: { question } });
    const head = r.columns.map((c) => `<th>${esc(c)}</th>`).join('');
    const body = r.rows.length
      ? r.rows.map((row) => `<tr>${r.columns.map((c) => `<td>${esc(row[c] ?? '—')}</td>`).join('')}</tr>`).join('')
      : `<tr><td colspan="${r.columns.length}" class="empty">Không có dòng nào khớp.</td></tr>`;

    $('#q-out').innerHTML = `
      <div class="note mt-md">
        <strong>Câu SQL đã chạy</strong> (chỉ-đọc):
        <pre class="sql-out">${esc(r.sql)}</pre>
      </div>
      <div class="table-wrap mt-md">
        <table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
      </div>
      <p class="hint mt-sm">${r.rows.length} dòng. Con số ở đây đọc thẳng từ database —
        nhưng câu hỏi được dịch sang SQL bởi mô hình, nên hãy đọc lại câu SQL ở trên
        trước khi dùng số này để kết luận.</p>`;
  } catch (err) {
    if (err.status === 401) { location.href = '/admin/login'; return; }
    setAlert($('#q-msg'), err.message);
  } finally { done(); }
}

// ---------------- bóc đơn xin phép ----------------
async function runLeave() {
  const text = $('#l-text').value.trim();
  if (text.length < 5) { $('#l-text').focus(); return; }
  setAlert($('#l-msg'), '');
  $('#l-out').innerHTML = '';
  const done = busy($('#l-run'), $('#l-hint'), 'Đang bóc');

  try {
    const r = await api('/api/admin/parse-leave', { method: 'POST', body: { text } });
    const p = r.parsed;
    const sid = p.student_id
      ? (p.student_known
        ? `<span class="mono">${esc(p.student_id)}</span> <span class="badge ok">có trong lớp</span>`
        : `<span class="mono">${esc(p.student_id)}</span> <span class="badge high">không có mã này trong lớp</span>`)
      : '<span class="badge med">đơn không ghi mã</span>';

    const rows = [
      ['Mã học viên', sid],
      ['Tên trong đơn', esc(p.student_name || '—')],
      ['Ngày xin nghỉ', p.dates.length
        ? p.dates.map((d) => `<span class="badge">${esc(d)}</span>`).join(' ')
        : '<span class="badge high">không xác định được ngày</span>'],
      ['Nhóm lý do', `${esc(p.category)} <span class="hint">${esc(CATEGORY_HINT[p.category] || '')}</span>`],
      ['Lý do (nguyên văn)', esc(p.reason_text || '—')],
      ['Có nhắc giấy tờ kèm', p.has_evidence ? 'có' : 'không'],
    ];

    const missing = (p.missing || []).length
      ? `<div class="alert warn mt-md">Đơn thiếu: <strong>${esc((p.missing || []).join(', '))}</strong>.
           Hỏi lại học viên trước khi ghi.</div>`
      : '';

    // Cảnh báo lệch thứ do code tự đối chiếu, không phải do mô hình tự khai. Model
    // 4B hay khớp "thứ 3" với ngày mùng 3 — sai một ngày, rất khó thấy bằng mắt.
    const dateWarn = (p.date_warnings || []).length
      ? `<div class="alert error mt-md">${(p.date_warnings || [])
          .map((w) => esc(w)).join('<br>')}</div>`
      : '';

    $('#l-out').innerHTML = `
      <div class="table-wrap mt-md">
        <table><tbody>${rows.map(([k, v]) =>
          `<tr><td class="nowrap"><strong>${esc(k)}</strong></td><td class="wrap">${v}</td></tr>`).join('')}
        </tbody></table>
      </div>
      ${dateWarn}
      ${missing}
      <div class="note mt-md">${esc(r.note)}
        Ghi nhận thật ở <a href="/admin/sessions">màn hình buổi học</a>, mục điểm danh tay —
        thao tác đó có tên bạn trong audit log, còn thao tác này thì không ghi gì cả.</div>`;
  } catch (err) {
    if (err.status === 401) { location.href = '/admin/login'; return; }
    setAlert($('#l-msg'), err.message);
  } finally { done(); }
}

$('#q-run').addEventListener('click', runQuestion);
$('#q-text').addEventListener('keydown', (e) => { if (e.key === 'Enter') runQuestion(); });
$('#l-run').addEventListener('click', runLeave);
checkStatus();
