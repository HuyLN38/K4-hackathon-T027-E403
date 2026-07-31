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

// Ô thống kê là chỗ duy nhất còn đủ rộng cho câu mô tả đầy đủ, nên nó gánh phần
// giải nghĩa cho nhãn ngắn dùng trong bảng. Mã kỹ thuật lùi xuống dòng phụ:
// Labcoach đọc bảng này để biết chuyện gì đang xảy ra, không phải để tra spec.
function renderTotals(byRule, labelOf, extra) {
  const entries = Object.entries(byRule).sort();
  $('#by-rule').innerHTML = entries.length
    ? entries.map(([code, n]) => `<div class="stat">
        <div class="label">${esc(labelOf[code] || code)}</div>
        <div class="value">${n}</div>
        <div class="sub mono">${esc(code)}</div>
      </div>`).join('')
    : '';
  $('#mode-note').innerHTML = extra;
}

function labelMap(rows) {
  const map = {};
  rows.forEach((r) => { if (r.label) map[r.rule_code] = r.label; });
  return map;
}

/** Ô "loại flag": nhãn ngắn hiện ra, câu đầy đủ + mã rule nằm ở tooltip. */
function ruleCell(f) {
  const full = `${f.label}\n(${f.rule_code})`;
  return `<td class="w-sm" title="${esc(full)}">${esc(f.label_short || f.label)}</td>`;
}

async function loadGrouped() {
  const data = await api(`/api/admin/anomalies/grouped?resolved=${showResolved ? 1 : 0}`);
  const { groups, totals } = data;
  setHead(GROUP_HEAD);
  renderTotals(totals.by_rule, labelMap(groups),
    `Gộp <strong>${totals.flags} flag</strong> thành <strong>${totals.groups} nhóm</strong>
     theo (rule × học viên). Bấm <em>Đã xử lý cả nhóm</em> để đóng hết một nhóm trong một lần —
     bắt bấm ${totals.flags} lần thì kết quả thực tế là không ai bấm lần nào.`);

  $('#rows').innerHTML = groups.length ? groups.map((g) => `<tr>
    ${ruleCell(g)}
    <td><span class="badge ${esc(g.severity)}">${esc(g.severity)}</span></td>
    <td class="num">${g.occurrences > 1
      ? `<span class="badge accent">×${g.occurrences}</span>` : g.occurrences}</td>
    <td class="mono">${esc(g.student_id || '—')}</td>
    <td class="wrap w-sm" title="${esc(g.name || '')}">${esc(g.name || '—')}</td>
    <td class="wrap w-md" title="${esc(g.latest_detail || '')}">${esc(g.latest_detail || '—')}</td>
    <td title="lần đầu: ${fmtDateTime(g.first_at)}">${fmtDateTime(g.last_at)}</td>
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
}

async function loadFlat() {
  const data = await api(`/api/admin/anomalies?resolved=${showResolved ? 1 : 0}`);
  const flags = data.flags;
  setHead(FLAT_HEAD);

  const counts = {};
  flags.forEach((f) => { counts[f.rule_code] = (counts[f.rule_code] || 0) + 1; });
  renderTotals(counts, labelMap(flags), `Đang xem <strong>từng flag một</strong> (${flags.length} dòng).
    Bấm <em>Gộp lại</em> để xem dạng nhóm.`);

  $('#rows').innerHTML = flags.length ? flags.map((f) => `<tr>
    ${ruleCell(f)}
    <td><span class="badge ${esc(f.severity)}">${esc(f.severity)}</span></td>
    <td class="mono">${esc(f.student_id || '—')}</td>
    <td class="wrap w-sm" title="${esc(f.name || '')}">${esc(f.name || '—')}</td>
    <td>${esc(f.date || '—')}</td>
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
