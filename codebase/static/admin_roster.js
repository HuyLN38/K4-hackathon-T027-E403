/* Danh sách lớp: khoá/mở thiết bị và mở hồ sơ rủi ro từng học viên. */

let students = [];
let closedSessions = 0;

function render() {
  const q = $('#q').value.trim().toLowerCase();
  const shown = students.filter(
    (s) => !q || s.student_id.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)
  );

  $('#rows').innerHTML = shown.length ? shown.map((s) => `<tr>
    <td class="mono">${esc(s.student_id)}</td>
    <td class="wrap w-md" title="${esc(s.name)}">${esc(s.name)}${s.active
      ? '' : ' <span class="badge">đã ngưng</span>'}</td>
    <td>${s.device_locked
      ? `<span class="badge ok">binded</span> <span class="mono hint">${esc(s.device_short)}</span>`
      : '<span class="badge">unbind</span>'}</td>
    <td>${s.device_locked_at ? fmtDateTime(s.device_locked_at) : '—'}</td>
    <td class="num">${s.attended}/${closedSessions}</td>
    <td class="num">${s.manual_records ? `<span class="badge manual">${s.manual_records}</span>` : '0'}</td>
    <td class="num">${s.open_flags ? `<span class="badge med">${s.open_flags}</span>` : '0'}</td>
    <td>${s.risk_level ? riskBadge(s.risk_level) : '<span class="hint">—</span>'}</td>
    <td><div class="btn-row">
      <button data-act="detail" data-sid="${esc(s.student_id)}">Hồ sơ</button>
      <button data-act="edit" data-sid="${esc(s.student_id)}">Sửa</button>
      <button data-act="release" data-sid="${esc(s.student_id)}" ${s.device_locked ? ''
        : 'disabled title="Học viên đang unbind, không có thiết bị nào để xóa"'}>Unbind</button>
    </div></td>
  </tr>`).join('') : '<tr><td colspan="9" class="empty">Không có học viên khớp.</td></tr>';

  $$('#rows button').forEach((btn) => btn.addEventListener('click', () => {
    if (btn.dataset.act === 'release') releaseDevice(btn);
    else if (btn.dataset.act === 'edit') openStudentModal(btn.dataset.sid);
    else showDetail(btn.dataset.sid);
  }));
}

async function load() {
  try {
    const data = await api('/api/admin/roster');
    students = data.students;
    closedSessions = data.closed_sessions;
    render();
  } catch (err) {
    if (err.status === 401) { location.href = '/admin/login'; return; }
    $('#rows').innerHTML = `<tr><td colspan="8" class="alert error">${esc(err.message)}</td></tr>`;
  }
}

/** Xóa dữ liệu thiết bị của một mã học viên: mất máy, đổi máy, hoặc buộc sai người. */
async function releaseDevice(btn) {
  const sid = btn.dataset.sid;
  const note = prompt(
    `Unbind thiết bị của ${sid}?\n\n`
    + 'Sau thao tác này học viên bind được máy mới ở lần check-in tới, và máy vừa nhả '
    + 'cũng bind được cho người khác.\n\nLý do (bắt buộc, sẽ vào audit log):',
    'học viên đổi điện thoại'
  );
  if (note === null) return;
  if (!note.trim()) { alert('Cần ghi lý do — thao tác này nới một lớp phòng vệ.'); return; }

  btn.disabled = true;
  try {
    const res = await api(`/api/admin/students/${encodeURIComponent(sid)}/release-device`,
      { method: 'POST', body: { note: note.trim() } });
    await load();
    const closed = res.flags_closed ? ` Đã đóng ${res.flags_closed} flag liên quan.` : '';
    alert(`Đã unbind thiết bị ${res.released_device || '(chưa có)'} của ${sid}.${closed}`);
  } catch (err) { alert(err.message); btn.disabled = false; }
}

