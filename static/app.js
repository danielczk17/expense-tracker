// ── Config ───────────────────────────────────────────────────────────────────
const CURRENCY = 'S$';

const CATEGORY_COLORS = {
  'Food & Dining':  '#f97316',
  'Transport':      '#06b6d4',
  'Shopping':       '#8b5cf6',
  'Entertainment':  '#ec4899',
  'Health':         '#10b981',
  'Utilities':      '#f59e0b',
  'Housing':        '#3b82f6',
  'Education':      '#14b8a6',
  'Travel':         '#6366f1',
  'Other':          '#94a3b8',
};

// ── State ─────────────────────────────────────────────────────────────────────
let currentMonth  = new Date().toISOString().slice(0, 7);
let summaryData   = null;
let allExpenses   = [];
let categories    = [];
let editingId     = null;
let selectedIds   = new Set();
let confirmResolve = null;
let expPage       = 1;
let stmtRows      = [];
const EXP_PAGE_SIZE = 25;

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', init);

async function init() {
  loadDarkMode();
  document.getElementById('month-picker').value = currentMonth;
  await loadCategories();
  await Promise.all([loadSummary(), loadExpenses()]);
  setDefaultDate();
}

// ── Month navigation ──────────────────────────────────────────────────────────
function setMonth(m) {
  currentMonth = m;
  document.getElementById('month-picker').value = m;
  expPage = 1;
  Promise.all([loadSummary(), loadExpenses()]);
}

function shiftMonth(delta) {
  const [y, mo] = currentMonth.split('-').map(Number);
  const d  = new Date(y, mo - 1 + delta, 1);
  const nm = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
  setMonth(nm);
}

// ── Data loading ──────────────────────────────────────────────────────────────
async function loadSummary() {
  setSpinner(true);
  try {
    const res  = await fetch(`/api/summary?month=${currentMonth}`);
    summaryData = await res.json();
    renderSummaryStrip(summaryData);
    renderCategoryChart(summaryData);
    renderMonthlyChart(summaryData);
    const budgetTab = document.getElementById('tab-budget');
    if (budgetTab && budgetTab.style.display !== 'none') {
      renderBudgetTab(summaryData);
    }
  } finally {
    setSpinner(false);
  }
}

async function loadExpenses() {
  const res  = await fetch(`/api/expenses?month=${currentMonth}`);
  allExpenses = await res.json();
  selectedIds.clear();
  renderExpensesTable(allExpenses);
}

async function loadCategories() {
  const res  = await fetch('/api/categories');
  categories = await res.json();
  populateCategoryDropdown();
}

// ── Category dropdown ─────────────────────────────────────────────────────────
function populateCategoryDropdown() {
  const sel = document.getElementById('f-category');
  const cur = sel.value;
  sel.innerHTML = '';
  for (const cat of categories) {
    const opt = document.createElement('option');
    opt.value = cat;
    opt.textContent = cat;
    sel.appendChild(opt);
  }
  if (cur && categories.includes(cur)) sel.value = cur;
}

// ── Summary strip ─────────────────────────────────────────────────────────────
function renderSummaryStrip(data) {
  document.getElementById('s-total').textContent = fmt(data.total);

  const budgetEl    = document.getElementById('s-budget-used');
  const budgetSubEl = document.getElementById('s-budget-sub');
  if (data.total_budget != null && data.total_budget > 0) {
    const pct = Math.round((data.total / data.total_budget) * 100);
    const rem = data.total_budget - data.total;
    budgetEl.textContent  = pct + '%';
    budgetEl.className    = 'val ' + (pct >= 100 ? 'neg' : pct >= 80 ? '' : 'pos');
    budgetSubEl.textContent = rem >= 0
      ? fmt(rem) + ' remaining'
      : fmt(-rem) + ' over budget';
  } else {
    budgetEl.textContent  = 'No budget';
    budgetEl.className    = 'val neutral';
    budgetSubEl.textContent = 'Set in Budget tab';
  }

  const expCount = data.by_category.reduce((s, c) => s + c.count, 0);
  document.getElementById('s-count').textContent = expCount;

  const topCatEl    = document.getElementById('s-top-cat');
  const topCatAmtEl = document.getElementById('s-top-cat-amt');
  if (data.by_category.length > 0) {
    topCatEl.textContent    = data.by_category[0].category;
    topCatAmtEl.textContent = fmt(data.by_category[0].total);
  } else {
    topCatEl.textContent    = '—';
    topCatAmtEl.textContent = '';
  }

  document.getElementById('s-ytd').textContent = fmt(data.ytd_total);
}

