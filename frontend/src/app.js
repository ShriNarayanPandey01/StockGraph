import './wireframe.css';
import './app.css';
import { api, session, escapeHtml as e } from './api.js';
import * as views from './views.js';
import * as agentViews from './agent-views.js';
import { mountStockConnections } from './stock-connections.js';

const root = document.querySelector('#app');
const state = { user: null, query: '', exchange: '', cursor: null, nextCursor: null, window: 'LAST_6M', job: null, candles: [] };
let renderVersion = 0;
let chartCleanup = () => {};
let connectionsCleanup = () => {};
let agentPoll = null;

const navItems = [
  ['dashboard', '01', 'Overview'], ['catalog', '02', 'Explore stocks'], ['watchlists', '03', 'Watchlists'],
  ['alerts', '04', 'Alerts'], ['research', '05', 'Research'], ['discovery', '06', 'Discovery'], ['monitoring', '07', 'Monitoring'], ['contributions', '08', 'Contributions'], ['profile', '09', 'Account & access'],
];

function route() {
  const [raw = 'dashboard', symbol = '', exchange = ''] = location.hash.slice(1).split('/');
  const aliases = { explore: 'catalog', connections: 'catalog', plans: 'profile', chat: 'research', discover: 'discovery', contributor: 'contributions', insights: 'contributions', 'review-queue': 'review', 'user-dashboard': 'dashboard', 'professional-dashboard': 'dashboard', 'admin-dashboard': 'admin' };
  return [aliases[raw] || raw || 'dashboard', decodeURIComponent(symbol), exchange];
}

function toast(message, error = false) {
  const el = root.querySelector('#toast');
  el.textContent = message;
  el.classList.toggle('error-toast', error);
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 6000);
}

function shell() {
  const user = state.user;
  const insightAccess = user.is_developer || user.roles?.some((role) => ['PROFESSIONAL', 'REVIEWER'].includes(role));
  const items = navItems.filter(([id]) => id !== 'profile');
  if (insightAccess) items.push(['review', '09', 'Review insights']);
  items.push(['profile', insightAccess ? '10' : '09', 'Account & access']);
  if (user.is_developer) items.push(['admin', '11', 'Administration']);
  root.innerHTML = `<a class="skip" href="#workspace-main">Skip to workspace</a><header class="app-header"><a class="logo" href="/" aria-label="StockGraph home">StockGraph<span>.</span></a><span class="brand-caption mono">INDIAN EQUITIES / RESEARCH</span><form class="header-search" id="header-search" role="search"><label class="sr" for="header-query">Search stocks</label><input id="header-query" name="query" maxlength="80" placeholder="Search NSE / BSE…"><button type="submit" aria-label="Search stocks">↗</button></form><div class="header-actions"><button class="icon-button theme-toggle" data-action="theme" aria-label="Toggle dark theme">◐</button><button class="pill" data-action="logout">Sign out ↗</button></div></header>
  <div class="app-shell"><aside class="app-sidebar"><div class="sidebar-top mono">RESEARCH WORKSPACE <span>01</span></div><nav aria-label="Workspace"><div class="nav-label">WORKSPACE</div>${items.map(([id, number, label]) => `<a class="nav-link" data-nav="${id}" href="#${id}"><span>${number}</span>${label}</a>`).join('')}</nav><div class="sidebar-bottom"><span class="mono">SIGNED IN AS</span><strong><i></i>${e(user.name)}</strong><p>${e(user.is_developer ? 'Developer' : `${user.plan} plan`)}<br>Research & context</p><a href="#profile">Account & usage ↗</a></div></aside><div class="main-wrap"><div class="workspace-status"><span class="mono">NSE / BSE · SCHEDULED UPDATES</span><span class="mono">RESEARCH & CONTEXT / STOCKGRAPH</span></div><main id="workspace-main" tabindex="-1" aria-live="polite"></main><footer class="app-footer mono"><span>STOCKGRAPH / RESEARCH & CONTEXT</span><span>Relationships are context, not investment advice.</span></footer></div></div><div id="toast" class="toast" role="status" hidden></div>
  <dialog id="edit-dialog" aria-labelledby="edit-title"><form id="edit-list-form"><div class="dialog-top"><span class="eyebrow">WATCHLIST / EDIT</span><button type="button" class="icon-button" data-action="close-dialog" aria-label="Close dialog">×</button></div><h2 id="edit-title">Edit watchlist</h2><input type="hidden" name="id"><label><span>List name</span><input name="name" maxlength="100" required></label><label><span>Tickers, separated by commas</span><input name="tickers"></label><button type="submit" class="btn blue">Save changes ↗</button></form></dialog>
  <dialog id="user-dialog" aria-labelledby="user-dialog-title"><form id="user-form"><div class="dialog-top"><span class="eyebrow">ADMIN / ACCOUNT</span><button type="button" class="icon-button" data-action="close-user-dialog" aria-label="Close dialog">×</button></div><h2 id="user-dialog-title">Edit account</h2><input type="hidden" name="id"><label><span>Name</span><input name="name" maxlength="200" required></label><label><span>Plan</span><select name="plan"><option>FREE</option><option>PRO</option></select></label><label class="checkbox-label"><input type="checkbox" name="professional"> Professional role</label><label class="checkbox-label"><input type="checkbox" name="reviewer"> Reviewer role</label><label class="checkbox-label"><input type="checkbox" name="verified"> Professional verified</label><label class="checkbox-label"><input type="checkbox" name="disabled"> Account disabled</label><button type="submit" class="btn blue">Save account ↗</button><button type="button" class="pill" data-action="revoke-user">Revoke sessions</button></form></dialog>`;
}