async function showDetail(studentId) {
  const card = $('#detail');
  card.classList.remove('hidden');
  $('#detail-title').textContent = `Hồ sơ ${studentId}`;
  $('#detail-body').innerHTML = '<div class="empty">Đang tải…</div>';
  card.scrollIntoView({ behavior: 'smooth', block: 'start' });

  try {
    const [d, dev] = await Promise.all([
      api(`/api/admin/risk/${encodeURIComponent(studentId)}`),
      api(`/api/admin/students/${encodeURIComponent(studentId)}/devices`),
    ]);
    $('#detail-title').innerHTML = `${esc(d.student.name)}
      <span class="mono hint">${esc(d.student.student_id)}</span> ${riskBadge(d.risk_level)}`;

    const deviceBlock = `
      <h3 class="mt-md">Thiết bị</h3>
      <p class="hint">Đang bind: ${dev.current_device
        ? `<span class="mono">${esc(dev.current_device)}</span> từ ${fmtDateTime(dev.locked_at)}`
        : 'unbind — chưa bind thiết bị nào'}</p>
      ${dev.history.length ? `<div class="table-wrap">
        <table><thead><tr><th>Thiết bị</th><th>Bind lúc</th><th>Unbind lúc</th><th>Ai unbind</th><th class="wrap">Lý do</th></tr></thead>
        <tbody>${dev.history.map((h) => `<tr>
          <td class="mono">${esc(h.device_short)}</td>
          <td>${fmtDateTime(h.bound_at)}</td>
          <td>${h.active ? '<span class="badge ok">đang dùng</span>' : fmtDateTime(h.released_at)}</td>
          <td class="mono">${esc(h.released_by || '—')}</td>
          <td class="wrap" title="${esc(h.release_note || '')}">${esc(h.release_note || '—')}</td>
        </tr>`).join('')}</tbody></table></div>`
        : '<p class="hint">Chưa có lịch sử bind thiết bị.</p>'}`;

    const flags = d.flags.length ? `<div class="table-wrap mt-md">
      <table><thead><tr><th>Rule</th><th>Mức</th><th class="wrap">Chi tiết</th><th>Lúc</th><th>Trạng thái</th></tr></thead>
      <tbody>${d.flags.map((f) => `<tr>
        <td class="mono">${esc(f.rule_code)}</td>
        <td><span class="badge ${esc(f.severity)}">${esc(f.severity)}</span></td>
        <td class="wrap">${esc(f.detail || '')}</td>
        <td>${fmtDateTime(f.created_at)}</td>
        <td>${f.resolved ? '<span class="badge ok">Đã xử lý</span>' : '<span class="badge med">Chưa xử lý</span>'}</td>
      </tr>`).join('')}</tbody></table></div>`
      : '<p class="hint mt-md">Không có flag bất thường nào.</p>';

    // Khối mô hình đặt SAU rule_trace, không phải trước: thứ chịu được khiếu nại
    // là rule_trace, còn câu chữ của mô hình chỉ là bản diễn giải nó.
    const llmBlock = d.llm_enabled
      ? `<div class="card mt-md" id="llm-card">
           <div class="card-head">
             <h3>Diễn giải và tin nhắn nháp</h3>
             <span class="spacer"></span>
             <button id="explain" data-sid="${esc(studentId)}">Sinh bằng mô hình</button>
           </div>
           <p class="hint">Mô hình local đọc đúng phần <em>Vì sao</em> ở trên rồi viết lại
             thành câu. Mất 20–30 giây. Tin nhắn là <strong>bản nháp</strong> — đọc lại
             rồi tự gửi, hệ thống không gửi giúp.</p>
           <div id="llm-out"></div>
         </div>`
      : `<div class="note mt-md">
           Tầng mô hình đang tắt: không có phần diễn giải và tin nhắn soạn sẵn.
           Mức rủi ro ở trên là deterministic, truy vết được về từng rule.</div>`;

    $('#detail-body').innerHTML = renderTrace(d.rule_trace) + flags + deviceBlock + llmBlock;

    const explain = $('#explain');
    if (explain) explain.addEventListener('click', () => runExplain(explain));
  } catch (err) {
    $('#detail-body').innerHTML = `<div class="alert error">${esc(err.message)}</div>`;
  }
}

/** Gọi mô hình sinh diễn giải + tin nhắn nháp cho một ca.
 *
 * Là một thao tác riêng chứ không nằm trong lượt tải hồ sơ: mô hình chạy local
 * mất 20-30s, mà phần lớn lần mở hồ sơ chỉ để xem lịch sử điểm danh.
 */
