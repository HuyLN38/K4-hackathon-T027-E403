/* Dashboard - bản tin đầu ngày: việc duy nhất của Labcoach trong lát cắt (§4.1).
 *
 * Trang này cố tình KHÔNG dựng như một màn hình phân tích số liệu. Việc thật là
 * "sáng nay cần nhắn ai" - đọc 5 cái tên, hiểu vì sao, quyết định. Nên:
 *
 *   - Thứ được phóng to là **dải điểm danh 5 buổi gần nhất** của từng người. Đọc
 *     ngang là ra câu chuyện (muộn → muộn hơn → vắng → vắng), đúng tín hiệu mà §1
 *     nói là "rất rõ nhưng không ai nhìn thấy trong lúc nó đang diễn ra".
 *   - Con số tổng của cả lớp bị thu xuống một thanh tỉ lệ một dòng: nó là bối
 *     cảnh, không phải việc cần làm. Bốn ô thống kê ngang hàng nhau khiến 17 người
 *     "ổn" giành mất chỗ của 5 người cần gọi.
 *   - Câu tiếng Việt đứng trước, mã rule đứng sau và mờ đi. Labcoach đọc "vắng 3
 *     buổi trong 5 buổi gần nhất", không đọc ABSENT_GTE.
 */

const LEVEL_ORDER = ['at_risk', 'watch', 'ok'];
const LEVEL_TEXT = { at_risk: 'nguy cơ rời lớp', watch: 'cần theo dõi', ok: 'ổn' };

/** Ngày dạng 30/07 cho thanh dưới mỗi ô - đủ để đối chiếu, không chiếm chỗ. */
function shortDate(iso) {
  const [, m, d] = (iso || '').split('-');
  return d && m ? `${d}/${m}` : '';
}

/** Dải điểm danh: mỗi buổi một ô, dưới mỗi ô là ngày.
 *
 * Ô chỉ hiện số phút khi buổi đó **thực sự bị tính là muộn**. Trước đây ô hiện
 * "8′" trên nền xanh (vì 8 phút chưa quá ngưỡng 10) - vừa chọi với chú giải, vừa
 * chọi với chính dòng "muộn 0" của cùng thẻ đó. Trễ dưới ngưỡng nằm ở tooltip.
 */
function strip(history) {
  return `<div class="strip">${history.map((h) => {
    const late = h.status === 'late';
    const cls = h.status === 'absent' ? 'absent' : (late ? 'late' : '');
    const mark = h.status === 'absent' ? '–' : (late ? `${h.late_min}′` : '✓');
    const label = h.status === 'absent'
      ? 'vắng'
      : (h.late_min ? `tới muộn ${h.late_min} phút` : 'có mặt đúng giờ');
    return `<div class="strip-cell">
      <div class="strip-mark ${cls}" title="${esc(h.date)} · ${esc(label)}">${esc(mark)}</div>
      <div class="strip-date">${esc(shortDate(h.date))}</div>
    </div>`;
  }).join('')}</div>`;
}

function caseCard(item, rank) {
  const trace = item.rule_trace;
  const all = trace.signals || [];

  // Chỉ nêu tín hiệu **quyết định ra mức**. Vắng 3 buổi kích hoạt cả ABSENT_GTE
  // (at_risk) lẫn ABSENT_WATCH (watch) - in cả hai thì thành hai câu gần trùng
  // nhau, đọc mệt mà không thêm thông tin. Phần còn lại vẫn nằm đủ trong
  // rule_trace và xem được ở hồ sơ học viên.
  const decisive = all.filter((s) => s.tier === item.risk_level);
  const shown = decisive.length ? decisive : all;
  const hidden = all.length - shown.length;

  const signals = shown.map((s) => `<li>
    <span class="why">${esc(s.note)}</span>
    <span class="measure">đo ${esc(s.value)} · ngưỡng ${esc(s.threshold)}</span>
    <span class="code">${esc(s.code)}</span>
  </li>`).join('');

  const action = item.sent
    ? '<span class="badge ok">Đã liên hệ</span>'
    : `<button data-sid="${esc(item.student_id)}" class="mark primary">Đánh dấu đã liên hệ</button>`;

  return `<article class="case ${esc(item.risk_level)}">
    <div class="case-rank">${String(rank).padStart(2, '0')}</div>
    <div class="case-main">
      <div class="case-head">
        <span class="case-name">${esc(item.name)}</span>
        <span class="mono hint">${esc(item.student_id)}</span>
        <span class="spacer"></span>
        ${riskBadge(item.risk_level)}
      </div>
      ${strip(trace.history || [])}
      <ul class="signals">${signals}</ul>
      <div class="case-foot">
        ${hidden ? `<span class="hint">+${hidden} tín hiệu mức thấp hơn</span>` : ''}
        <span class="spacer"></span>
        ${action}
      </div>
    </div>
  </article>`;
}

