/* Trang check-in của học viên.
 *
 * `fingerprint()` nằm ở app.js: trang /me cũng dùng đúng hàm đó để tự nhận ra
 * thiết bị, và hai bản sao lệch nhau là hai device_hash khác nhau.
 */

const sid = $('#sid');
const btn = $('#submit');
const msg = $('#msg');

sid.focus();
sid.addEventListener('keydown', (e) => { if (e.key === 'Enter') btn.click(); });

btn.addEventListener('click', async () => {
  const studentId = sid.value.trim().toUpperCase();
  if (!studentId) { setAlert(msg, 'Nhập mã học viên của bạn.'); sid.focus(); return; }

  btn.disabled = true;
  btn.textContent = 'Đang ghi nhận…';
  setAlert(msg, '');

  try {
    const res = await api('/api/checkin', {
      method: 'POST',
      body: { token: $('#token').value, student_id: studentId, fingerprint: fingerprint() },
    });

    $('#form-card').classList.add('hidden');
    const done = $('#done-card');
    done.classList.remove('hidden');

    const late = res.status === 'late';
    const mark = $('#done-mark');
    mark.textContent = late ? '⏱' : '✓';
    mark.classList.toggle('late', late);

    // Tên to nhất trên màn hình: đây là thứ học viên cần soát, không phải chữ
    // "đã ghi nhận".
    $('#done-name').textContent = res.student_name;
    $('#done-id').textContent = res.student_id;
    $('#done-status').innerHTML = late
      ? `${statusBadge('late')} muộn ${esc(res.late_minutes)} phút`
      : `${statusBadge('present')} đúng giờ`;

    // Mỗi thông tin một dòng, giá trị ngắn để không xuống dòng giữa cụm từ.
    const facts = [
      ['Buổi học', res.session_date],
      ['Phòng', res.room || '—'],
      ['Giờ bắt đầu', res.session_start_time],
      ['Giờ bạn điểm danh', fmtTime(res.checkin_ts)],
      ['Lượt điểm danh', `lượt ${res.call_index}`],
      ['Tổng số buổi đã dự', `${res.attended_sessions} buổi`],
    ];
    $('#done-facts').innerHTML = facts
      .map(([k, v]) => `<div><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span></div>`)
      .join('');

    const notes = [];
    if (res.device_locked_now) {
      notes.push('Thiết bị này vừa được buộc với mã học viên của bạn. Các buổi sau hãy dùng đúng thiết bị này — mỗi thiết bị chỉ điểm danh cho một người.');
    }
    (res.flags || []).forEach((f) => notes.push(`Đã ghi nhận dấu hiệu cần xem lại: ${f.label}.`));
    $('#done-flags').innerHTML = notes.length
      ? notes.map((n) => `<div class="note mb-sm">${esc(n)}</div>`).join('')
      : '';

    $('#again').addEventListener('click', () => {
      done.classList.add('hidden');
      $('#form-card').classList.remove('hidden');
      sid.value = '';
      btn.disabled = false;
      btn.textContent = 'Ghi nhận có mặt';
      setAlert(msg, '');
      sid.focus();
    });
  } catch (err) {
    setAlert(msg, err.message);
    btn.disabled = false;
    btn.textContent = 'Ghi nhận có mặt';
  }
});
