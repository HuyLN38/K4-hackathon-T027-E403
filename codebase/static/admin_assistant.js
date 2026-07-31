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

/** Khoá nút, đổi nhãn nút thành vòng quay + số giây.
 *
 * Đếm giây nằm trong chính cái nút chứ không ở một dòng chữ bên cạnh: mắt người
 * dùng đang ở nút vừa bấm, và một dòng chữ dài cạnh nút thì đẩy layout lệch.
 */
function busy(btn) {
  btn.disabled = true;
  btn.classList.add('is-busy');
  const label = btn.textContent;
  const started = Date.now();
  const tick = () => {
    const s = Math.round((Date.now() - started) / 1000);
    btn.innerHTML = `<i class="spin"></i><span class="busy-s">${s}s</span>`;
  };
  tick();
  const timer = setInterval(tick, 1000);
  return () => {
    clearInterval(timer);
    btn.classList.remove('is-busy');
    btn.disabled = false;
    btn.textContent = label;
  };
}

// ---------------- hỏi dữ liệu ----------------
async function runQuestion() {
  const question = $('#q-text').value.trim();
  if (!question) { $('#q-text').focus(); return; }
  setAlert($('#q-msg'), '');
  $('#q-out').innerHTML = '';
  const done = busy($('#q-run'));

  try {
    const r = await api('/api/admin/ask', { method: 'POST', body: { question } });
    const head = r.columns.map((c) => `<th>${esc(c)}</th>`).join('');
    const body = r.rows.length
      ? r.rows.map((row) => `<tr>${r.columns.map((c) => `<td>${esc(row[c] ?? '—')}</td>`).join('')}</tr>`).join('')
      : `<tr><td colspan="${r.columns.length}" class="empty">Không có dòng nào khớp.</td></tr>`;

    // Kết quả lên trước, SQL thu gọn phía dưới: thứ Labcoach cần là con số, câu
    // SQL là thứ để kiểm lại khi nghi ngờ. Mở sẵn thì mỗi lần hỏi lại phải cuộn
    // qua một khối code mới tới bảng.
    $('#q-out').innerHTML = `
      <div class="table-wrap mt-md">
        <table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
      </div>
      <p class="hint mt-sm">${r.rows.length} dòng, đọc thẳng từ database.
        Câu hỏi do mô hình dịch sang SQL — nghi ngờ con số nào thì mở câu SQL bên dưới
        để kiểm.</p>
      <details class="sql-details mt-sm">
        <summary>Câu SQL đã chạy <span class="hint">(chỉ-đọc)</span></summary>
        <pre class="sql-out">${esc(r.sql)}</pre>
      </details>`;
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
  const done = busy($('#l-run'));

  try {
    const r = await api('/api/admin/parse-leave', { method: 'POST', body: { text } });
    const p = r.parsed;
    const sid = p.student_id
      ? (p.student_known
        ? `<span class="mono">${esc(p.student_id)}</span> <span class="badge ok">có trong lớp</span>`
        : `<span class="mono">${esc(p.student_id)}</span> <span class="badge high">không có mã này trong lớp</span>`)
      : '<span class="badge high">chưa xác định được</span>';

    // Nhiều người trùng tên: §5.5 nói lớp có học viên trùng tên hoàn toàn, nên
    // liệt kê hết để Labcoach chọn chứ không chọn hộ.
    const nameCell = p.name_matches && p.name_matches.length > 1
      ? `${esc(p.student_name || '—')}<div class="mt-sm">${p.name_matches.map((m) =>
          `<span class="badge med mono">${esc(m.student_id)}</span>`).join(' ')}</div>`
      : esc(p.student_name || '—');

    const rows = [
      ['Mã học viên', sid],
      ['Tên trong đơn', nameCell],
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

    // Kết quả đối chiếu tên → mã, do code làm chứ không phải mô hình tự khẳng định.
    const lookup = p.lookup_note
      ? `<div class="alert ${p.student_known ? 'warn' : 'error'} mt-md">${esc(p.lookup_note)}</div>`
      : '';

    $('#l-out').innerHTML = `
      <div class="table-wrap mt-md">
        <table><tbody>${rows.map(([k, v]) =>
          `<tr><td class="nowrap"><strong>${esc(k)}</strong></td><td class="wrap">${v}</td></tr>`).join('')}
        </tbody></table>
      </div>
      ${lookup}
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

// ---------------- chất lượng tầng mô hình (§7.2) ----------------
/* Đọc kết quả lần chạy `eval/run_llm_eval.py` gần nhất.
 *
 * Đưa khối này vào app vì một chỉ tiêu chỉ nằm trong terminal của người vừa chạy
 * script thì với người dùng sản phẩm nó không tồn tại. Đây là trang mô hình nói
 * chuyện trực tiếp với Labcoach, nên cũng là chỗ phải nói mô hình được đo bằng gì.
 */
async function loadEval() {
  const grid = $('#eval-grid');
  try {
    const e = await api('/api/admin/llm-eval');
    if (!e.available) {
      grid.innerHTML = `<p class="hint">Chưa có số đo. ${esc(e.hint || '')}</p>`;
      return;
    }

    const when = new Date(e.measured_at * 1000).toLocaleString('vi-VN', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    });
    $('#eval-model').textContent = `${e.model} · ${e.cases} ca · đo lúc ${when}`;

    grid.innerHTML = e.criteria.map((c) => {
      const sign = c.compare === 'lte' ? '≤' : '≥';
      return `<div class="eval-item ${c.ok ? 'pass' : 'fail'}">
        <div class="eval-label">${esc(c.label)}</div>
        <div class="eval-value">${esc(c.value)}<span class="eval-unit">${esc(c.unit)}</span></div>
        <div class="eval-bar"><i class="${c.ok ? 'pass' : 'fail'}"></i></div>
        <div class="eval-foot">
          <span class="hint">ngưỡng ${sign} ${esc(c.threshold)}${esc(c.unit)}</span>
          <span class="badge ${c.ok ? 'ok' : 'high'}">${c.ok ? 'đạt' : 'chưa đạt'}</span>
        </div>
      </div>`;
    }).join('');

    renderEvalHistory(e);
    renderEvalCases(e.cases_detail || []);

    // Model trong config đã khác model lúc đo -> số cũ không nói gì về bản đang chạy.
    if (e.stale) {
      grid.insertAdjacentHTML('afterend',
        `<div class="alert warn mt-md">Số đo ở trên chạy trên
           <strong>${esc(e.model)}</strong>, nhưng app đang dùng
           <strong>${esc(e.current_model)}</strong>. Chạy lại
           <code>python eval/run_llm_eval.py</code> để số khớp bản đang chạy.</div>`);
    }
  } catch (err) {
    if (err.status === 401) { location.href = '/admin/login'; return; }
    grid.innerHTML = `<p class="hint">${esc(err.message)}</p>`;
  }
}

const fmtRun = (ts) => new Date(ts * 1000).toLocaleString('vi-VN', {
  day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
});

/** Bảng các lượt đã chạy. Chỉ hiện khi có từ 2 lượt trở lên — một dòng thì
 *  không nói được gì về dao động, chỉ tốn chỗ. */
function renderEvalHistory(e) {
  const rows = e.history || [];
  if (rows.length < 2) return;
  $('#eval-history').classList.remove('hidden');
  $('#eval-history-rows').innerHTML = rows.slice().reverse().map((h) => {
    const cell = (v, ok) => `<td class="num ${ok ? '' : 'miss'}">${esc(v)}</td>`;
    return `<tr>
      <td class="nowrap">${fmtRun(h.measured_at)}</td>
      <td class="mono">${esc(h.model)}</td>
      ${cell(h['Chẩn đoán nêu đúng tín hiệu'] + '%', h['Chẩn đoán nêu đúng tín hiệu'] >= 80)}
      ${cell(h['Tin nhắn qua message_must'] + '%', h['Tin nhắn qua message_must'] >= 85)}
      ${cell(h['Không bịa thông tin ngoài log'] + '%', h['Không bịa thông tin ngoài log'] >= 100)}
      ${cell(h['Latency mỗi ca (p95)'] + 's', h['Latency mỗi ca (p95)'] <= 8)}
      <td>${h.all_ok ? '<span class="badge ok">đạt cả 4</span>'
                     : '<span class="badge med">có mục chưa đạt</span>'}</td>
    </tr>`;
  }).join('');
}

/** Nguyên văn model sinh ra ở từng ca, kèm chỗ hỏng nếu có. */
function renderEvalCases(cases) {
  if (!cases.length) return;
  $('#eval-cases').innerHTML = cases.map((c) => {
    const bad = !(c.diagnosis_names_signal && c.message_ok && c.grounded);
    const problems = [
      ...(c.problems || []),
      ...(c.message_missing || []).map((m) => `tin nhắn thiếu: ${m}`),
    ];
    return `<div class="eval-case ${bad ? 'bad' : ''}">
      <div class="eval-case-head">
        <span class="mono">${esc(c.student_id)}</span>
        <strong>${esc(c.name)}</strong>
        ${riskBadge(c.level)}
        <span class="spacer"></span>
        <span class="hint">${esc(c.sec_diagnosis)}s + ${esc(c.sec_message)}s</span>
        <span class="badge ${bad ? 'high' : 'ok'}">${bad ? 'có vấn đề' : 'đạt'}</span>
      </div>
      ${problems.length
        ? `<ul class="eval-problems">${problems.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>`
        : ''}
      <div class="eval-case-body">
        <div><span class="k">Chẩn đoán</span><div class="llm-text">${esc(c.diagnosis || '—')}</div></div>
        <div><span class="k">Tin nhắn nháp</span><div class="llm-text">${esc(c.message || '—')}</div></div>
      </div>
    </div>`;
  }).join('');

  const toggle = $('#eval-toggle');
  toggle.addEventListener('click', () => {
    const hidden = $('#eval-cases').classList.toggle('hidden');
    toggle.textContent = hidden ? 'Hiện chi tiết' : 'Ẩn chi tiết';
  });
}

// ---------------- ví dụ bấm nhanh ----------------
$$('#q-samples .chip').forEach((c) => c.addEventListener('click', () => {
  $('#q-text').value = c.dataset.q;
  runQuestion();
}));
$$('#l-samples .chip').forEach((c) => c.addEventListener('click', () => {
  $('#l-text').value = c.dataset.l;
  runLeave();
}));

$('#q-run').addEventListener('click', runQuestion);
$('#q-text').addEventListener('keydown', (e) => { if (e.key === 'Enter') runQuestion(); });
$('#l-run').addEventListener('click', runLeave);
checkStatus();
loadEval();
