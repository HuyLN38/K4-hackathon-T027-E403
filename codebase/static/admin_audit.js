/* Audit log: căn cứ khi một bản ghi chuyên cần bị khiếu nại. */

(async () => {
  try {
    const data = await api('/api/admin/audit?limit=300');
    $('#rows').innerHTML = data.entries.length ? data.entries.map((e) => `<tr>
      <td>${fmtDateTime(e.ts)}</td>
      <td class="mono">${esc(e.actor)}</td>
      <td><span class="badge">${esc(e.action)}</span></td>
      <td class="wrap mono" title="${esc(e.target || '')}">${esc(e.target || '—')}</td>
      <td class="wrap" title="${esc(e.detail || '')}">${esc(e.detail || '—')}</td>
      <td class="mono">${esc(e.ip || '—')}</td>
    </tr>`).join('') : '<tr><td colspan="6" class="empty">Chưa có bản ghi.</td></tr>';
  } catch (err) {
    if (err.status === 401) { location.href = '/admin/login'; return; }
    $('#rows').innerHTML = `<tr><td colspan="6" class="alert error">${esc(err.message)}</td></tr>`;
  }
})();
