/* Quản lý buổi học + màn hình điểm danh trực tiếp. */

let liveSessionId = null;
let liveTimer = null;

const STATE_BADGE = {
  scheduled: '<span class="badge">Chưa mở</span>',
  open: '<span class="badge accent">Đang mở</span>',
  closed: '<span class="badge ok">Đã đóng</span>',
};

function actions(s) {
  const out = [];
  if (s.state === 'scheduled') out.push(`<button data-act="open" data-id="${s.session_id}">Mở điểm danh</button>`);
  if (s.state === 'open') {
    if (s.call_index === 1) out.push(`<button data-act="second" data-id="${s.session_id}" class="primary">Gọi lượt 2</button>`);
    out.push(`<button data-act="close" data-id="${s.session_id}">Đóng buổi</button>`);
  }
  out.push(`<button data-act="live" data-id="${s.session_id}">Xem</button>`);
  return `<div class="btn-row">${out.join('')}</div>`;
}

async function loadSessions() {
  try {
    const data = await api('/api/admin/sessions');
    $('#roster-note').textContent = `${data.roster_size} học viên đang hoạt động`;
    $('#rows').innerHTML = data.sessions.map((s) => `<tr>
      <td class="mono">${s.session_id}</td>
      <td>${esc(s.date)}</td>
      <td>${esc(s.start_time)}</td>
      <td>${esc(s.room || '—')}</td>
      <td>${STATE_BADGE[s.state] || esc(s.state)}</td>
      <td class="num">${s.call1_count}</td>
      <td class="num">${s.call2_count}</td>
      <td>${s.second_call_ts ? fmtTime(s.second_call_ts) : '—'}</td>
      <td>${actions(s)}</td>
    </tr>`).join('');

    $$('#rows button').forEach((btn) => btn.addEventListener('click', () => act(btn)));
  } catch (err) {
    if (err.status === 401) { location.href = '/admin/login'; return; }
    $('#rows').innerHTML = `<tr><td colspan="9" class="alert error">${esc(err.message)}</td></tr>`;
  }
}

async function act(btn) {
  const id = btn.dataset.id;
  const which = btn.dataset.act;
  if (which === 'live') { openLive(id); return; }

  const confirmText = {
    second: 'Gọi lượt điểm danh thứ 2? Mã QR của lượt 1 sẽ hết hiệu lực ngay.',
    close: 'Đóng buổi này? Sau khi đóng sẽ chạy rà soát vắng mặt ở lượt 2 và không mở lại được.',
  }[which];
  if (confirmText && !confirm(confirmText)) return;

  btn.disabled = true;
  setAlert($('#msg'), '');
  const path = { open: 'open', second: 'second-call', close: 'close' }[which];
  try {
    const res = await api(`/api/admin/sessions/${id}/${path}`, { method: 'POST' });
    if (which === 'close' && res.early_departure_flags) {
      setAlert($('#msg'), `Đã đóng buổi. Ghi nhận vắng mặt ở lượt 2 cho ${res.early_departure_flags.length} học viên.`, 'success');
    }
    await loadSessions();
    if (liveSessionId) loadLive();
  } catch (err) {
    setAlert($('#msg'), err.message);
    btn.disabled = false;
  }
}

$('#create').addEventListener('click', async () => {
  setAlert($('#msg'), '');
  try {
    await api('/api/admin/sessions', {
      method: 'POST',
      body: {
        date: $('#d').value,
        start_time: $('#t').value,
        room: $('#r').value.trim(),
        late_after_min: Number($('#l').value),
      },
    });
    await loadSessions();
    setAlert($('#msg'), 'Đã tạo buổi học.', 'success');
  } catch (err) { setAlert($('#msg'), err.message); }
});

// ---------------- điểm danh trực tiếp ----------------
/** Nạp danh sách lý do nhập tay. Danh sách đóng để về sau tổng hợp đếm được. */
async function loadManualReasons() {
  try {
    const data = await api('/api/admin/manual-reasons');
    $('#manual-reason').innerHTML = data.reasons
      .map((r) => `<option value="${esc(r.code)}">${esc(r.label)}</option>`).join('');
  } catch (err) {
    if (err.status === 401) location.href = '/admin/login';
  }
}