async function runExplain(btn) {
  const out = $('#llm-out');
  btn.disabled = true;
  const started = Date.now();
  const timer = setInterval(() => {
    btn.textContent = `Đang sinh… ${Math.round((Date.now() - started) / 1000)}s`;
  }, 1000);
  out.innerHTML = '<div class="empty">Mô hình đang đọc rule_trace…</div>';

  try {
    const r = await api(`/api/admin/risk/${encodeURIComponent(btn.dataset.sid)}/explain`,
      { method: 'POST' });
    // Ollama im lặng -> trả 200 kèm null. Nói ra chứ không hiện ô trống.
    const block = (title, body) => body
      ? `<h4 class="mt-md">${esc(title)}</h4><div class="llm-text">${esc(body)}</div>`
      : `<h4 class="mt-md">${esc(title)}</h4><p class="hint">Mô hình không trả lời lượt này.</p>`;
    out.innerHTML = block('Chẩn đoán', r.diagnosis)
      + block('Tin nhắn nháp', r.message)
      + (r.message ? '<div class="btn-row mt-sm"><button id="copy-msg">Chép tin nhắn</button></div>' : '');
    const copy = $('#copy-msg');
    if (copy) copy.addEventListener('click', async () => {
      await navigator.clipboard.writeText(r.message);
      copy.textContent = 'Đã chép';
    });
  } catch (err) {
    out.innerHTML = `<div class="alert error">${esc(err.message)}</div>`;
  } finally {
    clearInterval(timer);
    btn.disabled = false;
    btn.textContent = 'Sinh lại';
  }
}

// ---------------- thêm / sửa học viên ----------------
/* Không có nút xoá, và đó là chủ ý: attendance / anomaly_flags / risk_snapshots
   đều trỏ về student_id. Xoá học viên là xoá luôn bằng chứng chuyên cần của họ -
   đúng thứ hệ thống này sinh ra để bảo vệ. Thay bằng flag active. */

const studentModal = $('#student-modal');
let editingSid = null;

/** PIN chỉ hiện một lần - server giữ bản băm, không đọc lại được. */
function showPin(sid, pin) {
  alert(`PIN của ${sid}: ${pin}\n\n`
    + 'Ghi lại và đưa cho học viên ngay. Hệ thống chỉ lưu bản băm nên không xem lại được; '
    + 'quên thì phải cấp PIN mới.');
}

/** Ô "tự đặt PIN" chỉ bật khi đã chọn - tránh gõ vào ô mà hệ thống sẽ bỏ qua. */
function syncPinMode() {
  const manual = $('input[name=pinmode]:checked')?.value === 'manual';
  $('#f-pin').disabled = !manual;
  if (!manual) $('#f-pin').value = '';
}
$$('input[name=pinmode]').forEach((r) => r.addEventListener('change', syncPinMode));

function nameField() {
  return editingSid ? $('#f-name') : $('#f-name-new');
}

function openStudentModal(sid) {
  editingSid = sid || null;
  const student = sid ? students.find((s) => s.student_id === sid) : null;
  const editing = Boolean(sid);

  $('#student-modal-title').textContent = editing ? `Sửa ${sid}` : 'Thêm học viên';
  $('#student-save').textContent = editing ? 'Lưu thay đổi' : 'Thêm học viên';

  // Chế độ sửa: mã thành nhãn tĩnh; chế độ thêm: hai ô mã + tên nằm cạnh nhau.
  $('#f-sid-fixed').classList.toggle('hidden', !editing);
  $('#f-new-row').classList.toggle('hidden', editing);
  $('#f-name-row').classList.toggle('hidden', !editing);
  $('#f-pin-row').classList.toggle('hidden', editing);
  $('#f-active-row').classList.toggle('hidden', !editing);

  $('#f-sid-label').textContent = editing ? sid : '';
  $('#f-sid').value = '';
  $('#f-name').value = student ? student.name : '';
  $('#f-name-new').value = '';
  $('#f-email').value = student && student.email ? student.email : '';
  $('input[name=pinmode][value=auto]').checked = true;
  syncPinMode();

  if (student) {
    $('#f-toggle-active').textContent = student.active ? 'Ngưng theo dõi' : 'Mở lại theo dõi';
  }
  setAlert($('#student-msg'), '');
  studentModal.showModal();
  (editing ? $('#f-name') : $('#f-sid')).focus();
}

$('#add-open').addEventListener('click', () => openStudentModal(null));
$('#student-close').addEventListener('click', () => studentModal.close());

