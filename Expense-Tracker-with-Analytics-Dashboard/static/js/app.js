/* ── SpendLens Dashboard JS ── */

// ── State ──
let categories = [];
let incomeSources = [];
let editingExpenseId = null;
let currentExpensePage = 1;
let currentIncomePage = 1;
let searchTimer = null;
let pieChart = null, barChart = null, pieChart2 = null, barChart2 = null;
let isLightMode = localStorage.getItem('spendlens-theme') === 'light';

const CAT_COLORS = {
  Food: '#F59E0B', Transport: '#3B82F6', Housing: '#8B5CF6',
  Utilities: '#06B6D4', Entertainment: '#EC4899', Health: '#10B981',
  Shopping: '#F97316', Education: '#6366F1', Travel: '#14B8A6', Other: '#6B7280',
  Salary: '#10B981', Freelance: '#3B82F6', Investment: '#8B5CF6',
  Gift: '#EC4899', Rental: '#F59E0B', Business: '#F97316',
};

const fmt = (n) => '₹' + Number(n).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2});

// ── Init ──
document.addEventListener('DOMContentLoaded', async () => {
  applyTheme();

  // Set username avatar
  const uname = document.getElementById('user-name').textContent.trim();
  document.getElementById('user-avatar').textContent = uname.charAt(0).toUpperCase();

  // Set today as default dates
  const today = new Date().toISOString().split('T')[0];
  document.getElementById('exp-date').value = today;
  document.getElementById('inc-date').value = today;

  // Load categories
  const [cats, srcs] = await Promise.all([
    api('/api/categories'), api('/api/income/sources')
  ]);
  categories = cats;
  incomeSources = srcs;
  populateSelects();

  // Load initial data
  await Promise.all([loadSummary(), loadDashboardCharts(), loadExpenses(1)]);
});

function populateSelects() {
  // Expense category
  const cs = document.getElementById('cat-filter');
  const expCat = document.getElementById('exp-category');
  const budCat = document.getElementById('bud-category');
  categories.forEach(c => {
    cs.innerHTML += `<option value="${c}">${c}</option>`;
    expCat.innerHTML += `<option value="${c}">${c}</option>`;
    budCat.innerHTML += `<option value="${c}">${c}</option>`;
  });

  // Income sources
  const incSrc = document.getElementById('inc-source');
  incomeSources.forEach(s => {
    incSrc.innerHTML += `<option value="${s}">${s}</option>`;
  });
}

// ── API helper ──
async function api(url, method = 'GET', body = null) {
  const opts = { method, headers: {} };
  if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const res = await fetch(url, opts);
  if (res.status === 401) { window.location = '/login'; return; }
  try { return await res.json(); } catch { return {}; }
}

// ── Theme ──
function applyTheme() {
  document.body.classList.toggle('light-mode', isLightMode);
  document.getElementById('theme-btn').textContent = isLightMode ? '☀️' : '🌙';
}

function toggleTheme() {
  isLightMode = !isLightMode;
  localStorage.setItem('spendlens-theme', isLightMode ? 'light' : 'dark');
  applyTheme();
}

// ── Sidebar / mobile ──
function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
}

// ── Panel navigation ──
const panelTitles = {
  dashboard: 'Dashboard', expenses: 'Expenses', income: 'Income',
  analytics: 'Analytics', trends: 'Trends', budgets: 'Budgets', recurring: 'Recurring'
};

function showPanel(name, btn) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
  document.getElementById(`panel-${name}`).classList.add('active');
  if (btn) btn.classList.add('active');
  document.getElementById('topbar-title').textContent = panelTitles[name] || name;

  // Close sidebar on mobile
  document.getElementById('sidebar').classList.remove('open');

  // Lazy-load panel data
  if (name === 'analytics') loadAnalytics();
  if (name === 'trends') loadTrends();
  if (name === 'budgets') loadBudgets();
  if (name === 'recurring') loadRecurring();
  if (name === 'income') loadIncome(1);
}

// ── Toast ──
function toast(msg, type = 'success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'show ' + type;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.className = ''; }, 3000);
}

