/* Trang check-in của học viên.
 *
 * `fingerprint()` nằm ở app.js: trang /me cũng dùng đúng hàm đó để tự nhận ra
 * thiết bị, và hai bản sao lệch nhau là hai device_hash khác nhau.
 */

const sid = $('#sid');
const btn = $('#submit');
const msg = $('#msg');

sid.addEventListener('keydown', (e) => { if (e.key === 'Enter') btn.click(); });

/** Hiện form nhập mã. Dùng cho máy chưa buộc, và cho nút "không phải tôi". */
function showForm(note) {
  $('#detecting').classList.add('hidden');
  $('#form-card').classList.remove('hidden');
  if (note) $('#first-time-note').textContent = note;
  sid.focus();
}

async function submitCheckin(studentId, { auto = false } = {}) {
  btn.disabled = true;
  btn.textContent = 'Đang ghi nhận…';
  setAlert(msg, '');

  try {
    const res = await api('/api/checkin', {
      method: 'POST',
      body: { token: $('#token').value, student_id: studentId, fingerprint: fingerprint() },
    });

    $('#detecting').classList.add('hidden');
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

    $('#confirm-why').textContent = auto
      ? 'Máy này đang buộc với mã học viên ở trên nên hệ thống tự ghi. Nếu đây '
        + 'không phải bạn — máy mượn, hoặc Labcoach buộc nhầm người — báo Labcoach '
        + 'nhả thiết bị ngay, vì buổi này đang được ghi cho người có tên ở trên.'
      : 'Nếu đây không phải bạn thì mã học viên đã gõ sai — báo Labcoach ngay '
        + 'để sửa, vì buổi này đang được ghi cho người có tên ở trên.';

    const notes = [];
    if (res.device_locked_now) {
      notes.push('Thiết bị này vừa được buộc với mã học viên của bạn. Từ buổi sau chỉ cần quét mã là xong — không phải nhập lại mã học viên.');
    }
    (res.flags || []).forEach((f) => notes.push(`Đã ghi nhận dấu hiệu cần xem lại: ${f.label}.`));
    $('#done-flags').innerHTML = notes.length
      ? notes.map((n) => `<div class="note mb-sm">${esc(n)}</div>`).join('')
      : '';

    $('#again').addEventListener('click', () => {
      done.classList.add('hidden');
      sid.value = '';
      btn.disabled = false;
      btn.textContent = 'Ghi nhận có mặt';
      setAlert(msg, '');
      showForm('Nhập mã của người cần điểm danh.');
    });
  } catch (err) {
    // Hỏng ở đây thì phải quay về form: có thể máy đã buộc cho người khác, hoặc
    // học viên này đã điểm danh rồi. Cả hai đều cần người đọc thông báo và tự
    // quyết, không phải một màn hình trắng.
    showForm();
    setAlert(msg, err.message);
    btn.disabled = false;
    btn.textContent = 'Ghi nhận có mặt';
  }
}

btn.addEventListener('click', () => {
  const studentId = sid.value.trim().toUpperCase();
  if (!studentId) { setAlert(msg, 'Nhập mã học viên của bạn.'); sid.focus(); return; }
  submitCheckin(studentId);
});

/* Lần đầu hỏi mã, từ lần sau tự nhận.
 *
 * Gõ mã mỗi buổi là nguồn sai thật: nhầm một ký tự thì buổi đó ghi cho người
 * khác, rồi ràng buộc "một thiết bị một học viên" chặn luôn lượt đúng của cả hai
 * người. Máy đã buộc rồi thì server biết chắc chắn hơn học viên gõ tay.
 *
 * Tự ghi luôn chứ không chỉ điền sẵn: quét mã QR đang chiếu trên tường ĐÃ là
 * hành động xác nhận có mặt. Bắt bấm thêm một nút nữa không thêm thông tin gì. */
(async () => {
  $('#detecting').classList.remove('hidden');
  try {
    const who = await api('/api/checkin/whoami', {
      method: 'POST',
      body: { fingerprint: fingerprint() },
    });
    if (who.bound) {
      $('#detecting').querySelector('.empty').textContent =
        `Nhận ra ${who.name} (${who.student_id}) — đang ghi nhận…`;
      await submitCheckin(who.student_id, { auto: true });
      return;
    }
  } catch {
    /* không nhận được thì hỏi mã như cũ */
  }
  showForm();
})();
