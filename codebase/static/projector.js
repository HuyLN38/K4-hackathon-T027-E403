/* Màn hình máy chiếu: mã QR xoay vòng.
 *
 * Server là nguồn sự thật của token và thời gian sống. Trang này chỉ hỏi lại
 * server ngay trước khi mã hết hạn, và đếm ngược cục bộ giữa hai lần hỏi để
 * thanh tiến trình chạy mượt mà không cần poll mỗi giây.
 *
 * Trang **không nhớ** session_id nào cả - nó luôn hỏi "buổi nào đang mở". Màn
 * hình này treo trên tường suốt buổi trong khi Labcoach đóng buổi này mở buổi kia
 * từ một máy khác. Bản trước bám vào session_id nhúng lúc tải, nên sau khi đổi
 * buổi nó hỏi mãi một buổi đã đóng, nhận 409 và đứng yên ở mã đã chết - cả phòng
 * quét vào một mã không còn hiệu lực mà không ai biết.
 */

const FETCH_TIMEOUT_MS = 8000;
const RETRY_MS = 3000;

let sessionId = null;
let expiresAt = 0;
let rotateMs = 20000;
let fetching = false;

function showLive(data) {
  if (data.session_id !== sessionId) {
    sessionId = data.session_id;
    $('#sub').textContent = `Buổi ${data.date} · ${data.start_time}`
      + (data.room ? ` · ${data.room}` : '');
    $('#rotate').disabled = false;
  }
  $('#live').classList.remove('hidden');
  $('#idle').classList.add('hidden');
  $('#qr-frame').classList.remove('stale');
  $('#qr-frame').innerHTML = data.qr_svg;
  $('#url').textContent = data.checkin_url;
  $('#count').textContent = `${data.checked_in}/${data.roster_size}`;
  $('#call').textContent = data.call_index;
  rotateMs = data.rotate_sec * 1000;
  expiresAt = Date.now() + data.expires_in_ms;
  setAlert($('#err'), '');
}

function showIdle() {
  sessionId = null;
  expiresAt = Date.now() + RETRY_MS;
  $('#live').classList.add('hidden');
  $('#idle').classList.remove('hidden');
  $('#rotate').disabled = true;
  $('#qr-frame').innerHTML = '';
  setAlert($('#err'), '');
}

async function refresh() {
  if (fetching) return;
  fetching = true;
  try {
    // Không truyền session_id: server trả về buổi đang mở, kể cả khi đó là buổi
    // vừa được mở sau lúc trang này tải.
    const data = await api('/api/projector/token', { timeoutMs: FETCH_TIMEOUT_MS });
    if (data.open) showLive(data); else showIdle();
  } catch (err) {
    if (err.status === 401) { location.href = '/admin/login'; return; }
    setAlert($('#err'), err.message);
    expiresAt = Date.now() + RETRY_MS;
  } finally {
    // Phải luôn nhả flag này. Để kẹt ở true - ví dụ vì một request treo không bao
    // giờ trả lời - là mã QR đứng yên vĩnh viễn cho tới khi có người F5.
    fetching = false;
  }
}

function tick() {
  if (sessionId === null) {
    if (Date.now() >= expiresAt) refresh();
    return;
  }
  const left = Math.max(0, expiresAt - Date.now());
  $('#secs').textContent = Math.ceil(left / 1000);
  $('#meter').style.width = `${Math.min(100, (left / rotateMs) * 100)}%`;
  // Mã đã hết hạn mà chưa xin được mã mới thì làm mờ đi: một mã chết trên tường
  // trông y hệt mã sống, học viên quét vào rồi mới biết là hỏng.
  $('#qr-frame').classList.toggle('stale', left === 0);
  if (left <= 250) refresh();
}

$('#rotate').addEventListener('click', async () => {
  if (sessionId === null) return;
  try {
    await api(`/api/admin/sessions/${sessionId}/rotate-token`, { method: 'POST' });
    await refresh();
  } catch (err) { setAlert($('#err'), err.message); }
});

// Máy chiếu ngủ / tab bị ẩn thì trình duyệt bóp nghẹt setInterval. Lúc sáng lại
// phải hỏi ngay, không chờ hết nhịp.
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) refresh();
});

refresh();
setInterval(tick, 200);
// Số người đã điểm danh cần cập nhật cả khi mã chưa đổi.
setInterval(refresh, 5000);