async function showPage() {
  const version = ++renderVersion;
  clearTimeout(agentPoll);
  chartCleanup(); chartCleanup = () => {};
  connectionsCleanup(); connectionsCleanup = () => {};
  const [page, ticker, exchange] = route();
  root.querySelectorAll('[data-nav]').forEach((el) => {
    const active = el.dataset.nav === (page === 'stock' ? 'catalog' : page === 'monitor' ? 'monitoring' : page);
    el.classList.toggle('active', active);
    if (active) el.setAttribute('aria-current', 'page'); else el.removeAttribute('aria-current');
  });
  const main = root.querySelector('#workspace-main');
  main.innerHTML = '<div class="page-loading" role="status"><span class="eyebrow">STOCKGRAPH / LOADING</span><h2>Gathering context<span>.</span></h2><p>One moment while we load your workspace.</p></div>';
  try {
    let html, pendingJob = false;
    if (page === 'dashboard') html = await views.dashboard(state);
    else if (page === 'catalog') html = await views.catalog(state);
    else if (page === 'stock' && ticker) html = await views.stock(state, ticker, exchange);
    else if (page === 'watchlists') html = await views.watchlists(state);
    else if (page === 'alerts') html = await views.alerts();
    else if (page === 'research') html = await agentViews.research(ticker);
    else if (page === 'discovery') html = await agentViews.discovery();
    else if (page === 'monitoring') html = await agentViews.monitoring();
    else if (page === 'monitor' && ticker) html = await agentViews.monitorHistory(ticker);
    else if (page === 'agent-job' && ticker) { const view = await agentViews.agentJob(ticker); html = view.html; pendingJob = ['pending', 'running'].includes(view.job.state); }
    else if (page === 'profile') html = await views.profile(state);
    else if (page === 'contributions') html = await views.contributions(state);
    else if (page === 'review') html = await views.reviewInsights(state);
    else if (page === 'contribution' && ticker) html = await views.contribution(ticker);
    else if (page === 'admin' && state.user.is_developer) html = await views.admin();
    else html = views.empty('Page not found', 'Choose a section from the workspace navigation.', '<a class="pill" href="#dashboard">Go to overview ↗</a>');
    if (version !== renderVersion) return;
    main.innerHTML = html;
    if (page === 'stock') connectionsCleanup = mountStockConnections(main.querySelector('#stock-connections'), { ticker, window: state.window });
    if (page === 'stock' && state.candles.length) drawChart(state.candles, version);
    if (pendingJob) agentPoll = setTimeout(() => { if (route()[0] === 'agent-job') showPage(); }, 4000);
  } catch (error) {
    if (version !== renderVersion) return;
    main.innerHTML = `${views.fail(error)}<button class="pill" data-action="retry">Try again ↗</button>`;
  }
}

