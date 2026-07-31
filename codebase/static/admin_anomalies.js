/* Hàng đợi flag. Flag phải có người xử lý, không tự mất.
 *
 * Mặc định gộp theo (rule × học viên) kèm số lần. Lý do: một học viên rời lớp sớm
 * 5 buổi sinh 5 flag EARLY_DEPARTURE giống nhau; để nguyên thì hàng đợi đầy dòng
 * trùng và Labcoach bỏ qua cả hàng đợi - đúng cái bẫy §1 mô tả ("số liệu không
 * được ai đọc"). Gộp theo *học viên* chứ không gộp theo rule, vì đơn vị cần xử lý
 * là một con người, không phải một loại lỗi.
 */

let showResolved = false;
let grouped = true;

/* [nhãn, class] - class quyết định bề rộng cột, khai báo cùng chỗ với tiêu đề để
   ô dữ liệu bên dưới không lệch nấc so với tiêu đề.

   Bỏ cột 'Lần đầu' và cho cột loại flag dùng nhãn ngắn: bảng 8 cột phải nằm gọn
   trong khung, vì bảng kéo ngang thì cột Thao tác nằm ngoài màn hình và không ai
   bấm được nút xử lý. Mốc đầu tiên và câu mô tả đầy đủ chuyển vào tooltip. */
const GROUP_HEAD = [
  ['Loại flag', 'nowrap w-sm'], ['Mức', ''], ['Số lần', 'num'], ['Mã HV', 'nowrap'],
  ['Tên', 'wrap w-sm'], ['Chi tiết gần nhất', 'wrap w-md'], ['Gần nhất', ''], ['Thao tác', ''],
];
const FLAT_HEAD = [
  ['Loại flag', 'nowrap w-sm'], ['Mức', ''], ['Mã HV', 'nowrap'], ['Tên', 'wrap w-sm'],
  ['Buổi', ''], ['Chi tiết', 'wrap w-md'], ['Lúc', ''], ['Thao tác', ''],
];

function setHead(columns) {
  $('#head-row').innerHTML = columns
    .map(([label, cls]) => `<th${cls ? ` class="${cls}"` : ''}>${esc(label)}</th>`)
    .join('');
}

/* Dải chip lọc thay cho năm ô thống kê to.
 *
 * Ô to chiếm nguyên một hàng chỉ để lặp lại con số đã có trong bảng. Chip gọn
 * bằng một dòng và bấm được để lọc — cùng một chỗ vừa cho biết phân bố vừa làm
 * được việc. Câu mô tả đầy đủ của rule nằm ở tooltip. */
let ruleFilter = null;

function renderTotals(byRule, labelOf, shortOf, extra) {
  const entries = Object.entries(byRule).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, n]) => s + n, 0);
  const chip = (code, label, n, title) =>
    `<button class="fchip${ruleFilter === code ? ' on' : ''}" data-rule="${esc(code || '')}"
             title="${esc(title || '')}">${esc(label)}<span class="fchip-n">${n}</span></button>`;

  $('#by-rule').innerHTML = entries.length
    ? chip('', 'Tất cả', total, 'Bỏ lọc')
      + entries.map(([code, n]) =>
          chip(code, shortOf[code] || code, n, `${labelOf[code] || code}\n(${code})`)).join('')
    : '';

  $$('#by-rule .fchip').forEach((b) => b.addEventListener('click', () => {
    ruleFilter = b.dataset.rule || null;
    load();
  }));
  $('#mode-note').innerHTML = extra;
}

/** Nhãn "đã chặn": khác biệt quan trọng nhất giữa hai loại flag, trước đây không
 *  hiện ở đâu cả. attendance_id NULL = lượt quét bị từ chối, không có dòng nào. */
function blockedBadge(blocked, count) {
  if (!blocked) return '';
  return `<span class="badge blocked" title="Lượt quét bị từ chối, không ghi vào bản ghi chuyên cần">`
    + `đã chặn${count > 1 ? ` ×${count}` : ''}</span>`;
}

const byFilter = (r) => !ruleFilter || r.rule_code === ruleFilter;

function labelMap(rows) {
  const map = {};
  rows.forEach((r) => { if (r.label) map[r.rule_code] = r.label; });
  return map;
}