// ── Category donut chart ──────────────────────────────────────────────────────
function renderCategoryChart(data) {
  const area     = document.getElementById('cat-chart-area');
  const empty    = document.getElementById('cat-chart-empty');
  const monthLbl = document.getElementById('cat-chart-month');

  const d = new Date(data.month + '-01');
  monthLbl.textContent = d.toLocaleString('default', { month: 'long', year: 'numeric' });

  if (!data.by_category.length) {
    area.style.display  = 'none';
    empty.style.display = '';
    return;
  }
  area.style.display  = '';
  empty.style.display = 'none';

  const segments = data.by_category.map(c => ({
    label: c.category,
    value: c.total,
    color: getCategoryColor(c.category),
  }));

  document.getElementById('donut-label-val').textContent = fmt(data.total);

  const canvas = document.getElementById('cat-canvas');
  requestAnimationFrame(() => drawDonut(canvas, segments));

  const legend = document.getElementById('cat-legend');
  legend.innerHTML = '';
  for (const seg of segments) {
    const pct = data.total > 0 ? (seg.value / data.total * 100).toFixed(1) : '0.0';
    const row = document.createElement('div');
    row.style.cssText = 'display:grid;grid-template-columns:10px 1fr auto auto;align-items:center;gap:.5rem;font-size:.8rem';
    row.innerHTML =
      `<div style="width:10px;height:10px;border-radius:50%;background:${seg.color};flex-shrink:0"></div>` +
      `<div style="color:var(--text);font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(seg.label)}</div>` +
      `<div style="color:var(--text-muted);font-size:.72rem;white-space:nowrap">${fmt(seg.value)}</div>` +
      `<div style="font-weight:700;min-width:44px;text-align:right">${pct}%</div>`;
    legend.appendChild(row);
  }
}

// ── Monthly trend bar chart ───────────────────────────────────────────────────
function renderMonthlyChart(data) {
  const area  = document.getElementById('trend-chart-area');
  const empty = document.getElementById('trend-empty');

  if (!data.monthly_totals.length) {
    area.style.display  = 'none';
    empty.style.display = '';
    return;
  }
  area.style.display  = '';
  empty.style.display = 'none';

  const canvas = document.getElementById('trend-canvas');
  requestAnimationFrame(() => drawBarChart(canvas, data.monthly_totals));
}

// ── Expenses table ────────────────────────────────────────────────────────────
function renderExpensesTable(expenses) {
  const wrap = document.getElementById('exp-wrap');
  updateSelectionUI();

  if (!expenses.length) {
    wrap.innerHTML = '<div class="empty">No expenses for this month.</div>';
    return;
  }

  const total = expenses.length;
  const pages = Math.ceil(total / EXP_PAGE_SIZE);
  if (expPage > pages) expPage = pages;
  const slice = expenses.slice((expPage - 1) * EXP_PAGE_SIZE, expPage * EXP_PAGE_SIZE);

  let html = `<table>
    <thead><tr>
      <th class="chk"><input type="checkbox" id="chk-all" onchange="toggleAllExpenses(this.checked)"></th>
      <th style="text-align:left">Date</th>
      <th style="text-align:left">Category</th>
      <th>Amount</th>
      <th style="text-align:left">Description</th>
    </tr></thead><tbody>`;

  for (const e of slice) {
    const sel   = selectedIds.has(e.id);
    const color = getCategoryColor(e.category);
    html += `<tr class="${sel ? 'selected' : ''}" data-id="${escAttr(e.id)}">
      <td class="chk"><input type="checkbox" ${sel ? 'checked' : ''} onchange="toggleExpenseRow(this,'${escAttr(e.id)}')" /></td>
      <td>${escHtml(e.date)}</td>
      <td><span class="cat-chip" style="background:${color}1a;color:${color};border-color:${color}40">${escHtml(e.category)}</span></td>
      <td>${fmt(e.amount)}</td>
      <td style="color:var(--text-muted)">${escHtml(e.description)}</td>
    </tr>`;
  }
  html += '</tbody></table>';

  if (pages > 1) {
    html += '<div class="pagination">';
    html += `<button onclick="expPage=Math.max(1,expPage-1);renderExpensesTable(allExpenses)" ${expPage === 1 ? 'disabled' : ''}>&#8249;</button>`;
    for (let p = 1; p <= pages; p++) {
      html += `<button class="${p === expPage ? 'pg-active' : ''}" onclick="expPage=${p};renderExpensesTable(allExpenses)">${p}</button>`;
    }
    html += `<button onclick="expPage=Math.min(${pages},expPage+1);renderExpensesTable(allExpenses)" ${expPage === pages ? 'disabled' : ''}>&#8250;</button>`;
    html += '</div>';
  }

  wrap.innerHTML = html;

  // Restore "check all" state
  const allOnPage = slice.every(e => selectedIds.has(e.id));
  const chkAll = document.getElementById('chk-all');
  if (chkAll) chkAll.checked = allOnPage && slice.length > 0;
}

