const panel = document.querySelector('#seats-panel');
if (panel) {
  const run = panel.dataset.run;
  const tbody = panel.querySelector('#seats-rows');
  const balance = panel.querySelector('#seats-balance');
  const money = cents => {
    const digits = Math.abs(cents);
    return `${cents < 0 ? '−' : ''}${Math.floor(digits / 100)}.${String(digits % 100).padStart(2, '0')}`;
  };

  async function loadSeats() {
    try {
      const response = await fetch(`/api/seats/${encodeURIComponent(run)}?view=shows&limit=200`);
      if (!response.ok) {
        balance.textContent = '缩座数据未发布';
        balance.className = 'state state--muted';
        return;
      }
      const data = await response.json();
      balance.textContent = data.balanced ? '座位核对一致' : '座位核对未通过';
      balance.className = `state ${data.balanced ? 'state--ok' : 'state--bad'}`;
      tbody.replaceChildren();
      for (const row of data.items) {
        const tr = tbody.insertRow();
        if (!row.balanced) tr.classList.add('has-gap');
        const head = tr.insertCell();
        head.innerHTML = `<strong title="${row.title}">${row.title}</strong><small title="${row.venue}">${row.venue} · ${row.show}</small>`;
        [row.capacity, row.active_count, row.unpaid_released, row.package_split].forEach(value => {
          const td = tr.insertCell();
          td.className = 'num';
          td.textContent = value;
        });
        const due = tr.insertCell();
        due.className = 'num';
        due.textContent = money(row.due_cents);
        const version = tr.insertCell();
        version.className = 'num';
        version.textContent = row.version < 0 ? '基线' : `v${row.version}`;
        const proof = tr.insertCell();
        const link = document.createElement('a');
        link.className = 'isolation-link';
        link.href = `/api/seats/${encodeURIComponent(run)}/holds?show=${encodeURIComponent(row.show)}`;
        link.textContent = '查看占位';
        proof.append(link);
      }
    } catch (error) {
      balance.textContent = '缩座数据读取失败';
      balance.className = 'state state--bad';
    }
  }

  panel.querySelector('#voucher-form').addEventListener('submit', event => {
    event.preventDefault();
    const input = panel.querySelector('#voucher-hold');
    const message = panel.querySelector('#voucher-message');
    const hold_id = input.value.trim();
    if (!hold_id) return;
    window.location.assign(`/api/seats/${encodeURIComponent(run)}/holds/${encodeURIComponent(hold_id)}/voucher`);
    message.textContent = `正在导出占位 ${hold_id} 的凭证…`;
  });

  loadSeats();
}