$('#student-save').addEventListener('click', async () => {
  const btn = $('#student-save');
  btn.disabled = true;
  setAlert($('#student-msg'), '');
  try {
    const body = { name: nameField().value.trim(), email: $('#f-email').value.trim() };
    if (editingSid) {
      await api(`/api/admin/students/${encodeURIComponent(editingSid)}/update`,
        { method: 'POST', body });
    } else {
      const res = await api('/api/admin/students', {
        method: 'POST',
        body: { ...body, student_id: $('#f-sid').value.trim(), pin: $('#f-pin').value.trim() },
      });
      showPin(res.student_id, res.pin);
    }
    studentModal.close();
    await load();
  } catch (err) { setAlert($('#student-msg'), err.message); }
  btn.disabled = false;
});

$('#student-cancel').addEventListener('click', () => studentModal.close());

$('#f-toggle-active').addEventListener('click', async () => {
  const student = students.find((s) => s.student_id === editingSid);
  const next = !student.active;
  if (!confirm(next
    ? `Mở lại theo dõi cho ${editingSid}?`
    : `Ngưng theo dõi ${editingSid}?\n\nHọc viên sẽ không điểm danh được nữa, nhưng toàn bộ `
      + 'lịch sử chuyên cần vẫn giữ nguyên và vẫn tra cứu được.')) return;
  try {
    await api(`/api/admin/students/${encodeURIComponent(editingSid)}/set-active`,
      { method: 'POST', body: { active: next } });
    studentModal.close();
    await load();
  } catch (err) { setAlert($('#student-msg'), err.message); }
});

$('#f-reset-pin').addEventListener('click', async () => {
  if (!confirm(`Cấp PIN mới cho ${editingSid}? PIN cũ mất hiệu lực ngay.`)) return;
  try {
    const res = await api(`/api/admin/students/${encodeURIComponent(editingSid)}/reset-pin`,
      { method: 'POST' });
    showPin(res.student_id, res.pin);
  } catch (err) { setAlert($('#student-msg'), err.message); }
});

// ---------------- nhập CSV ----------------
const importModal = $('#import-modal');
$('#import-open').addEventListener('click', () => {
  $('#import-result').innerHTML = '';
  setAlert($('#import-msg'), '');
  importModal.showModal();
  $('#csv-text').focus();
});
$('#import-close').addEventListener('click', () => importModal.close());

$('#import-run').addEventListener('click', async () => {
  const btn = $('#import-run');
  btn.disabled = true;
  setAlert($('#import-msg'), '');
  $('#import-result').innerHTML = '';
  try {
    const res = await api('/api/admin/students/import',
      { method: 'POST', body: { csv_text: $('#csv-text').value } });

    if (!res.ok) {
      setAlert($('#import-msg'), res.message);
      $('#import-result').innerHTML = `<div class="table-wrap mb-sm">
        <table><thead><tr><th>Dòng</th><th class="wrap">Nội dung</th><th class="wrap">Lỗi</th></tr></thead>
        <tbody>${res.errors.map((e) => `<tr>
          <td class="num">${e.line}</td>
          <td class="wrap" title="${esc(e.text)}">${esc(e.text)}</td>
          <td class="wrap" title="${esc(e.error)}">${esc(e.error)}</td>
        </tr>`).join('')}</tbody></table></div>`;
    } else {
      // PIN chỉ hiện một lần -> phải cho Labcoach chép ra được ngay tại đây.
      $('#import-result').innerHTML = `
        <div class="alert success mb-sm">Đã thêm ${res.imported} học viên.</div>
        <div class="note mb-sm"><strong>Chép PIN ra ngay.</strong>
          Hệ thống chỉ lưu bản băm, đóng cửa sổ này là không xem lại được.</div>
        <div class="table-wrap mb-sm">
          <table><thead><tr><th>Mã HV</th><th class="wrap">Tên</th><th>PIN</th></tr></thead>
          <tbody>${res.students.map((s) => `<tr>
            <td class="mono">${esc(s.student_id)}</td>
            <td class="wrap" title="${esc(s.name)}">${esc(s.name)}</td>
            <td class="mono">${esc(s.pin)}</td>
          </tr>`).join('')}</tbody></table></div>`;
      $('#csv-text').value = '';
      await load();
    }
  } catch (err) { setAlert($('#import-msg'), err.message); }
  btn.disabled = false;
});

$('#detail-close').addEventListener('click', () => $('#detail').classList.add('hidden'));
$('#q').addEventListener('input', render);
load();