function toggleAllExpenses(checked) {
  const slice = allExpenses.slice((expPage - 1) * EXP_PAGE_SIZE, expPage * EXP_PAGE_SIZE);
  slice.forEach(e => checked ? selectedIds.add(e.id) : selectedIds.delete(e.id));
  renderExpensesTable(allExpenses);
}

function toggleExpenseRow(cb, id) {
  if (cb.checked) selectedIds.add(id); else selectedIds.delete(id);
  cb.closest('tr').classList.toggle('selected', cb.checked);
  updateSelectionUI();
  const slice   = allExpenses.slice((expPage - 1) * EXP_PAGE_SIZE, expPage * EXP_PAGE_SIZE);
  const allSel  = slice.length > 0 && slice.every(e => selectedIds.has(e.id));
  const chkAll  = document.getElementById('chk-all');
  if (chkAll) chkAll.checked = allSel;
}

function updateSelectionUI() {
  const count = selectedIds.size;
  document.getElementById('exp-sel-count').textContent  = count > 0 ? `${count} selected` : '';
  document.getElementById('exp-edit-btn').disabled      = count !== 1;
  document.getElementById('exp-delete-btn').disabled    = count === 0;
}

// ── Add / Edit expense ────────────────────────────────────────────────────────
function setDefaultDate() {
  const today = new Date();
  const iso   = today.getFullYear() + '-' +
                String(today.getMonth() + 1).padStart(2, '0') + '-' +
                String(today.getDate()).padStart(2, '0');
  document.getElementById('f-date').value = iso;
}

