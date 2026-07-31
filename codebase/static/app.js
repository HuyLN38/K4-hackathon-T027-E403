/* Tiện ích dùng chung. Không framework, không CDN - CSP chỉ cho phép 'self'. */

function getCookie(name) {
  const hit = document.cookie.split('; ').find((c) => c.startsWith(name + '='));
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : '';
}

/** Gọi API. Tự gắn CSRF token cho mọi request đổi trạng thái.
 *
 * `options.timeoutMs` cho trang nào tự làm mới theo nhịp: `fetch` không có hạn
 * chờ mặc định, nên một request treo (wifi rớt giữa chừng, server đang khởi động
 * lại) sẽ không bao giờ settle. Trang nào dựng vòng lặp quanh nó sẽ kẹt vĩnh viễn.
 */
async function api(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = { Accept: 'application/json' };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') headers['X-CSRF-Token'] = getCookie('csrf_token');

  const controller = options.timeoutMs ? new AbortController() : null;
  const timer = controller
    ? setTimeout(() => controller.abort(), options.timeoutMs)
    : null;

  let res;
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: 'same-origin',
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: controller ? controller.signal : undefined,
    });
  } catch (cause) {
    if (cause.name === 'AbortError') throw new Error('Server không trả lời kịp. Đang thử lại…');
    throw cause;
  } finally {
    if (timer) clearTimeout(timer);
  }

  let data = null;
  try { data = await res.json(); } catch { /* trả về không phải JSON */ }
  if (!res.ok) {
    const err = new Error((data && data.error) || `Lỗi ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

/**
 * Nửa "trình duyệt" của danh tính thiết bị (lớp 3).
 *
 * Chỉ lấy các thuộc tính ổn định giữa các buổi (đổi tab, khởi động lại máy vẫn
 * giữ nguyên) và không lấy gì định danh được người. Giá trị này đi kèm với cookie
 * do server phát; server băm cả hai lại thành device_hash và chỉ lưu bản băm.
 *
 * Nằm ở đây chứ không nằm riêng trong checkin.js vì trang /me cũng cần đúng giá
 * trị này để tự nhận ra thiết bị. Hai bản sao lệch nhau một ký tự là ra hai
 * device_hash khác nhau, và triệu chứng sẽ là "tự đăng nhập không chạy" mà không
 * có lỗi nào hiện ra.
 */
function fingerprint() {
  const parts = [
    navigator.userAgent,
    navigator.language,
    navigator.hardwareConcurrency || 0,
    screen.width + 'x' + screen.height + 'x' + (screen.colorDepth || 0),
    new Date().getTimezoneOffset(),
    navigator.maxTouchPoints || 0,
  ];
  return parts.join('|').slice(0, 250);
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function $(selector, root = document) { return root.querySelector(selector); }
function $$(selector, root = document) { return Array.from(root.querySelectorAll(selector)); }

const RISK_LABEL = { ok: 'Ổn', watch: 'Cần theo dõi', at_risk: 'Nguy cơ rời lớp' };
const STATUS_LABEL = { present: 'Có mặt', late: 'Muộn', absent: 'Vắng' };

function riskBadge(level) {
  return `<span class="badge ${esc(level)}">${esc(RISK_LABEL[level] || level)}</span>`;
}

function statusBadge(status) {
  if (!status) return '<span class="badge absent">Vắng</span>';
  return `<span class="badge ${esc(status)}">${esc(STATUS_LABEL[status] || status)}</span>`;
}

function fmtTime(ms) {
  if (!ms) return '—';
  return new Date(ms).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
}

function fmtDateTime(ms) {
  if (!ms) return '—';
  return new Date(ms).toLocaleString('vi-VN', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

/** Hiện thông báo trong một hộp .alert, tự ẩn khi message rỗng. */
function setAlert(node, message, kind = 'error') {
  if (!node) return;
  if (!message) { node.classList.add('hidden'); node.textContent = ''; return; }
  node.className = `alert ${kind}`;
  node.textContent = message;
}

/* Đăng xuất Labcoach. Nằm ở đây chứ không phải script inline trong base.html:
   CSP là `script-src 'self'`, script inline bị trình duyệt chặn thẳng. */
document.addEventListener('DOMContentLoaded', () => {
  const logout = document.getElementById('logout');
  if (!logout) return;
  logout.addEventListener('click', async (e) => {
    e.preventDefault();
    try { await api('/api/admin/logout', { method: 'POST' }); } finally {
      location.href = '/admin/login';
    }
  });
});

/** Vẽ khối rule_trace: vì sao học viên này bị xếp mức đó (§6 - luôn giải thích được). */
function renderTrace(trace) {
  if (!trace) return '';
  const signals = (trace.signals || []).map((s) => `
    <li><span class="signal-code">${esc(s.code)}</span> ${esc(s.note)}
      <span class="hint">(đo ${esc(s.value)} / ngưỡng ${esc(s.threshold)})</span></li>`).join('');
  const dots = (trace.history || []).map((h) => {
    const cls = h.status === 'absent' ? 'absent' : (h.status === 'late' ? 'late' : '');
    const text = h.status === 'absent' ? '—' : (h.late_min ? `${h.late_min}'` : '✓');
    const day = (h.date || '').slice(5);
    return `<div class="dot ${cls}" title="${esc(day)} · ${esc(STATUS_LABEL[h.status] || h.status)}">${esc(text)}</div>`;
  }).join('');

  return `
    <div class="trace">
      <strong>Vì sao:</strong> vắng ${esc(trace.counts.absent)} · muộn ${esc(trace.counts.late)}
      / ${esc(trace.counts.sessions_considered)} buổi gần nhất
      ${signals ? `<ul>${signals}</ul>` : '<div class="hint">Không có tín hiệu nào vượt ngưỡng.</div>'}
      <div class="timeline">${dots}</div>
    </div>`;
}