// ── Summary cards ──
async function loadSummary() {
  const d = await api('/api/analytics/summary');
  animateValue('s-month', d.current_month_expense);
  animateValue('s-total', d.total_spent);
  animateValue('s-avg', d.average_expense);
  animateValue('s-savings', d.net_savings);

  document.getElementById('s-count').textContent = `${d.expense_count} entries total`;
  document.getElementById('s-topcat').textContent = d.top_category ? `Top: ${d.top_category}` : '';

  const savingsEl = document.getElementById('s-savings');
  const card = document.getElementById('s-savings-card');
  card.classList.toggle('positive', d.net_savings > 0);
  card.classList.toggle('negative', d.net_savings < 0);
}

function animateValue(id, val) {
  const el = document.getElementById(id);
  el.style.opacity = '0.4';
  el.style.transform = 'translateY(4px)';
  setTimeout(() => {
    el.textContent = fmt(val);
    el.style.opacity = '1';
    el.style.transform = 'translateY(0)';
  }, 120);
}

// ── Dashboard charts ──
async function loadDashboardCharts() {
  const [catData, monthData] = await Promise.all([
    api('/api/analytics/by-category'),
    api('/api/analytics/by-month'),
  ]);
  renderPieChart('chart-pie', catData, 'pie');
  renderBarChart('chart-bar', monthData, 'bar');
}

const chartDefaults = {
  responsive: true, maintainAspectRatio: false,
  plugins: { legend: { labels: { color: '#94A3B8', font: { family: 'Inter', size: 12 }, boxWidth: 14 } } },
};