async function submitExpense() {
  const date     = document.getElementById('f-date').value;
  const category = document.getElementById('f-category').value;
  const amount   = document.getElementById('f-amount').value;
  const desc     = document.getElementById('f-desc').value;

  if (!date || !category || !amount) {
    showToast('Please fill in Date, Category, and Amount', 'error');
    return;
  }

  const body = { date, category, amount: parseFloat(amount), description: desc };

  if (editingId) {
    const res  = await fetch(`/api/expense/${editingId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.error) { showToast(data.error, 'error'); return; }
    showToast('Expense updated');
    cancelEdit();
  } else {
    const res  = await fetch('/api/expense', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.error) { showToast(data.error, 'error'); return; }
    showToast('Expense added');
    document.getElementById('f-amount').value = '';
    document.getElementById('f-desc').value   = '';
  }

  expPage = 1;
  await Promise.all([loadSummary(), loadExpenses()]);
}

function startEdit() {
  if (selectedIds.size !== 1) return;
  const id  = [...selectedIds][0];
  const exp = allExpenses.find(e => e.id === id);
  if (!exp) return;

  editingId = id;
  document.getElementById('f-date').value     = exp.date;
  document.getElementById('f-category').value = exp.category;
  document.getElementById('f-amount').value   = exp.amount;
  document.getElementById('f-desc').value     = exp.description;

  document.getElementById('submit-btn').textContent = 'Update';
  document.getElementById('cancel-btn').style.display = '';
  document.getElementById('expense-card').classList.add('editing');
  document.getElementById('expense-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function cancelEdit() {
  editingId = null;
  document.getElementById('submit-btn').textContent   = 'Add';
  document.getElementById('cancel-btn').style.display = 'none';
  document.getElementById('expense-card').classList.remove('editing');
  document.getElementById('f-amount').value = '';
  document.getElementById('f-desc').value   = '';
  setDefaultDate();
  selectedIds.clear();
  updateSelectionUI();
  renderExpensesTable(allExpenses);
}

async function deleteSelected() {
  if (!selectedIds.size) return;
  const count = selectedIds.size;
  const ok    = await askConfirm(`Delete ${count} expense${count > 1 ? 's' : ''}? This cannot be undone.`);
  if (!ok) return;

  await Promise.all([...selectedIds].map(id =>
    fetch(`/api/expense/${id}`, { method: 'DELETE' })
  ));
  showToast(`Deleted ${count} expense${count > 1 ? 's' : ''}`);
  selectedIds.clear();
  expPage = 1;
  await Promise.all([loadSummary(), loadExpenses()]);
}

// ── Budget tab ────────────────────────────────────────────────────────────────
function renderBudgetTab(data) {
  const grid = document.getElementById('budget-grid');

  const expCats    = new Set(data.by_category.map(c => c.category));
  const budgetCats = new Set(Object.keys(data.budgets));
  const allCats    = [...new Set([...categories, ...expCats, ...budgetCats])];

  const spendMap = {};
  for (const c of data.by_category) spendMap[c.category] = c.total;

  let html = `<table class="budget-table">
    <thead><tr>
      <th style="text-align:left;padding:.5rem .75rem;font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted)">Category</th>
      <th style="text-align:right;padding:.5rem .75rem;font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted)">Monthly Limit (${CURRENCY})</th>
      <th style="text-align:right;padding:.5rem .75rem;font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted)">Spent This Month</th>
      <th style="padding:.5rem .75rem;font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted)">Progress</th>
    </tr></thead><tbody>`;

  for (const cat of allCats) {
    const limit  = data.budgets[cat] || 0;
    const spent  = spendMap[cat] || 0;
    const pct    = limit > 0 ? Math.min(100, (spent / limit) * 100) : 0;
    const cls    = pct >= 100 ? 'over' : pct >= 80 ? 'warn' : 'ok';
    const dot    = getCategoryColor(cat);

    html += `<tr class="budget-row budget-input-row" data-category="${escAttr(cat)}">
      <td>
        <div style="display:flex;align-items:center;gap:.5rem">
          <div style="width:9px;height:9px;border-radius:50%;background:${dot};flex-shrink:0"></div>
          <span style="font-weight:500;font-size:.875rem">${escHtml(cat)}</span>
        </div>
      </td>
      <td style="text-align:right">
        <input type="number" class="budget-limit-input"
               value="${limit > 0 ? limit : ''}"
               placeholder="No limit" min="0" step="0.01"
               style="width:110px;padding:.3rem .5rem;border:1px solid var(--border);border-radius:4px;font-size:.83rem;text-align:right;background:var(--input-bg);color:var(--text);outline:none;font-family:inherit">
      </td>
      <td style="text-align:right;font-size:.875rem;color:${spent > 0 ? 'var(--text)' : 'var(--text-faint)'}">${spent > 0 ? fmt(spent) : '—'}</td>
      <td style="min-width:150px">
        ${limit > 0 ? `
          <div class="progress-wrap">
            <div class="progress-bar">
              <div class="progress-fill ${cls}" style="width:${pct.toFixed(1)}%"></div>
            </div>
            <span style="font-size:.72rem;font-weight:600;min-width:36px;text-align:right;color:${cls === 'over' ? '#ef4444' : cls === 'warn' ? '#f59e0b' : '#10b981'}">${Math.round(pct)}%</span>
          </div>
        ` : `<span style="font-size:.75rem;color:var(--text-faint)">—</span>`}
      </td>
    </tr>`;
  }

  html += '</tbody></table>';
  grid.innerHTML = html;
}

async function saveAllBudgets() {
  const rows = document.querySelectorAll('.budget-input-row');
  const ops  = [];
  for (const row of rows) {
    const cat = row.dataset.category;
    const inp = row.querySelector('.budget-limit-input');
    const val = parseFloat(inp.value);
    if (inp.value === '' || val === 0 || isNaN(val)) {
      ops.push(fetch(`/api/budget/${encodeURIComponent(cat)}`, { method: 'DELETE' }));
    } else if (val > 0) {
      ops.push(fetch('/api/budget', {
        method:  'PUT',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ category: cat, monthly_limit: val }),
      }));
    }
  }
  await Promise.all(ops);
  showToast('Budgets saved');
  const statusEl = document.getElementById('budget-status');
  statusEl.style.display = 'inline';
  setTimeout(() => { statusEl.style.display = 'none'; }, 2000);
  await loadSummary();
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function switchTab(name) {
  const tabs = ['dashboard', 'expenses', 'budget', 'settings', 'data'];
  for (const t of tabs) {
    const el  = document.getElementById(`tab-${t}`);
    const btn = document.querySelector(`.tab-btn[data-tab="${t}"]`);
    if (el)  el.style.display = t === name ? '' : 'none';
    if (btn) btn.classList.toggle('active', t === name);
  }
  if (name === 'dashboard' && summaryData) {
    requestAnimationFrame(() => {
      renderCategoryChart(summaryData);
      renderMonthlyChart(summaryData);
    });
  }
  if (name === 'budget' && summaryData) {
    renderBudgetTab(summaryData);
  }
  if (name === 'settings') {
    renderCategoryChips();
    loadMerchantRules();
  }
}

// ── Expense log toggle ────────────────────────────────────────────────────────
function toggleExpenseLog() {
  const body = document.getElementById('exp-log-body');
  const icon = document.getElementById('exp-log-icon');
  const lbl  = document.getElementById('exp-log-lbl');
  const open = body.classList.toggle('open');
  icon.textContent = open ? '▼' : '▶';
  lbl.textContent  = open ? 'Hide' : 'Show';
}

// ── Header menu ───────────────────────────────────────────────────────────────
function toggleMenu(e) {
  e.stopPropagation();
  document.getElementById('app-menu').classList.toggle('open');
}
function closeMenu() {
  document.getElementById('app-menu').classList.remove('open');
}
document.addEventListener('click', closeMenu);

// ── Export / Import ───────────────────────────────────────────────────────────
function doExport() {
  window.location.href = '/api/export';
}

async function importFromCSV(input) {
  const file = input.files[0];
  if (!file) return;
  input.value = '';

  const form = new FormData();
  form.append('file', file);

  setSpinner(true);
  try {
    const res  = await fetch('/api/import', { method: 'POST', body: form });
    const data = await res.json();
    if (data.error) { showToast(data.error, 'error'); return; }

    let msg = `Imported ${data.added} expense${data.added !== 1 ? 's' : ''}`;
    if (data.errors.length) msg += ` (${data.errors.length} row${data.errors.length !== 1 ? 's' : ''} skipped)`;
    showToast(msg);
    if (data.errors.length) console.warn('Import errors:', data.errors);

    expPage = 1;
    await Promise.all([loadCategories(), loadSummary(), loadExpenses()]);
  } finally {
    setSpinner(false);
  }
}

// ── Statement upload & review ─────────────────────────────────────────────────
async function uploadStatement(input) {
  const file = input.files[0];
  if (!file) return;
  input.value = '';

  const form = new FormData();
  form.append('file', file);

  setSpinner(true);
  try {
    const res  = await fetch('/api/parse-statement', { method: 'POST', body: form });
    const data = await res.json();
    if (data.error) { showToast(data.error, 'error'); return; }
    openStatementModal(data.transactions);
  } finally {
    setSpinner(false);
  }
}

function openStatementModal(transactions) {
  stmtRows = transactions.map((t, i) => ({ ...t, _id: i, included: true, _origCategory: t.category }));
  renderStmtModal();
  document.getElementById('stmt-overlay').style.display = 'flex';
}

function renderStmtModal() {
  const included = stmtRows.filter(r => r.included).length;
  document.getElementById('stmt-count').textContent = stmtRows.length
    ? `${stmtRows.length} transaction${stmtRows.length !== 1 ? 's' : ''} found — review and edit before saving`
    : 'No transactions found';
  const saveBtn = document.getElementById('stmt-save-btn');
  saveBtn.textContent = `Save ${included} Expense${included !== 1 ? 's' : ''}`;
  saveBtn.disabled    = included === 0;

  const wrap = document.getElementById('stmt-table-wrap');
  if (!stmtRows.length) {
    wrap.innerHTML = `<div class="stmt-empty">
      No transactions could be parsed from this PDF.<br>
      The statement format may not be recognised — try downloading a CSV from your bank portal and using <strong>Import from CSV</strong> instead.
    </div>`;
    return;
  }

  let html = `<table class="stmt-table">
    <thead><tr>
      <th class="chk"><input type="checkbox" id="stmt-chk-all" onchange="toggleAllStmt(this.checked)"></th>
      <th>Date</th>
      <th style="width:100%">Description</th>
      <th style="text-align:right">Amount (S$)</th>
      <th>Category</th>
      <th></th>
    </tr></thead><tbody>`;

  for (const row of stmtRows) {
    const ex = !row.included;
    const catOpts = categories.map(c =>
      `<option value="${escAttr(c)}"${c === row.category ? ' selected' : ''}>${escHtml(c)}</option>`
    ).join('');
    html += `
    <tr class="stmt-row${ex ? ' stmt-excl' : ''}" data-sid="${row._id}">
      <td class="chk">
        <input type="checkbox" ${row.included ? 'checked' : ''}
          onchange="toggleStmtRow(${row._id},this.checked)">
      </td>
      <td>
        <input type="date" class="stmt-input stmt-date" value="${escAttr(row.date)}"
          onchange="updateStmtRow(${row._id},'date',this.value)" ${ex ? 'disabled' : ''}>
      </td>
      <td>
        <input type="text" class="stmt-input stmt-desc" value="${escAttr(row.description)}"
          oninput="updateStmtRow(${row._id},'description',this.value)" ${ex ? 'disabled' : ''}>
      </td>
      <td style="text-align:right">
        <input type="number" class="stmt-input stmt-amount" value="${row.amount}"
          min="0.01" step="0.01"
          onchange="updateStmtRow(${row._id},'amount',parseFloat(this.value)||0)" ${ex ? 'disabled' : ''}>
      </td>
      <td>
        <select class="stmt-input stmt-cat"
          onchange="updateStmtRow(${row._id},'category',this.value)" ${ex ? 'disabled' : ''}>
          ${catOpts}
        </select>
      </td>
      <td>
        <button class="btn btn-del" onclick="removeStmtRow(${row._id})"
          style="padding:.18rem .4rem;font-size:.68rem;line-height:1.4">&#x2715;</button>
      </td>
    </tr>`;
  }
  html += '</tbody></table>';
  wrap.innerHTML = html;

  const allIn  = stmtRows.every(r => r.included);
  const someIn = stmtRows.some(r => r.included);
  const chkAll = document.getElementById('stmt-chk-all');
  if (chkAll) { chkAll.checked = allIn; chkAll.indeterminate = !allIn && someIn; }
}

function updateStmtRow(id, field, value) {
  const row = stmtRows.find(r => r._id === id);
  if (row) row[field] = value;
  const included = stmtRows.filter(r => r.included).length;
  const saveBtn  = document.getElementById('stmt-save-btn');
  if (saveBtn) { saveBtn.textContent = `Save ${included} Expense${included !== 1 ? 's' : ''}`; saveBtn.disabled = included === 0; }
}

function toggleStmtRow(id, checked) {
  const row = stmtRows.find(r => r._id === id);
  if (!row) return;
  row.included = checked;
  const tr = document.querySelector(`.stmt-row[data-sid="${id}"]`);
  if (tr) {
    tr.classList.toggle('stmt-excl', !checked);
    tr.querySelectorAll('.stmt-input').forEach(el => { el.disabled = !checked; });
  }
  const included = stmtRows.filter(r => r.included).length;
  const saveBtn  = document.getElementById('stmt-save-btn');
  if (saveBtn) { saveBtn.textContent = `Save ${included} Expense${included !== 1 ? 's' : ''}`; saveBtn.disabled = included === 0; }
  const allIn  = stmtRows.every(r => r.included);
  const someIn = stmtRows.some(r => r.included);
  const chkAll = document.getElementById('stmt-chk-all');
  if (chkAll) { chkAll.checked = allIn; chkAll.indeterminate = !allIn && someIn; }
}

function toggleAllStmt(checked) {
  stmtRows.forEach(r => { r.included = checked; });
  renderStmtModal();
}

function removeStmtRow(id) {
  stmtRows = stmtRows.filter(r => r._id !== id);
  renderStmtModal();
}

function closeStatementModal() {
  document.getElementById('stmt-overlay').style.display = 'none';
  stmtRows = [];
}

async function saveStatementRows() {
  const toSave = stmtRows.filter(r => r.included);
  if (!toSave.length) return;

  const invalid = toSave.filter(r => !r.date || !r.amount || r.amount <= 0);
  if (invalid.length) {
    showToast(`${invalid.length} row${invalid.length > 1 ? 's have' : ' has'} a missing date or invalid amount`, 'error');
    return;
  }

  setSpinner(true);
  try {
    const results = await Promise.all(toSave.map(row =>
      fetch('/api/expense', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ date: row.date, amount: row.amount, category: row.category, description: row.description }),
      }).then(r => r.json())
    ));
    const saved  = results.filter(r => r.success).length;
    const failed = results.length - saved;

    // Auto-save merchant rules for any rows where the user changed the category
    const changedRules = toSave.filter(r => r.category !== r._origCategory);
    if (changedRules.length) {
      await Promise.all(changedRules.map(r =>
        fetch('/api/merchant-rule', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ pattern: r.description.toLowerCase().trim(), category: r.category }),
        })
      ));
    }

    closeStatementModal();
    showToast(`Saved ${saved} expense${saved !== 1 ? 's' : ''}${failed ? ` (${failed} failed)` : ''}${changedRules.length ? ` · ${changedRules.length} rule${changedRules.length !== 1 ? 's' : ''} learned` : ''}`);
    expPage = 1;
    await Promise.all([loadSummary(), loadExpenses()]);
  } finally {
    setSpinner(false);
  }
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.getElementById('stmt-overlay').style.display !== 'none') {
    closeStatementModal();
  }
});

// ── Merchant rules ────────────────────────────────────────────────────────────
// ── Category management ───────────────────────────────────────────────────────
function renderCategoryChips() {
  const wrap = document.getElementById('category-chips');
  if (!wrap) return;
  wrap.innerHTML = categories.map(c => {
    const color = getCategoryColor(c);
    return `<span style="display:inline-flex;align-items:center;gap:.3rem;padding:.3rem .65rem;border-radius:999px;font-size:.78rem;font-weight:600;background:${color}1a;color:${color};border:1px solid ${color}40">
      ${escHtml(c)}
      <button onclick="deleteCategory(${JSON.stringify(c)})" title="Remove"
        style="background:none;border:none;cursor:pointer;color:${color};opacity:.6;font-size:.85rem;line-height:1;padding:0 0 0 .1rem">&times;</button>
    </span>`;
  }).join('');
}

async function addCategory() {
  const input = document.getElementById('new-category-name');
  const name  = input.value.trim();
  if (!name) { showToast('Enter a category name', 'error'); return; }
  const res  = await fetch('/api/categories', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ name }),
  });
  const data = await res.json();
  if (data.error) { showToast(data.error, 'error'); return; }
  input.value = '';
  await loadCategories();
  renderCategoryChips();
  showToast(`"${name}" added`);
}

async function deleteCategory(name) {
  const confirmed = await askConfirm(`Remove category "${name}"? Existing expenses in this category won't be deleted.`);
  if (!confirmed) return;
  await fetch(`/api/categories/${encodeURIComponent(name)}`, { method: 'DELETE' });
  await loadCategories();
  renderCategoryChips();
  showToast(`"${name}" removed`);
}

async function loadMerchantRules() {
  // Populate category select
  const sel = document.getElementById('rule-category');
  if (sel) {
    sel.innerHTML = categories.map(c => `<option value="${escAttr(c)}">${escHtml(c)}</option>`).join('');
  }
  const res   = await fetch('/api/merchant-rules');
  const rules = await res.json();
  renderMerchantRules(rules);
}

function renderMerchantRules(rules) {
  const wrap = document.getElementById('merchant-rules-wrap');
  if (!wrap) return;
  if (!rules.length) {
    wrap.innerHTML = '<div class="empty" style="padding:1.5rem 0">No rules saved yet.</div>';
    return;
  }
  let html = `<table style="width:100%;border-collapse:collapse;font-size:.83rem">
    <thead><tr style="background:var(--bg-subtle)">
      <th style="text-align:left;padding:.45rem .75rem;font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);border-bottom:1px solid var(--border)">Pattern (contains)</th>
      <th style="text-align:left;padding:.45rem .75rem;font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);border-bottom:1px solid var(--border)">Assigned Category</th>
      <th style="padding:.45rem .75rem;border-bottom:1px solid var(--border)"></th>
    </tr></thead><tbody>`;
  for (const r of rules) {
    const color = getCategoryColor(r.category);
    html += `<tr style="border-bottom:1px solid var(--border-subtle)">
      <td style="padding:.5rem .75rem;font-family:monospace;font-size:.8rem;color:var(--text)">${escHtml(r.pattern)}</td>
      <td style="padding:.5rem .75rem">
        <span class="cat-chip" style="background:${color}1a;color:${color};border-color:${color}40">${escHtml(r.category)}</span>
      </td>
      <td style="padding:.5rem .75rem;text-align:right">
        <button class="btn btn-del" onclick="deleteMerchantRule(${JSON.stringify(r.pattern)})"
          style="padding:.18rem .4rem;font-size:.68rem">Remove</button>
      </td>
    </tr>`;
  }
  html += '</tbody></table>';
  wrap.innerHTML = html;
}

async function addMerchantRule() {
  const pattern  = document.getElementById('rule-pattern').value.trim().toLowerCase();
  const category = document.getElementById('rule-category').value;
  if (!pattern) { showToast('Enter a keyword or merchant name', 'error'); return; }
  const res  = await fetch('/api/merchant-rule', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ pattern, category }),
  });
  const data = await res.json();
  if (data.error) { showToast(data.error, 'error'); return; }
  document.getElementById('rule-pattern').value = '';
  showToast('Rule saved');
  await loadMerchantRules();
}

