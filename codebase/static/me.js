/* Trang học viên tự xem dữ liệu của mình.
 *
 * Có trang này vì §6 coi "hệ thống bị xem là công cụ giám sát" là một rủi ro thật.
 * Cách giảm: học viên thấy đúng những gì Labcoach thấy về mình, kể cả ngưỡng và
 * lý do xếp mức - không có số nào chỉ một bên đọc được.
 */

async function loadMe() {
  try {
    const d = await api('/api/student/me');
    $('#login-card').classList.add('hidden');
    const area = $('#data-area');
    area.classList.remove('hidden');

    const rows = d.history.map((h) => `<tr>
      <td>${esc(h.date)}</td>
      <td>${esc(h.start_time)}</td>
      <td>${statusBadge(h.status)}</td>
      <td>${h.checkin_ts_ms ? fmtTime(h.checkin_ts_ms) : '—'}</td>
      <td>${h.source === 'manual' ? '<span class="badge manual">nhập tay</span>' : (h.source ? 'tự động' : '—')}</td>
    </tr>`).join('');

    const flags = d.flags.length ? `
      <div class="card">
        <div class="card-head"><h2>Dấu hiệu đã ghi nhận</h2></div>
        <p class="hint">Flag không phải kết luận — Labcoach xem lại rồi mới xử lý.</p>
        <div class="table-wrap">
          <table><thead><tr><th>Dấu hiệu</th><th>Mức</th><th>Lúc</th><th>Trạng thái</th></tr></thead>
          <tbody>${d.flags.map((f) => `<tr>
            <td class="wrap">${esc(f.label)}</td>
            <td><span class="badge ${esc(f.severity)}">${esc(f.severity)}</span></td>
            <td>${fmtDateTime(f.created_at)}</td>
            <td>${f.resolved ? '<span class="badge ok">Đã xử lý</span>' : '<span class="badge med">Đang chờ</span>'}</td>
          </tr>`).join('')}</tbody></table>
        </div>
      </div>` : '';

    area.innerHTML = `
      <div class="card">
        <div class="card-head">
          <h2>${esc(d.student.name)}</h2>
          <span class="mono hint">${esc(d.student.student_id)}</span>
          <span class="spacer"></span>
          ${riskBadge(d.risk_level)}
        </div>
        ${renderTrace(d.rule_trace)}
        <p class="hint mt-sm">
          Ngưỡng công khai: vắng ≤1 là ổn · vắng 2 hoặc muộn ≥3 buổi là cần theo dõi ·
          vắng ≥3 là nguy cơ rời lớp. Tính trên ${esc(d.rule_trace.window_sessions)} buổi gần nhất.
        </p>
        ${d.student.device_locked_at
          ? `<p class="hint">Thiết bị của bạn đã khoá từ ${fmtDateTime(d.student.device_locked_at)}.
             Đổi máy thì nhờ Labcoach mở khoá.</p>` : ''}
        ${d.auth_via === 'device'
          ? `<p class="hint">Bạn vào được trang này vì <strong>máy này đã buộc với mã học viên
               của bạn</strong> — không cần nhập PIN. Đưa máy cho người khác thì bấm
               <em>Đăng xuất</em> bên dưới.</p>` : ''}
      </div>
      ${flags}
      <div class="card">
        <div class="card-head"><h2>Lịch sử điểm danh</h2></div>
        <div class="table-wrap">
          <table><thead><tr><th>Ngày</th><th>Giờ</th><th>Trạng thái</th><th>Check-in</th><th>Nguồn</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="5" class="empty">Chưa có buổi nào đã đóng.</td></tr>'}</tbody></table>
        </div>
      </div>
      <div class="btn-row"><button id="out">Đăng xuất</button></div>`;

    $('#out').addEventListener('click', async () => {
      await api('/api/student/logout', { method: 'POST' });
      location.reload();
    });
    return true;
  } catch (err) {
    if (err.status === 401) return false;
    setAlert($('#msg'), err.message);
    return false;
  }
}

async function login() {
  const btn = $('#go');
  btn.disabled = true;
  setAlert($('#msg'), '');
  try {
    await api('/api/student/login', {
      method: 'POST',
      body: { student_id: $('#sid').value.trim().toUpperCase(), pin: $('#pin').value },
    });
    await loadMe();
  } catch (err) {
    setAlert($('#msg'), err.message);
    btn.disabled = false;
  }
}

/** Thử nhận ra thiết bị đã buộc. Trả true nếu vào thẳng được, không thì false. */
async function tryDevice() {
  try {
    await api('/api/student/device-session', {
      method: 'POST',
      body: { fingerprint: fingerprint() },
    });
    return await loadMe();
  } catch {
    // 401 ở đây là chuyện bình thường: máy chưa buộc, máy mượn, hoặc vừa đăng
    // xuất. Không phải lỗi để hiện lên - chỉ nghĩa là phải nhập PIN.
    return false;
  }
}

$('#go').addEventListener('click', login);
$('#pin').addEventListener('keydown', (e) => { if (e.key === 'Enter') login(); });

/* Thứ tự: phiên sẵn có -> thiết bị đã buộc -> form PIN.
   Học viên mở /me trên đúng điện thoại vẫn dùng để điểm danh thì không phải gõ gì. */
(async () => {
  const done = () => $('#checking').classList.add('hidden');
  if (await loadMe()) { done(); return; }
  if (await tryDevice()) { done(); return; }
  done();
  $('#login-card').classList.remove('hidden');
})();