function shortMap(rows) {
  const map = {};
  rows.forEach((r) => { if (r.label_short) map[r.rule_code] = r.label_short; });
  return map;
}

/** Ô "loại flag": nhãn ngắn hiện ra, câu đầy đủ + mã rule nằm ở tooltip. */
function ruleCell(f) {
  const full = `${f.label}\n(${f.rule_code})`;
  return `<td class="w-sm" title="${esc(full)}">${esc(f.label_short || f.label)}</td>`;
}

async function loadGrouped() {
  const data = await api(`/api/admin/anomalies/grouped?resolved=${showResolved ? 1 : 0}`);
  const groups = data.groups.filter(byFilter);
  const { totals } = data;
  setHead(GROUP_HEAD);
  renderTotals(totals.by_rule, labelMap(groups.length ? groups : data.groups),
    shortMap(data.groups),
    `<strong>${totals.flags} flag</strong> gộp thành <strong>${totals.groups} nhóm</strong>
     theo (rule × học viên) — đóng cả nhóm trong một lần bấm.`);

  $('#rows').innerHTML = groups.length ? groups.map((g) => `<tr class="clickable" data-flag="${g.latest_flag_id}">
    ${ruleCell(g)}
    <td><span class="badge ${esc(g.severity)}">${esc(g.severity)}</span></td>
    <td class="num">${g.occurrences > 1
      ? `<span class="badge accent">×${g.occurrences}</span>` : g.occurrences}</td>
    <td class="mono">${esc(g.student_id || '—')}</td>
    <td class="wrap w-sm" title="${esc(g.name || '')}">${esc(g.name || '—')}</td>
    <td class="wrap w-md" title="${esc(g.latest_detail || '')}">${esc(g.latest_detail || '—')}</td>
    <td>${blockedBadge(g.blocked_count > 0, g.blocked_count)}${fmtDateTime(g.last_at)}</td>
    <td><div class="btn-row">${showResolved
      ? '<span class="badge ok">đã xử lý</span>'
      : `<button data-rule="${esc(g.rule_code)}" data-sid="${esc(g.student_id || '')}"
                 data-n="${g.occurrences}">Đã xử lý cả nhóm</button>`}</div></td>
  </tr>`).join('')
    : `<tr><td colspan="8" class="empty">Không có flag ${showResolved ? 'đã xử lý' : 'chưa xử lý'}.</td></tr>`;

  $$('#rows button').forEach((btn) => btn.addEventListener('click', async () => {
    const n = btn.dataset.n;
    const note = prompt(
      `Đánh dấu đã xử lý ${n} flag ${btn.dataset.rule} của ${btn.dataset.sid || '(không rõ HV)'}?\n\n`
      + 'Ghi chú xử lý (ví dụ: đã hỏi học viên, đổi máy thật):', '');
    if (note === null) return;
    btn.disabled = true;
    try {
      const res = await api('/api/admin/anomalies/resolve-group', {
        method: 'POST',
        body: { rule_code: btn.dataset.rule, student_id: btn.dataset.sid || null, note },
      });
      load();
      if (res.resolved > 1) alert(`Đã đóng ${res.resolved} flag trong nhóm.`);
    } catch (err) { alert(err.message); btn.disabled = false; }
  }));
  wireRowClicks();
}

async function loadFlat() {
  const data = await api(`/api/admin/anomalies?resolved=${showResolved ? 1 : 0}`);
  const all = data.flags;
  const flags = all.filter(byFilter);
  setHead(FLAT_HEAD);

  const counts = {};
  all.forEach((f) => { counts[f.rule_code] = (counts[f.rule_code] || 0) + 1; });
  renderTotals(counts, labelMap(all), shortMap(all),
    `Xem <strong>từng flag một</strong> — ${flags.length} dòng.`);

  $('#rows').innerHTML = flags.length ? flags.map((f) => `<tr class="clickable" data-flag="${f.id}">
    ${ruleCell(f)}
    <td><span class="badge ${esc(f.severity)}">${esc(f.severity)}</span></td>
    <td class="mono">${esc(f.student_id || '—')}</td>
    <td class="wrap w-sm" title="${esc(f.name || '')}">${esc(f.name || '—')}</td>
    <td>${esc(f.date || '—')} ${blockedBadge(f.attendance_id === null, 1)}</td>
    <td class="wrap w-md" title="${esc(f.detail || '')}">${esc(f.detail || '—')}</td>
    <td>${fmtDateTime(f.created_at)}</td>
    <td><div class="btn-row">${f.resolved
      ? `<span class="badge ok">${esc(f.resolved_by || 'đã xử lý')}</span>`
      : `<button data-id="${f.id}">Đã xử lý</button>`}</div></td>
  </tr>`).join('')
    : `<tr><td colspan="8" class="empty">Không có flag ${showResolved ? 'đã xử lý' : 'chưa xử lý'}.</td></tr>`;

  $$('#rows button').forEach((btn) => btn.addEventListener('click', async () => {
    const note = prompt('Ghi chú xử lý (ví dụ: đã hỏi học viên, đổi máy thật):', '');
    if (note === null) return;
    btn.disabled = true;
    try {
      await api(`/api/admin/anomalies/${btn.dataset.id}/resolve`, { method: 'POST', body: { note } });
      load();
    } catch (err) { alert(err.message); btn.disabled = false; }
  }));
  wireRowClicks();
}