async function deleteMerchantRule(pattern) {
  await fetch(`/api/merchant-rule/${encodeURIComponent(pattern)}`, { method: 'DELETE' });
  showToast('Rule removed');
  await loadMerchantRules();
}

// ── Dark mode ─────────────────────────────────────────────────────────────────
function loadDarkMode() {
  const on = localStorage.getItem('expense_darkmode') === '1';
  document.body.classList.toggle('dark', on);
  const cb = document.getElementById('dark-mode-toggle');
  if (cb) cb.checked = on;
}

function toggleDarkMode(on) {
  document.body.classList.toggle('dark', on);
  localStorage.setItem('expense_darkmode', on ? '1' : '0');
  if (summaryData) {
    renderCategoryChart(summaryData);
    renderMonthlyChart(summaryData);
  }
}

// ── Spinner ───────────────────────────────────────────────────────────────────
function setSpinner(on) {
  document.getElementById('spinner').classList.toggle('active', on);
}

// ── Toast ─────────────────────────────────────────────────────────────────────
let _toastTimer = null;
function showToast(msg, type) {
  const el = document.getElementById('toast');
  el.textContent   = msg;
  el.style.background = type === 'error' ? '#dc2626' : '';
  el.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('show'), 2500);
}

// ── Confirm dialog ────────────────────────────────────────────────────────────
function askConfirm(msg) {
  return new Promise(resolve => {
    confirmResolve = resolve;
    document.getElementById('confirm-msg').textContent = msg;
    document.getElementById('confirm-overlay').style.display = 'flex';
  });
}