function renderPieChart(canvasId, data, ref) {
  const ctx = document.getElementById(canvasId).getContext('2d');
  if (ref === 'pie' && pieChart) pieChart.destroy();
  if (ref === 'pie2' && pieChart2) pieChart2.destroy();

  const chart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: data.map(d => d.category),
      datasets: [{
        data: data.map(d => d.total),
        backgroundColor: data.map(d => CAT_COLORS[d.category] || '#6B7280'),
        borderWidth: 0,
        hoverOffset: 6,
      }]
    },
    options: {
      ...chartDefaults,
      cutout: '65%',
      plugins: {
        ...chartDefaults.plugins,
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.label}: ${fmt(ctx.parsed)}`
          }
        }
      }
    }
  });

  if (ref === 'pie') pieChart = chart;
  else pieChart2 = chart;
}

function renderBarChart(canvasId, data, ref) {
  const ctx = document.getElementById(canvasId).getContext('2d');
  if (ref === 'bar' && barChart) barChart.destroy();
  if (ref === 'bar2' && barChart2) barChart2.destroy();

  const hasIncome = data.some(d => d.income !== undefined);

  const datasets = [{
    label: 'Expenses',
    data: data.map(d => d.expenses ?? d.total),
    backgroundColor: 'rgba(99,102,241,0.7)',
    borderRadius: 4,
  }];

  if (hasIncome) {
    datasets.push({
      label: 'Income',
      data: data.map(d => d.income ?? 0),
      backgroundColor: 'rgba(16,185,129,0.7)',
      borderRadius: 4,
    });
  }

  const chart = new Chart(ctx, {
    type: 'bar',
    data: { labels: data.map(d => d.month ?? d.label), datasets },
    options: {
      ...chartDefaults,
      scales: {
        x: { ticks: { color: '#94A3B8', font: { family: 'DM Mono', size: 11 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
        y: { ticks: { color: '#94A3B8', callback: v => '₹' + v, font: { family: 'DM Mono', size: 11 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
      },
      plugins: {
        ...chartDefaults.plugins,
        tooltip: { callbacks: { label: ctx => ` ${ctx.dataset.label}: ${fmt(ctx.parsed.y)}` } }
      }
    }
  });

  if (ref === 'bar') barChart = chart;
  else barChart2 = chart;
}

// ── Expense list ──
function debouncedSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadExpenses(1), 300);
}

function clearDates() {
  document.getElementById('start-date').value = '';
  document.getElementById('end-date').value = '';
  loadExpenses(1);
}

function buildExpenseQueryParams(page) {
  const params = new URLSearchParams();
  params.set('page', page);
  params.set('per_page', 20);

  const cat = document.getElementById('cat-filter').value;
  if (cat !== 'all') params.set('category', cat);

  const search = document.getElementById('search-input').value.trim();
  if (search) params.set('search', search);

  const startDate = document.getElementById('start-date').value;
  const endDate = document.getElementById('end-date').value;
  if (startDate) params.set('start_date', startDate);
  if (endDate) params.set('end_date', endDate);

  const [sort_by, sort_dir] = (document.getElementById('sort-select').value || 'date-desc').split('-');
  params.set('sort_by', sort_by);
  params.set('sort_dir', sort_dir);

  return params;
}

async function loadExpenses(page = 1) {
  currentExpensePage = page;
  const params = buildExpenseQueryParams(page);
  const data = await api('/api/expenses?' + params.toString());
  if (!data) return;

  const list = document.getElementById('expense-list');
  const label = document.getElementById('expense-count-label');
  label.textContent = `${data.total} expense${data.total !== 1 ? 's' : ''} found`;

  if (!data.expenses.length) {
    list.innerHTML = `<div class="empty-state"><div class="empty-icon">↑</div><div class="empty-text">No expenses match your filters.</div></div>`;
    document.getElementById('pagination').innerHTML = '';
    return;
  }

  list.innerHTML = data.expenses.map(e => expenseRowHTML(e)).join('');
  renderPagination('pagination', data.pages, page, p => loadExpenses(p));
}

function expenseRowHTML(e) {
  const catClass = 'cat-' + e.category.toLowerCase();
  return `
    <div class="expense-row" id="exp-row-${e.id}">
      <div class="expense-cat-dot ${catClass}"></div>
      <div class="expense-info">
        <div class="expense-title">${escHtml(e.title)}</div>
        <div class="expense-meta">${e.date} · ${e.category}${e.note ? ' · ' + escHtml(e.note.substring(0,40)) : ''}</div>
      </div>
      ${e.is_recurring ? '<span class="recurring-badge">↺ recurring</span>' : ''}
      <div class="expense-amount">${fmt(e.amount)}</div>
      <div class="expense-actions">
        <button class="icon-btn" onclick="editExpense(${e.id})" title="Edit">✎</button>
        <button class="icon-btn del" onclick="deleteExpense(${e.id})" title="Delete">✕</button>
      </div>
    </div>`;
}

function renderPagination(containerId, totalPages, current, onClick) {
  const el = document.getElementById(containerId);
  if (totalPages <= 1) { el.innerHTML = ''; return; }

  let html = `<button class="page-btn" ${current===1?'disabled':''} onclick="(${onClick.toString()})(${current-1})">‹</button>`;
  for (let p = Math.max(1, current-2); p <= Math.min(totalPages, current+2); p++) {
    html += `<button class="page-btn ${p===current?'active':''}" onclick="(${onClick.toString()})(${p})">${p}</button>`;
  }
  html += `<button class="page-btn" ${current===totalPages?'disabled':''} onclick="(${onClick.toString()})(${current+1})">›</button>`;
  el.innerHTML = html;
}

// ── CSV Export ──
function exportCSV(e) {
  e.preventDefault();
  const params = buildExpenseQueryParams(1);
  params.delete('page'); params.delete('per_page');
  window.location = '/api/expenses/export/csv?' + params.toString();
}

// ── Expense Modal ──
function openExpenseModal(e) {
  editingExpenseId = e ? e.id : null;
  document.getElementById('expense-modal-title').textContent = e ? 'Edit expense' : 'Add expense';
  document.getElementById('exp-title').value = e ? e.title : '';
  document.getElementById('exp-amount').value = e ? e.amount : '';
  document.getElementById('exp-category').value = e ? e.category : 'Food';
  document.getElementById('exp-date').value = e ? e.date : new Date().toISOString().split('T')[0];
  document.getElementById('exp-note').value = e ? (e.note || '') : '';
  document.getElementById('exp-recurring').checked = e ? !!e.is_recurring : false;
  document.getElementById('exp-error').style.display = 'none';
  document.getElementById('expense-modal').classList.add('open');
  document.getElementById('exp-title').focus();
}

function closeExpenseModal() {
  document.getElementById('expense-modal').classList.remove('open');
}

async function editExpense(id) {
  const data = await api(`/api/expenses?page=1&per_page=1`);
  // Fetch single – find in current list
  const row = document.getElementById(`exp-row-${id}`);
  if (!row) return;
  // Re-fetch from API to get full data
  const allData = await api(`/api/expenses?page=1&per_page=999`);
  const exp = (allData.expenses || []).find(e => e.id === id);
  if (exp) openExpenseModal(exp);
}

async function saveExpense() {
  const btn = document.getElementById('exp-save-btn');
  const errEl = document.getElementById('exp-error');
  btn.disabled = true; btn.textContent = 'Saving…';

  const body = {
    title: document.getElementById('exp-title').value,
    amount: document.getElementById('exp-amount').value,
    category: document.getElementById('exp-category').value,
    date: document.getElementById('exp-date').value,
    note: document.getElementById('exp-note').value,
    is_recurring: document.getElementById('exp-recurring').checked,
  };

  const url = editingExpenseId ? `/api/expenses/${editingExpenseId}` : '/api/expenses';
  const method = editingExpenseId ? 'PUT' : 'POST';
  const res = await fetch(url, {
    method,
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body),
  });
  const data = await res.json();

  if (res.ok) {
    closeExpenseModal();
    toast(editingExpenseId ? 'Expense updated' : 'Expense added');
    await Promise.all([loadExpenses(currentExpensePage), loadSummary()]);
    if (pieChart) loadDashboardCharts();
  } else {
    errEl.textContent = data.error;
    errEl.style.display = 'block';
  }

  btn.disabled = false; btn.textContent = 'Save expense';
}

async function deleteExpense(id) {
  if (!confirm('Delete this expense?')) return;
  const res = await fetch(`/api/expenses/${id}`, { method: 'DELETE' });
  if (res.ok) {
    toast('Expense deleted');
    await Promise.all([loadExpenses(currentExpensePage), loadSummary()]);
    if (pieChart) loadDashboardCharts();
  } else {
    toast('Failed to delete', 'error');
  }
}

// ── Income ──
async function loadIncome(page = 1) {
  currentIncomePage = page;
  const params = new URLSearchParams({ page, per_page: 20 });
  const sd = document.getElementById('income-start-date').value;
  const ed = document.getElementById('income-end-date').value;
  if (sd) params.set('start_date', sd);
  if (ed) params.set('end_date', ed);

  const data = await api('/api/income?' + params);
  if (!data) return;

  const list = document.getElementById('income-list');
  if (!data.income.length) {
    list.innerHTML = `<div class="empty-state"><div class="empty-icon">↓</div><div class="empty-text">No income entries yet.</div></div>`;
    document.getElementById('income-pagination').innerHTML = '';
    return;
  }

  list.innerHTML = data.income.map(i => `
    <div class="income-row">
      <div class="expense-cat-dot cat-${i.source.toLowerCase()}"></div>
      <div class="expense-info">
        <div class="expense-title">${escHtml(i.title)}</div>
        <div class="expense-meta">${i.date} · ${i.source}${i.note ? ' · ' + escHtml(i.note.substring(0,40)) : ''}</div>
      </div>
      ${i.is_recurring ? '<span class="recurring-badge">↺ recurring</span>' : ''}
      <div class="income-amount">${fmt(i.amount)}</div>
      <div class="expense-actions">
        <button class="icon-btn del" onclick="deleteIncome(${i.id})" title="Delete">✕</button>
      </div>
    </div>
  `).join('');

  renderPagination('income-pagination', data.pages, page, p => loadIncome(p));
}

function clearIncomeDates() {
  document.getElementById('income-start-date').value = '';
  document.getElementById('income-end-date').value = '';
  loadIncome(1);
}

function openIncomeModal() {
  document.getElementById('inc-title').value = '';
  document.getElementById('inc-amount').value = '';
  document.getElementById('inc-source').value = 'Salary';
  document.getElementById('inc-date').value = new Date().toISOString().split('T')[0];
  document.getElementById('inc-note').value = '';
  document.getElementById('inc-recurring').checked = false;
  document.getElementById('inc-error').style.display = 'none';
  document.getElementById('income-modal').classList.add('open');
}

function closeIncomeModal() {
  document.getElementById('income-modal').classList.remove('open');
}

async function saveIncome() {
  const errEl = document.getElementById('inc-error');
  const body = {
    title: document.getElementById('inc-title').value,
    amount: document.getElementById('inc-amount').value,
    source: document.getElementById('inc-source').value,
    date: document.getElementById('inc-date').value,
    note: document.getElementById('inc-note').value,
    is_recurring: document.getElementById('inc-recurring').checked,
  };

  const res = await fetch('/api/income', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body),
  });
  const data = await res.json();

  if (res.ok) {
    closeIncomeModal();
    toast('Income recorded');
    await Promise.all([loadIncome(currentIncomePage), loadSummary()]);
  } else {
    errEl.textContent = data.error;
    errEl.style.display = 'block';
  }
}

async function deleteIncome(id) {
  if (!confirm('Delete this income entry?')) return;
  const res = await fetch(`/api/income/${id}`, { method: 'DELETE' });
  if (res.ok) {
    toast('Income deleted');
    await Promise.all([loadIncome(currentIncomePage), loadSummary()]);
  }
}

// ── Analytics ──
function clearAnalyticsDates() {
  document.getElementById('analytics-start').value = '';
  document.getElementById('analytics-end').value = '';
  loadAnalytics();
}

async function loadAnalytics() {
  const params = new URLSearchParams();
  const sd = document.getElementById('analytics-start').value;
  const ed = document.getElementById('analytics-end').value;
  if (sd) params.set('start_date', sd);
  if (ed) params.set('end_date', ed);

  const [catData, monthData] = await Promise.all([
    api('/api/analytics/by-category?' + params),
    api('/api/analytics/by-month'),
  ]);

  renderPieChart('chart-pie-2', catData, 'pie2');
  renderBarChart('chart-bar-2', monthData, 'bar2');
}

// ── Trends ──
async function loadTrends() {
  const data = await api('/api/analytics/trends');
  const list = document.getElementById('trends-list');

  if (!data.length) {
    list.innerHTML = `<div class="empty-state"><div class="empty-icon">⟡</div><div class="empty-text">Not enough data for trends yet. Add more expenses!</div></div>`;
    return;
  }

  list.innerHTML = data.map(item => {
    let badge = '';
    let icon = '◦';
    if (item.change_pct === null) {
      badge = `<span class="badge-new">new this month</span>`;
      icon = '✦';
    } else if (item.change_pct > 0) {
      badge = `<span class="badge-up">▲ ${item.change_pct}%</span>`;
      icon = item.change_pct > 30 ? '⚠' : '↑';
    } else {
      badge = `<span class="badge-down">▼ ${Math.abs(item.change_pct)}%</span>`;
      icon = '↓';
    }
    return `
      <div class="insight-card">
        <div class="insight-icon">${icon}</div>
        <div class="insight-text">
          <div class="insight-title">${item.category}</div>
          <div class="insight-sub">${fmt(item.this_month)} this month · ${fmt(item.last_month)} last month</div>
        </div>
        ${badge}
      </div>`;
  }).join('');
}

// ── Budgets ──
function openBudgetModal() {
  document.getElementById('bud-category').value = categories[0] || '';
  document.getElementById('bud-limit').value = '';
  document.getElementById('bud-error').style.display = 'none';
  document.getElementById('budget-modal').classList.add('open');
}
function closeBudgetModal() { document.getElementById('budget-modal').classList.remove('open'); }

async function loadBudgets() {
  const data = await api('/api/budgets');
  const list = document.getElementById('budget-list');
  const empty = document.getElementById('budget-empty');

  if (!data.length) {
    list.innerHTML = '';
    empty.style.display = 'block';
    return;
  }

  empty.style.display = 'none';
  list.innerHTML = data.map(b => {
    const pct = Math.min(b.percent, 100);
    const fillClass = b.percent >= 100 ? 'danger' : b.percent >= 80 ? 'warn' : '';
    return `
      <div class="budget-item">
        <div class="budget-header">
          <div>
            <div class="budget-cat">${b.category}</div>
          </div>
          <div style="display:flex;align-items:center;gap:12px">
            <div class="budget-amounts">${fmt(b.spent)} / ${fmt(b.limit)}</div>
            <button class="icon-btn del" onclick="deleteBudget('${b.category}')" title="Remove">✕</button>
          </div>
        </div>
        <div class="budget-bar-track">
          <div class="budget-bar-fill ${fillClass}" style="width:${pct}%"></div>
        </div>
        <div class="budget-pct">${b.percent}%${b.percent >= 100 ? ' — limit exceeded!' : b.percent >= 80 ? ' — nearing limit' : ''}</div>
      </div>`;
  }).join('');
}

async function saveBudget() {
  const errEl = document.getElementById('bud-error');
  const res = await fetch('/api/budgets', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      category: document.getElementById('bud-category').value,
      limit: document.getElementById('bud-limit').value,
    }),
  });
  const data = await res.json();
  if (res.ok) {
    closeBudgetModal();
    toast('Budget saved');
    loadBudgets();
  } else {
    errEl.textContent = data.error;
    errEl.style.display = 'block';
  }
}

async function deleteBudget(category) {
  if (!confirm(`Remove budget for ${category}?`)) return;
  await fetch(`/api/budgets/${category}`, { method: 'DELETE' });
  toast('Budget removed');
  loadBudgets();
}

// ── Recurring ──
async function loadRecurring() {
  const data = await api('/api/analytics/recurring');

  document.getElementById('rec-exp-total').textContent = fmt(data.monthly_recurring_expense);
  document.getElementById('rec-inc-total').textContent = fmt(data.monthly_recurring_income);

  const expList = document.getElementById('recurring-exp-list');
  if (!data.recurring_expenses.length) {
    expList.innerHTML = `<div class="empty-state" style="padding:30px"><div class="empty-text">No recurring expenses. Mark an expense as recurring to track it here.</div></div>`;
  } else {
    expList.innerHTML = data.recurring_expenses.map(e => expenseRowHTML(e)).join('');
  }

  const incList = document.getElementById('recurring-inc-list');
  if (!data.recurring_income.length) {
    incList.innerHTML = `<div class="empty-state" style="padding:30px"><div class="empty-text">No recurring income entries.</div></div>`;
  } else {
    incList.innerHTML = data.recurring_income.map(i => `
      <div class="income-row">
        <div class="expense-cat-dot cat-${i.source.toLowerCase()}"></div>
        <div class="expense-info">
          <div class="expense-title">${escHtml(i.title)}</div>
          <div class="expense-meta">${i.source}</div>
        </div>
        <span class="recurring-badge">↺ monthly</span>
        <div class="income-amount">${fmt(i.amount)}</div>
      </div>`).join('');
  }
}

// ── Logout ──
async function doLogout() {
  await api('/api/logout', 'POST');
  window.location = '/';
}

// ── Helpers ──
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Close modals on backdrop click
['expense-modal','income-modal','budget-modal'].forEach(id => {
  document.getElementById(id).addEventListener('click', function(e) {
    if (e.target === this) this.classList.remove('open');
  });
});

// Close sidebar when clicking outside on mobile
document.addEventListener('click', e => {
  const sidebar = document.getElementById('sidebar');
  const hamburger = document.getElementById('hamburger');
  if (sidebar.classList.contains('open') && !sidebar.contains(e.target) && !hamburger.contains(e.target)) {
    sidebar.classList.remove('open');
  }
});