/* ---------------- chi tiết một flag ----------------
 *
 * Bảng hàng đợi phải cắt chữ bằng "…" để 8 cột nằm vừa khung, nên phải có một chỗ
 * đọc được đầy đủ. Modal này là chỗ đó — và cũng là chỗ hỏi mô hình "chuyện gì đã
 * xảy ra", vì một dòng detail như "thiết bị đã buộc cho K4002" là dữ kiện đúng
 * nhưng chưa dùng được: Labcoach vẫn phải tự ghép xem nên hỏi ai cái gì.
 */
const flagModal = $('#flag-modal');
$('#flag-close').addEventListener('click', () => flagModal.close());

const SEV_VI = { low: 'thấp', med: 'trung bình', high: 'cao' };

function factRows(d) {
  const f = d.flag;
  const rows = [
    ['Loại', `${esc(f.label)} <span class="mono hint">${esc(f.rule_code)}</span>`],
    ['Mức', `<span class="badge ${esc(f.severity)}">${esc(SEV_VI[f.severity] || f.severity)}</span>`],
    ['Học viên', f.student_id
      ? `${esc(f.student_name || '—')} <span class="mono hint">${esc(f.student_id)}</span>`
      : '<span class="hint">không gắn với học viên nào</span>'],
    ['Buổi', f.date ? `${esc(f.date)} · ${esc(f.start_time || '')}${f.room ? ' · ' + esc(f.room) : ''}` : '—'],
    ['Ghi nhận lúc', fmtDateTime(f.created_at)],
    // Đây là thứ hay bị cắt trong bảng. Ở đây cho xuống dòng thoải mái.
    ['Hệ thống ghi lại', `<div class="detail-full">${esc(f.detail || '—')}</div>`],
  ];

  if (d.attendance) {
    const a = d.attendance;
    rows.push(['Bản ghi điểm danh',
      `lượt ${esc(a.call_index)} · ${statusBadge(a.status)} · ${fmtTime(a.checkin_ts_ms)}
       · ${a.source === 'manual' ? 'Labcoach nhập tay' : 'học viên tự quét'}`]);
  } else {
    rows.push(['Bản ghi điểm danh',
      '<span class="badge high">bị chặn</span> <span class="hint">lượt check-in này '
      + 'không được ghi, buổi đó học viên chưa được tính có mặt</span>']);
  }

  if (f.resolved) {
    rows.push(['Đã xử lý bởi', `${esc(f.resolved_by || '—')}`]);
    rows.push(['Ghi chú xử lý', `<div class="detail-full">${esc(f.resolved_note || '—')}</div>`]);
  }

  return `<div class="table-wrap"><table><tbody>${rows.map(([k, v]) =>
    `<tr><td class="nowrap"><strong>${esc(k)}</strong></td><td class="wrap">${v}</td></tr>`)
    .join('')}</tbody></table></div>`;
}