function renderDistribution(summary, total) {
  // Bề rộng đặt qua CSSOM chứ không phải thuộc tính style= trong markup: CSP của
  // app là `style-src 'self'`, thuộc tính style trong HTML bị trình duyệt chặn.
  const bar = $('#dist');
  bar.innerHTML = '';
  if (total) {
    LEVEL_ORDER.filter((lv) => summary[lv]).forEach((lv) => {
      const seg = document.createElement('i');
      seg.className = `d-${lv}`;
      seg.style.width = `${(summary[lv] / total) * 100}%`;
      seg.title = `${summary[lv]} ${LEVEL_TEXT[lv]}`;
      bar.appendChild(seg);
    });
  }

  $('#dist-legend').innerHTML = LEVEL_ORDER.map((lv) => `<span>
      <i class="swatch d-${lv}"></i><b>${summary[lv] || 0}</b> ${esc(LEVEL_TEXT[lv])}
    </span>`).join('') + `<span class="spacer"></span><span>${total} học viên</span>`;
}

// ---------------- chọn ngày ----------------
const TODAY = new Date().toLocaleDateString('en-CA');   // YYYY-MM-DD theo giờ máy
const DOW = ['Chủ Nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'];
const DOW_SHORT = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'];  // tuần Việt bắt đầu thứ Hai

let selected = TODAY;
let viewMonth = TODAY.slice(0, 7);
let monthDays = {};

const iso = (d) => d.toLocaleDateString('en-CA');
const parse = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
const shift = (s, days) => { const d = parse(s); d.setDate(d.getDate() + days); return iso(d); };

function renderDayLabel() {
  const d = parse(selected);
  $('#day-weekday').textContent = selected === TODAY ? 'Hôm nay' : DOW[d.getDay()];
  $('#day-full').textContent = `${d.getDate()} tháng ${d.getMonth() + 1}, ${d.getFullYear()}`;
  $('#day-next').disabled = selected >= TODAY;      // bản tin ngày mai thì chưa có gì
  $('#day-today').classList.toggle('hidden', selected === TODAY);
}

async function loadMonth(month) {
  viewMonth = month;
  try {
    const data = await api(`/api/admin/calendar?month=${encodeURIComponent(month)}`);
    monthDays = data.days || {};
  } catch { monthDays = {}; }
  renderCalendar();
}