const liveModal = $('#live-modal');

function openLive(id) {
  liveSessionId = id;
  $('#live-id').textContent = id;
  loadLive();
  clearInterval(liveTimer);
  liveTimer = setInterval(loadLive, 4000);
  liveModal.showModal();  // <dialog> lo backdrop, bẫy focus và phím Esc
}

function closeLive() {
  liveSessionId = null;
  clearInterval(liveTimer);
  if (liveModal.open) liveModal.close();
}

$('#live-close').addEventListener('click', closeLive);
// Esc đóng dialog nhưng không chạy qua nút, nên phải dừng polling ở đây.
liveModal.addEventListener('close', () => { liveSessionId = null; clearInterval(liveTimer); });
$('#live-q').addEventListener('input', renderLive);

let liveRows = [];

function renderLive() {
  const q = $('#live-q').value.trim().toLowerCase();
  const shown = liveRows.filter(
    (r) => !q || r.student_id.toLowerCase().includes(q) || r.name.toLowerCase().includes(q)
  );

  $('#live-rows').innerHTML = shown.length ? shown.map((r) => {
    const flags = (r.flags || '').split(',').filter(Boolean)
      .map((f) => `<span class="badge med">${esc(f)}</span>`).join(' ');
    /** Bản ghi nhập tay phải nhìn ra ngay, ở cả hai lượt. */
    const manualMark = (source, reason) => source === 'manual'
      ? ` <span class="badge manual" title="${esc(reason || 'nhập tay')}">tay</span>` : '';
    return `<tr>
      <td class="mono">${esc(r.student_id)}</td>
      <td class="wrap" title="${esc(r.name)}">${esc(r.name)}</td>
      <td>${statusBadge(r.call1_status)}${manualMark(r.call1_source, r.call1_reason)}</td>
      <td>${fmtTime(r.call1_ts)}</td>
      <td>${r.call2_status
        ? statusBadge(r.call2_status) + manualMark(r.call2_source, r.call2_reason)
        : '<span class="hint">—</span>'}</td>
      <td>${flags || '<span class="hint">—</span>'}</td>
      <td class="wrap" title="${esc(r.call1_reason || '')}">${esc(r.call1_reason || '—')}</td>
      <td><div class="btn-row">
        <button class="manual-btn" data-sid="${esc(r.student_id)}" data-call="1" data-status="present">L1 có</button>
        <button class="manual-btn" data-sid="${esc(r.student_id)}" data-call="1" data-status="absent">L1 vắng</button>
        <button class="manual-btn" data-sid="${esc(r.student_id)}" data-call="2" data-status="present">L2 có</button>
        <button class="manual-btn" data-sid="${esc(r.student_id)}" data-call="2" data-status="absent">L2 vắng</button>
      </div></td>
    </tr>`;
  }).join('') : '<tr><td colspan="8" class="empty">Không có học viên khớp.</td></tr>';

  $$('.manual-btn').forEach((btn) => btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      await api('/api/admin/manual-checkin', {
        method: 'POST',
        body: {
          session_id: Number(liveSessionId),
          student_id: btn.dataset.sid,
          call_index: Number(btn.dataset.call),
          status: btn.dataset.status,
          reason: $('#manual-reason').value,
          note: $('#manual-note').value.trim(),
        },
      });
      loadLive();
    } catch (err) { alert(err.message); btn.disabled = false; }
  }));
}

async function loadLive() {
  if (!liveSessionId) return;
  try {
    const data = await api(`/api/admin/sessions/${liveSessionId}/live`);
    liveRows = data.rows;
    const present = liveRows.filter((r) => r.call1_status && r.call1_status !== 'absent').length;
    $('#live-count').textContent = `${present}/${liveRows.length} đã điểm danh`;
    renderLive();
  } catch (err) {
    if (err.status === 401) location.href = '/admin/login';
  }
}

loadSessions();
loadManualReasons();