async function drawChart(candles, version) {
  const target = root.querySelector('#price-chart');
  if (!target) return;
  try {
    const { createChart, CandlestickSeries } = await import('lightweight-charts');
    if (version !== renderVersion || !target.isConnected) return;
    const chart = createChart(target, { height: 300, autoSize: true, layout: { background: { color: 'transparent' }, textColor: '#6d7068', attributionLogo: true }, grid: { vertLines: { color: '#e4e6df' }, horzLines: { color: '#e4e6df' } }, timeScale: { borderVisible: false }, rightPriceScale: { borderVisible: false } });
    const series = chart.addSeries(CandlestickSeries, { upColor: '#315df4', downColor: '#da6e55', borderVisible: false, wickUpColor: '#315df4', wickDownColor: '#da6e55' });
    const points = candles.filter((c) => c.trade_date && [c.open, c.high, c.low, c.close].every(Number.isFinite)).map((c) => ({ time: c.trade_date, open: c.open, high: c.high, low: c.low, close: c.close })).sort((a, b) => a.time.localeCompare(b.time));
    series.setData(points.filter((p, i) => !i || p.time !== points[i - 1].time));
    chart.timeScale().fitContent();
    chartCleanup = () => chart.remove();
  } catch { target.textContent = 'Price chart could not be displayed.'; }
}

function tickers(input) { return [...new Set(input.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean))]; }

async function action(button, operation, success) {
  button.disabled = true;
  try { await operation(); if (success) toast(success); }
  catch (error) {
    const dialog = button.closest('dialog');
    if (dialog?.open) {
      let status = dialog.querySelector('.dialog-error');
      if (!status) { status = document.createElement('p'); status.className = 'dialog-error'; status.setAttribute('role', 'alert'); dialog.querySelector('form').append(status); }
      status.textContent = error.message;
    } else toast(error.message, true);
  }
  finally { if (button.isConnected) button.disabled = false; }
}

