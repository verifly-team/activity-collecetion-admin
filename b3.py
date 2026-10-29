import pathlib

p = pathlib.Path("static/index.html")
s = p.read_text(encoding="utf-8")

EVENT_CN = {
    "export_xlsx": "导出 Excel",
    "export_zip": "打包下载",
    "export_zip_done": "打包完成",
    "reveal_phone": "查看手机号",
}

old = "  function showApp() {"
new = '''  const EVENT_CN = {
    export_xlsx: '导出 Excel',
    export_zip: '打包下载',
    export_zip_done: '打包完成',
    reveal_phone: '查看手机号',
  };

  function renderAudit(items) {
    const tb = $('auditBody');
    $('auditEmpty').classList.toggle('hidden', items.length > 0);
    tb.innerHTML = items
      .map((it) => {
        const ev = it.event || '';
        let cls = 'ev';
        if (ev === 'export_zip') cls += ' zip';
        if (ev === 'reveal_phone') cls += ' phone';
        if (ev === 'export_zip_done') cls += it.aborted ? ' abort' : ' done';
        const label = EVENT_CN[ev] || ev;

        let detail = '';
        if (ev === 'export_xlsx' || ev === 'export_zip') {
          detail = `报名 <b>${esc(it.ids || '-')}</b> · ${it.count || 0} 条 · 附件 ${it.files || 0} 个`
            + (it.mb ? ` · ${it.mb} MB` : '');
        } else if (ev === 'export_zip_done') {
          detail = it.aborted
            ? `未下载完，已发送 <b>${it.mb || 0} MB</b>`
            : `已发送 <b>${it.mb || 0} MB</b>`;
        } else if (ev === 'reveal_phone') {
          detail = `报名 <b>#${esc(it.application_id)}</b>`;
        }

        const ts = (it.ts || '').replace('T', ' ').slice(0, 19);
        const ua = esc((it.ua || '').slice(0, 46));
        return `<tr>
          <td class="mono nowrap">${esc(ts)}</td>
          <td class="nowrap"><span class="${cls}">${esc(label)}</span></td>
          <td class="mono nowrap" title="${esc(it.ua || '')}">${esc(it.ip || '-')}</td>
          <td class="detail" data-label="明细">${detail}<div class="muted" style="font-size:11px">${ua}</div></td>
        </tr>`;
      })
      .join('');
  }

  async function loadAudit() {
    $('auditBody').innerHTML = '<tr><td colspan="4" class="loading"><span class="spin"></span>加载中</td></tr>';
    try {
      const ev = $('auditFilter').value;
      const q = '/api/v1/audit?limit=300' + (ev ? '&event=' + encodeURIComponent(ev) : '');
      const data = await api(q);
      renderAudit(data.items || []);
    } catch (e) {
      $('auditBody').innerHTML = `<tr><td colspan="4" class="empty">${esc(e.message || '加载失败')}</td></tr>`;
    }
  }

  function showAudit() {
    $('listWrap').classList.add('hidden');
    $('actionbar').classList.add('hidden');
    $('auditWrap').classList.remove('hidden');
    loadAudit();
  }

  function showList() {
    $('auditWrap').classList.add('hidden');
    $('listWrap').classList.remove('hidden');
    $('actionbar').classList.remove('hidden');
  }

  function showApp() {'''
assert old in s
s = s.replace(old, new, 1)

# 事件绑定
old_bind = "  $('logoutBtn').addEventListener('click', () => {"
new_bind = """  $('auditBtn').addEventListener('click', showAudit);
  $('backBtn').addEventListener('click', showList);
  $('auditRefresh').addEventListener('click', loadAudit);
  $('auditFilter').addEventListener('change', loadAudit);

  $('logoutBtn').addEventListener('click', () => {"""
assert old_bind in s
s = s.replace(old_bind, new_bind, 1)

p.write_text(s, encoding="utf-8")
print("审计页面 JS 完成")