function relatedBlocks(d) {
  const others = d.others_same_session || [];
  const mine = d.student_other_flags || [];
  let out = '';
  if (others.length) {
    out += `<h3 class="mt-md">Cùng buổi, cùng loại</h3>
      <p class="hint">Vế kia của câu chuyện — flag kiểu này thường đi theo cặp.</p>
      <ul class="rel-list">${others.map((o) => `<li>
        <span class="mono">${esc(o.student_id || '—')}</span> ${esc(o.name || '')}
        <span class="hint">${esc(o.detail || '')}</span></li>`).join('')}</ul>`;
  }
  if (mine.length) {
    out += `<h3 class="mt-md">Flag khác của học viên này</h3>
      <ul class="rel-list">${mine.map((m) => `<li>
        <span class="badge ${esc(m.severity)}">${esc(m.severity)}</span>
        ${esc(m.label)} <span class="hint">${fmtDateTime(m.created_at)}</span>
        ${m.resolved ? '<span class="badge ok">đã xử lý</span>' : ''}</li>`).join('')}</ul>`;
  }
  return out;
}

async function openFlag(flagId) {
  $('#flag-body').innerHTML = '<div class="empty">Đang tải…</div>';
  flagModal.showModal();
  try {
    const d = await api(`/api/admin/anomalies/${flagId}`);
    $('#flag-title').textContent = `${d.flag.label_short} · ${d.flag.student_id || '—'}`;
    $('#flag-body').innerHTML = factRows(d) + relatedBlocks(d)
      + (d.llm_enabled
        ? `<div class="card mt-md">
             <div class="card-head">
               <h3>Chuyện gì đã xảy ra</h3>
               <span class="spacer"></span>
               <button id="flag-explain" data-id="${flagId}">Hỏi mô hình</button>
             </div>
             <p class="hint">Mô hình dựng lại chuỗi sự việc từ dữ kiện ở trên và gợi ý
               việc nên kiểm. Nó <strong>không</strong> kết luận có gian lận hay không,
               và <strong>không</strong> đóng flag — hai việc đó là của bạn.</p>
             <div id="flag-explain-out"></div>
           </div>`
        : '<p class="hint mt-md">Tầng mô hình đang tắt — chỉ có phần dữ kiện ở trên.</p>');

    const btn = $('#flag-explain');
    if (btn) btn.addEventListener('click', () => explainFlag(btn));
  } catch (err) {
    if (err.status === 401) { location.href = '/admin/login'; return; }
    $('#flag-body').innerHTML = `<div class="alert error">${esc(err.message)}</div>`;
  }
}

async function explainFlag(btn) {
  const out = $('#flag-explain-out');
  btn.disabled = true;
  const started = Date.now();
  const timer = setInterval(() => {
    btn.textContent = `Đang đọc… ${Math.round((Date.now() - started) / 1000)}s`;
  }, 1000);
  out.innerHTML = '<div class="empty">Mô hình đang đọc dữ kiện…</div>';
  try {
    const r = await api(`/api/admin/anomalies/${btn.dataset.id}/explain`, { method: 'POST' });
    out.innerHTML = r.explanation
      ? `<div class="llm-text">${esc(r.explanation)}</div>`
      : '<p class="hint">Mô hình không trả lời lượt này.</p>';
  } catch (err) {
    out.innerHTML = `<div class="alert error">${esc(err.message)}</div>`;
  } finally {
    clearInterval(timer);
    btn.disabled = false;
    btn.textContent = 'Hỏi lại';
  }
}

/** Bấm vào dòng thì mở chi tiết, trừ khi bấm trúng nút trong dòng đó. */
function wireRowClicks() {
  $$('#rows tr[data-flag]').forEach((tr) => tr.addEventListener('click', (e) => {
    if (e.target.closest('button')) return;
    openFlag(tr.dataset.flag);
  }));
}

async function load() {
  $('#tab-open').className = showResolved ? '' : 'primary';
  $('#tab-done').className = showResolved ? 'primary' : '';
  $('#toggle-group').textContent = grouped ? 'Xem từng flag' : 'Gộp lại';

  try {
    await (grouped ? loadGrouped() : loadFlat());
  } catch (err) {
    if (err.status === 401) { location.href = '/admin/login'; return; }
    $('#rows').innerHTML = `<tr><td colspan="9" class="alert error">${esc(err.message)}</td></tr>`;
  }
}

$('#tab-open').addEventListener('click', () => { showResolved = false; load(); });
$('#tab-done').addEventListener('click', () => { showResolved = true; load(); });
$('#toggle-group').addEventListener('click', () => { grouped = !grouped; load(); });
load();