function resolveConfirm(val) {
  document.getElementById('confirm-overlay').style.display = 'none';
  if (confirmResolve) { confirmResolve(val); confirmResolve = null; }
}

// ── Canvas: Donut chart ───────────────────────────────────────────────────────
function drawDonut(canvas, segments) {
  const dpr  = window.devicePixelRatio || 1;
  const size = canvas.offsetWidth || 200;
  canvas.width  = size * dpr;
  canvas.height = size * dpr;

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const cx  = size / 2, cy = size / 2;
  const R   = size * 0.44;
  const r   = R * 0.58;
  const gap = 0.025;

  const total = segments.reduce((s, x) => s + x.value, 0);
  if (!total) return;

  let angle = -Math.PI / 2;
  for (const seg of segments) {
    const sweep = Math.max(0, (seg.value / total) * 2 * Math.PI - gap);
    if (sweep <= 0) continue;
    ctx.beginPath();
    ctx.arc(cx, cy, R, angle + gap / 2, angle + sweep + gap / 2);
    ctx.arc(cx, cy, r, angle + sweep + gap / 2, angle + gap / 2, true);
    ctx.closePath();
    ctx.fillStyle = seg.color;
    ctx.fill();
    angle += sweep + gap;
  }
}

// ── Canvas: Bar chart ─────────────────────────────────────────────────────────
function drawBarChart(canvas, data) {
  const dpr    = window.devicePixelRatio || 1;
  const W      = canvas.offsetWidth || canvas.parentElement?.offsetWidth || 600;
  const H      = 200;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const isDark   = document.body.classList.contains('dark');
  const gridCol  = isDark ? 'rgba(255,255,255,.07)' : 'rgba(0,0,0,.06)';
  const textCol  = isDark ? '#64748b' : '#94a3b8';
  const barColor = '#3b82f6';
  const curColor = '#1d4ed8';

  const pad = { top: 16, right: 10, bottom: 40, left: 58 };
  const cW  = W - pad.left - pad.right;
  const cH  = H - pad.top  - pad.bottom;

  const maxVal  = Math.max(...data.map(d => d.total), 1);
  const niceTop = niceMax(maxVal);
  const ticks   = 4;
  const step    = cW / data.length;
  const bw      = Math.max(6, step * 0.55);

  ctx.font = `10px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif`;

  // Grid + Y-axis labels
  for (let i = 0; i <= ticks; i++) {
    const y   = pad.top + cH - (i / ticks) * cH;
    const val = (i / ticks) * niceTop;
    ctx.strokeStyle = gridCol;
    ctx.lineWidth   = 0.5;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + cW, y); ctx.stroke();
    ctx.fillStyle  = textCol;
    ctx.textAlign  = 'right';
    ctx.fillText(fmtK(val), pad.left - 6, y + 3.5);
  }

  // Bars and labels
  data.forEach((d, i) => {
    const barH   = Math.max((d.total / niceTop) * cH, d.total > 0 ? 2 : 0);
    const x      = pad.left + i * step + step / 2 - bw / 2;
    const y      = pad.top + cH - barH;
    const isCur  = d.month === currentMonth;

    ctx.fillStyle = isCur ? curColor : barColor;
    ctx.beginPath();
    if (ctx.roundRect) {
      ctx.roundRect(x, y, bw, barH, [3, 3, 0, 0]);
    } else {
      ctx.rect(x, y, bw, barH);
    }
    ctx.fill();

    // Month label
    const date  = new Date(d.month + '-01');
    const label = date.toLocaleString('default', { month: 'short' });
    ctx.textAlign  = 'center';
    ctx.fillStyle  = isCur ? (isDark ? '#e2e8f0' : '#334155') : textCol;
    ctx.font = isCur
      ? `bold 10px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif`
      : `10px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif`;
    ctx.fillText(label, pad.left + i * step + step / 2, pad.top + cH + 16);

    // Year label (Jan or first bar)
    if (d.month.endsWith('-01') || i === 0) {
      ctx.font      = `9px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif`;
      ctx.fillStyle = textCol;
      ctx.fillText(d.month.slice(0, 4), pad.left + i * step + step / 2, pad.top + cH + 29);
    }
  });
}

function niceMax(v) {
  if (v <= 0) return 100;
  const exp  = Math.floor(Math.log10(v));
  const pow  = Math.pow(10, exp);
  const frac = v / pow;
  const ceil = frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 5 ? 5 : 10;
  return ceil * pow * 1.15;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(n) {
  if (n == null || isNaN(n)) return '—';
  return CURRENCY + Number(n).toLocaleString('en-SG', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtK(n) {
  if (n >= 10000) return (n / 1000).toFixed(0) + 'k';
  if (n >= 1000)  return (n / 1000).toFixed(1) + 'k';
  return Math.round(n).toString();
}

function escHtml(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function escAttr(s) {
  return String(s || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function getCategoryColor(cat) {
  if (CATEGORY_COLORS[cat]) return CATEGORY_COLORS[cat];
  let h = 0;
  for (let i = 0; i < cat.length; i++) h = cat.charCodeAt(i) + ((h << 5) - h);
  return `hsl(${Math.abs(h) % 360}, 55%, 50%)`;
}