function renderCalendar() {
  const [y, m] = viewMonth.split('-').map(Number);
  $('#cal-month').textContent = `tháng ${m}, ${y}`;
  $('#cal-dow').innerHTML = DOW_SHORT.map((d) => `<span>${d}</span>`).join('');

  const first = new Date(y, m - 1, 1);
  const lead = (first.getDay() + 6) % 7;              // dời để thứ Hai đứng đầu
  const total = new Date(y, m, 0).getDate();

  let html = '';
  for (let i = 0; i < lead; i++) html += '<button class="cal-day other" disabled></button>';
  for (let day = 1; day <= total; day++) {
    const date = `${y}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    const info = monthDays[date] || {};
    const cls = [
      'cal-day',
      date === selected ? 'selected' : '',
      date === TODAY ? 'today' : '',
    ].filter(Boolean).join(' ');
    // Ngày tương lai và ngày không có buổi học đều không mở được bản tin.
    const disabled = date > TODAY || !info.sessions;
    html += `<button class="${cls}" data-date="${date}" ${disabled ? 'disabled' : ''}
      title="${esc(DOW[parse(date).getDay()])}, ${day}/${m}${info.sessions ? ` · ${info.sessions} buổi` : ' · không có lớp'}">
      <span>${day}</span>
      <span class="dot-slot">${info.sessions ? '<i class="dot-session"></i>' : ''}</span>
    </button>`;
  }
  $('#cal-grid').innerHTML = html;

  $$('#cal-grid .cal-day[data-date]').forEach((btn) => {
    if (btn.disabled) return;
    btn.addEventListener('click', () => { setDate(btn.dataset.date); closeCal(); });
  });
}

function openCal() {
  $('#cal').classList.remove('hidden');
  $('#day-label').setAttribute('aria-expanded', 'true');
  loadMonth(selected.slice(0, 7));
}
function closeCal() {
  $('#cal').classList.add('hidden');
  $('#day-label').setAttribute('aria-expanded', 'false');
}

function setDate(date) {
  selected = date;
  renderDayLabel();
  load();
}

$('#day-prev').addEventListener('click', () => setDate(shift(selected, -1)));
$('#day-next').addEventListener('click', () => setDate(shift(selected, 1)));
$('#day-today').addEventListener('click', () => setDate(TODAY));
$('#day-label').addEventListener('click', () => {
  $('#cal').classList.contains('hidden') ? openCal() : closeCal();
});
$('#cal-prev').addEventListener('click', () => {
  const [y, m] = viewMonth.split('-').map(Number);
  loadMonth(iso(new Date(y, m - 2, 1)).slice(0, 7));
});
$('#cal-next').addEventListener('click', () => {
  const [y, m] = viewMonth.split('-').map(Number);
  loadMonth(iso(new Date(y, m, 1)).slice(0, 7));
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeCal(); });
document.addEventListener('click', (e) => {
  if (!$('#cal').classList.contains('hidden') && !e.target.closest('.date-nav')) closeCal();
});

async function load() {
  const date = selected;
  try {
    const data = await api(`/api/admin/briefing?date=${encodeURIComponent(date)}`);
    const summary = data.summary || {};
    const total = LEVEL_ORDER.reduce((n, lv) => n + (summary[lv] || 0), 0);
    const cases = data.cases || [];

    renderDistribution(summary, total);

    if (!data.generated) {
      // Màn hình trống là một lối cụt. Nói rõ vì sao trống, và đưa sẵn nước đi
      // tiếp theo: hoặc dựng bản tin cho ngày này, hoặc nhảy tới ngày gần nhất
      // đã có bản tin.
      const noClass = !data.has_session;
      $('#lead').innerHTML = noClass
        ? `Ngày <b>${esc(shortDate(date))}</b> không có buổi học nào.`
        : `Chưa dựng bản tin cho ngày <b>${esc(shortDate(date))}</b>.`;
      $('#strip-legend').textContent = '';

      const jump = data.latest_available && data.latest_available !== date
        ? `<button id="goto-latest" class="primary" data-date="${esc(data.latest_available)}">
             Xem bản tin gần nhất — ${esc(shortDate(data.latest_available))}</button>` : '';
      $('#cases').innerHTML = `<div class="empty">
        <p>${noClass
          ? 'Không có buổi học thì không có gì để tổng hợp.'
          : 'Bấm <strong>Tính lại</strong> để dựng bản tin cho ngày này.'}</p>
        <div class="btn-row center">${jump}</div>
      </div>`;

      $('#goto-latest')?.addEventListener('click', (e) => setDate(e.target.dataset.date));
      return;
    }

    $('#lead').innerHTML = cases.length
      ? `Hôm nay cần liên hệ <b class="n">${cases.length}</b> ${cases.length > 1 ? 'người' : 'người'},
         xếp theo mức ưu tiên.`
      : 'Hôm nay không có ai vượt ngưỡng.';
    $('#strip-legend').textContent = cases.length
      ? '✓ đúng giờ · 12′ số phút muộn · – vắng' : '';

    $('#cases').innerHTML = cases.length
      ? cases.map((c, i) => caseCard(c, i + 1)).join('')
      : `<div class="empty">Không ai vượt ngưỡng trong ngày này.
           Cả lớp đang trong mức theo dõi bình thường.</div>`;

    // Xuất hiện lần lượt để mắt đi từ ca ưu tiên nhất xuống.
    $$('#cases .case').forEach((el, i) => { el.style.animationDelay = `${i * 45}ms`; });

    $$('.mark').forEach((btn) => btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        await api(`/api/admin/risk/${encodeURIComponent(btn.dataset.sid)}/mark-sent?date=${encodeURIComponent(date)}`,
          { method: 'POST' });
        load();
      } catch (err) { alert(err.message); btn.disabled = false; }
    }));
  } catch (err) {
    if (err.status === 401) { location.href = '/admin/login'; return; }
    $('#cases').innerHTML = `<div class="alert error">${esc(err.message)}</div>`;
  }
}

$('#rebuild').addEventListener('click', async () => {
  const btn = $('#rebuild');
  btn.disabled = true;
  btn.textContent = 'Đang tính…';
  try {
    await api(`/api/admin/briefing/rebuild?date=${encodeURIComponent(selected)}`, { method: 'POST' });
    await load();
  } catch (err) { alert(err.message); }
  btn.disabled = false;
  btn.textContent = 'Tính lại';
});

renderDayLabel();
load();