root.addEventListener('click', async (event) => {
  if (event.target.closest('a.skip')) { event.preventDefault(); root.querySelector('#workspace-main')?.focus(); return; }
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const { action: type, ticker, id } = button.dataset;
  if (type === 'theme') { document.documentElement.classList.toggle('dark'); localStorage.setItem('stockgraph-theme', document.documentElement.classList.contains('dark') ? 'dark' : 'light'); }
  if (type === 'logout') { await action(button, async () => { try { await api('/auth/logout', { method: 'POST' }); } finally { session.clear(); location.assign('/auth/#signin'); } }); }
  if (type === 'retry') showPage();
  if (type === 'window') { state.window = button.dataset.window; showPage(); }
  if (type === 'catalog-next') { state.cursor = state.nextCursor; showPage(); }
  if (type === 'catalog-first') { state.cursor = null; showPage(); }
  if (type === 'watchlist-mode') { state.watchlistMode = button.dataset.mode; showPage(); }
  if (type === 'toggle-stock') await action(button, async () => { const current = await api('/me/active-stocks'); const next = current.tickers.includes(ticker) ? current.tickers.filter((t) => t !== ticker) : [...current.tickers, ticker]; await api('/me/active-stocks', { method: 'PUT', body: { tickers: next } }); await showPage(); }, 'Stock selection updated.');
  if (type === 'register') await action(button, async () => { state.job = await api('/market/stock-registrations', { method: 'POST', body: { query: ticker, exchange: button.dataset.exchange, strengths: [], business_exclusions: [] } }); await showPage(); }, 'Registration submitted.');
  if (type === 'refresh-job') await action(button, async () => { const jobId = state.job?.job_id || state.job?.id; if (!jobId) throw new Error('No registration job ID was returned.'); state.job = await api(`/market/stock-registrations/${encodeURIComponent(jobId)}`); await showPage(); });
  if (type === 'delete-list' && confirm(`Delete “${button.dataset.name}”?`)) await action(button, async () => { await api(`/watchlists/${encodeURIComponent(id)}`, { method: 'DELETE' }); await showPage(); }, 'Watchlist deleted.');
  if (type === 'edit-list') { const dialog = root.querySelector('#edit-dialog'); const form = dialog.querySelector('form'); form.elements.id.value = id; form.elements.name.value = button.dataset.name; form.elements.tickers.value = button.dataset.tickers; dialog.showModal(); }
  if (type === 'close-dialog') root.querySelector('#edit-dialog').close();
  if (type === 'edit-user') { const dialog = root.querySelector('#user-dialog'); const form = dialog.querySelector('form'); const roles = button.dataset.roles.split(','); form.elements.id.value = id; form.elements.name.value = button.dataset.name; form.elements.plan.value = button.dataset.plan; form.elements.professional.checked = roles.includes('PROFESSIONAL'); form.elements.reviewer.checked = roles.includes('REVIEWER'); form.elements.verified.checked = button.dataset.verified === 'true'; form.elements.disabled.checked = button.dataset.disabled === 'true'; dialog.showModal(); }
  if (type === 'close-user-dialog') root.querySelector('#user-dialog').close();
  if (type === 'revoke-user' && confirm('Revoke all sessions for this account?')) await action(button, async () => { const userId = root.querySelector('#user-form').elements.id.value; await api(`/admin/users/${encodeURIComponent(userId)}/revoke-sessions`, { method: 'POST' }); }, 'Sessions revoked.');
  if (type === 'submit-contribution' && confirm('Submit this draft for review?')) await action(button, async () => { await api(`/contributions/${encodeURIComponent(id)}/submit`, { method: 'POST', body: { expected_revision: Number(button.dataset.revision) } }); await showPage(); }, 'Draft submitted for review.');
  if (type === 'ack-alert') await action(button, async () => { await api(`/alerts/${encodeURIComponent(id)}/acknowledge`, { method: 'POST' }); await showPage(); }, 'Alert marked as read.');
  if (type === 'cancel-agent-job') await action(button, async () => { await api(`/agent-jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }); await showPage(); }, 'Job cancelled.');
  if (type === 'toggle-monitor') await action(button, async () => { await api(`/monitor-rules/${encodeURIComponent(id)}`, { method: 'PATCH', body: { active: button.dataset.active !== 'true' } }); await showPage(); }, 'Monitor updated.');
  if (type === 'delete-monitor' && confirm('Remove this monitor?')) await action(button, async () => { await api(`/monitor-rules/${encodeURIComponent(id)}`, { method: 'DELETE' }); await showPage(); }, 'Monitor removed.');
  if (type === 'disconnect-broker' && confirm('Disconnect your Upstox market-data connection?')) await action(button, async () => { await api('/me/broker-connections/upstox', { method: 'DELETE' }); await showPage(); }, 'Upstox disconnected.');
});

root.addEventListener('submit', async (event) => {
  const form = event.target;
  event.preventDefault();
  const formId = form.getAttribute('id');
  const values = Object.fromEntries(new FormData(form));
  const button = form.querySelector('button[type=submit]');
  if (formId === 'header-search') { state.query = values.query; state.cursor = null; if (route()[0] === 'catalog') showPage(); else location.hash = 'catalog'; }
  if (formId === 'catalog-form') { state.query = values.query; state.exchange = values.exchange; state.cursor = null; showPage(); }
  if (formId === 'watchlist-form') await action(button, async () => { await api('/watchlists', { method: 'POST', body: { name: values.name, tickers: tickers(values.tickers) } }); await showPage(); }, 'Watchlist created.');
  if (formId === 'edit-list-form') await action(button, async () => { await api(`/watchlists/${encodeURIComponent(values.id)}`, { method: 'PUT', body: { name: values.name, tickers: tickers(values.tickers) } }); root.querySelector('#edit-dialog').close(); await showPage(); }, 'Watchlist updated.');
  if (formId === 'monitor-form') await action(button, async () => { await api('/monitor-rules', { method: 'POST', body: { watchlist_id: values.watchlist_id, scope: 'watchlist', question: values.question, interval_seconds: Number(values.interval_seconds) } }); await showPage(); }, 'Monitor saved.');
  if (formId === 'market-monitor-form') await action(button, async () => { await api('/monitor-rules', { method: 'POST', body: { watchlist_id: null, scope: 'market', question: values.question, interval_seconds: 3600 } }); location.hash = 'monitoring'; }, 'Market monitor saved.');
  if (formId === 'research-form' || formId === 'discovery-form') await action(button, async () => {
    const body = { question: values.question, tickers: tickers(values.tickers), window: values.window };
    let conversation = form.dataset.conversation;
    if (formId === 'research-form' && !conversation) {
      const created = await api('/conversations', { method: 'POST', body: { title: values.question.trim().slice(0, 160) } });
      conversation = created.id; form.dataset.conversation = conversation;
    }
    const signature = JSON.stringify({ body, conversation });
    if (form.dataset.signature !== signature) { form.dataset.requestKey = crypto.randomUUID(); form.dataset.signature = signature; }
    const path = formId === 'research-form' ? `/conversations/${encodeURIComponent(conversation)}/messages` : '/discovery/scans';
    const job = await api(path, { method: 'POST', headers: { 'Idempotency-Key': form.dataset.requestKey }, body });
    location.hash = `agent-job/${encodeURIComponent(job.id)}`;
  });
  if (formId === 'contribution-form') await action(button, async () => { form.dataset.key ||= crypto.randomUUID(); await api('/contributions', { method: 'POST', headers: { 'Idempotency-Key': form.dataset.key }, body: { ticker: values.ticker.trim().toUpperCase(), title: values.title, body: values.body, direction: values.direction, horizon: values.horizon, event_at: new Date(values.event_at).toISOString(), expires_at: new Date(values.expires_at).toISOString(), evidence: [{ url: values.source_url, title: values.source_title, locator: values.locator }], disclosures: values.disclosures } }); await showPage(); }, 'Draft saved.');
  if (form.classList.contains('review-form')) { const decision = event.submitter?.value; await action(event.submitter, async () => { await api(`/contributions/${encodeURIComponent(form.dataset.id)}/review`, { method: 'POST', body: { expected_revision: Number(form.dataset.revision), decision, reason: values.reason } }); await showPage(); }, 'Review recorded.'); }
  if (formId === 'user-form') await action(button, async () => { const roles = ['USER', ...(form.elements.professional.checked ? ['PROFESSIONAL'] : []), ...(form.elements.reviewer.checked ? ['REVIEWER'] : [])]; await api(`/admin/users/${encodeURIComponent(values.id)}`, { method: 'PATCH', body: { name: values.name, plan: values.plan, roles, professional_verified: form.elements.verified.checked, disabled: form.elements.disabled.checked } }); root.querySelector('#user-dialog').close(); await showPage(); }, 'Account updated.');
  if (formId === 'broker-form') await action(button, async () => { await api('/me/broker-connections/upstox', { method: 'PUT', body: { access_token: values.access_token } }); await showPage(); }, 'Upstox connection updated.');
  if (formId === 'password-form') await action(button, async () => { const result = await api('/auth/change-password', { method: 'POST', body: values }); session.clear(); sessionStorage.setItem('stockgraph.notice', result.detail || 'Password updated. Please sign in again.'); location.assign('/auth/#signin'); });
});

async function start() {
  if (localStorage.getItem('stockgraph-theme') === 'dark') document.documentElement.classList.add('dark');
  if (!session.get()) { location.replace('/auth/#signin'); return; }
  root.innerHTML = '<main><p>Opening your workspace…</p></main>';
  try {
    const data = await api('/me');
    state.user = data.user;
    state.access = data.access;
    shell();
    addEventListener('hashchange', showPage);
    showPage();
  } catch (error) {
    if (error.status === 401 || error.status === 403) { session.clear(); location.replace('/auth/#signin'); return; }
    root.innerHTML = `<main><a class="logo" href="/">StockGraph<span>.</span></a>${views.fail(error)}<button class="pill" id="retry-start">Try again ↗</button><a class="pill" href="/auth/#signin">Account access</a></main>`;
    root.querySelector('#retry-start').addEventListener('click', start);
  }
}
start();
