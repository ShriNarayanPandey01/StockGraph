import { api, escapeHtml as e, formatDate } from './api.js';

const head = (eyebrow, title, description, action = '') => `<div class="page-head"><div><div class="eyebrow">${eyebrow}</div><h1>${title}<span>.</span></h1><p>${description}</p></div>${action}</div>`;
const section = (title, detail = '') => `<div class="section-head"><h2>${title}</h2>${detail}</div>`;
const empty = (title, description, link = '') => `<div class="empty-state"><span class="empty-symbol" aria-hidden="true">✳</span><h3>${title}</h3><p>${description}</p>${link}</div>`;
const fail = (error) => `<div class="notice error" role="alert"><strong>Unable to load this section.</strong> ${e(error.message)}</div>`;
const value = (result, fallback) => result.status === 'fulfilled' ? result.value : fallback;
const detail = (result, content) => result.status === 'fulfilled' ? content(result.value) : fail(result.reason);
const tickerLink = (ticker, exchange = '') => `<a class="ticker-link" href="#stock/${encodeURIComponent(ticker)}${exchange ? `/${encodeURIComponent(exchange)}` : ''}">${e(ticker)} <span>↗</span></a>`;
const safeUrl = (url) => { try { const parsed = new URL(url); return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : ''; } catch { return ''; } };
const sampleOpportunityAlerts = [
  { ticker: 'RELIANCE', title: 'Example: results follow-through', summary: 'Illustrative format for an alert about a material results update. No live event is being reported.' },
  { ticker: 'TCS', title: 'Example: guidance change', summary: 'Illustrative format for an alert about a verified change in company guidance. No live event is being reported.' },
  { ticker: 'INFY', title: 'Example: sector signal', summary: 'Illustrative format for an alert linking a sector development to company evidence. No live event is being reported.' },
];

export async function dashboard(state) {
  const [selection, usage, lists, alerts] = await Promise.allSettled([api('/me/active-stocks'), api('/me/usage'), api('/watchlists'), api('/alerts?limit=5')]);
  const selected = value(selection, {}).tickers || [];
  const counts = value(usage, {});
  const limit = counts.access?.limits || {};
  const firstName = e((state.user.name || 'there').split(' ')[0]);
  return `${head('YOUR WORKSPACE / OVERVIEW', `Good to see you, ${firstName}`, 'A little more context for the companies you follow.', '<a class="btn blue head-action" href="#catalog">Explore stocks ↗</a>')}
  <div class="overview-strip"><div><span class="eyebrow">RESEARCH / INDIA</span><strong>Your market, in context.</strong><p>Start with a company. Follow the connections that matter to your research.</p></div><div class="orbital" aria-hidden="true"><i></i><i></i><i></i><b>SG</b></div></div>
  <div class="metrics-grid"><div class="metric"><span class="eyebrow">01 / ACTIVE STOCKS</span><strong>${selection.status === 'fulfilled' ? selected.length : '—'}<small>${limit.active_stocks ? ` / ${e(limit.active_stocks)}` : ''}</small></strong><p>Your selected research universe</p><a href="#catalog">Manage selection ↗</a></div><div class="metric"><span class="eyebrow">02 / WATCHLISTS</span><strong>${lists.status === 'fulfilled' ? (lists.value.items || []).length : '—'}</strong><p>Groups you have saved</p><a href="#watchlists">View watchlists ↗</a></div><div class="metric"><span class="eyebrow">03 / ALERTS THIS MONTH</span><strong>${usage.status === 'fulfilled' ? e(counts.opportunity_alerts_this_month) : '—'}<small>${limit.opportunity_alerts_per_month ? ` / ${e(limit.opportunity_alerts_per_month)}` : ''}</small></strong><p>In-app research alerts</p><a href="#alerts">View alert feed ↗</a></div></div>
  <div class="dashboard-columns"><section>${section('Your active stocks', '<a href="#catalog">Browse catalog ↗</a>')}${detail(selection, () => selected.length ? `<ul class="row-list">${selected.map((ticker) => `<li class="data-row"><div>${tickerLink(ticker)}<p>Selected for research</p></div><a href="#stock/${encodeURIComponent(ticker)}" aria-label="Open ${e(ticker)}">↗</a></li>`).join('')}</ul>` : empty('Start with a stock', 'Search the catalog and select a company to build your research universe.', '<a class="pill" href="#catalog">Explore stocks ↗</a>'))}</section>
  <section>${section('Recent alerts', '<a href="#alerts">View all ↗</a>')}${detail(alerts, (data) => data.items?.length ? `<ul class="row-list">${data.items.map((item) => `<li class="data-row"><div><strong>${e(item.ticker || 'Research alert')}</strong><p>${e(item.summary || 'New research context')}</p></div><span class="eyebrow">${e(formatDate(item.created_at))}</span></li>`).join('')}</ul>` : empty('All quiet here', 'New alerts will appear here when monitoring produces them.'))}</section></div>`;
}

export async function catalog(state) {
  const params = new URLSearchParams({ limit: '50', query: state.query || '' });
  if (state.exchange) params.set('exchange', state.exchange);
  if (state.cursor) params.set('cursor', state.cursor);
  const [results, selection] = await Promise.allSettled([api(`/market/stocks?${params}`), api('/me/active-stocks')]);
  const active = value(selection, {}).tickers || [];
  const items = value(results, {}).items || [];
  const next = value(results, {}).next_cursor;
  state.nextCursor = next || null;
  return `${head('MARKET DIRECTORY / NSE + BSE', 'Explore stocks', 'Search the directory, then choose which companies to add to your active research selection.')}
  <form id="catalog-form" class="search-panel"><label><span class="eyebrow">COMPANY OR SYMBOL</span><input name="query" value="${e(state.query || '')}" placeholder="Search by company or ticker" maxlength="80"></label><label><span class="eyebrow">EXCHANGE</span><select name="exchange"><option value="">All exchanges</option><option value="NSE" ${state.exchange === 'NSE' ? 'selected' : ''}>NSE</option><option value="BSE" ${state.exchange === 'BSE' ? 'selected' : ''}>BSE</option></select></label><button class="btn blue" type="submit">Search ↗</button></form>
  <div class="notice"><strong>Search freely.</strong> Selecting a stock is a separate step. Companies marked “Register” need data collection before they can be selected.</div>
  ${selection.status === 'rejected' ? fail(selection.reason) : ''}${section('Company directory', `<span class="eyebrow">${e(items.length)} RESULTS ON THIS PAGE</span>`)}
  ${detail(results, () => items.length ? `<div class="catalog-list">${items.map((item) => `<article class="company-row"><div><span class="eyebrow">${e(item.exchange)} / ${e(item.trading_symbol)}</span><h3>${e(item.name)}</h3><p>${e(item.isin)} · ${item.registered ? 'Available for research' : 'Registration required'}</p></div><div class="row-actions">${item.registered ? `${tickerLink(item.trading_symbol, item.exchange)}<button class="pill" data-action="toggle-stock" data-ticker="${e(item.trading_symbol)}">${active.includes(item.trading_symbol) ? 'Remove selection' : 'Select stock'} ${active.includes(item.trading_symbol) ? '−' : '+'}</button>` : `<button class="pill" data-action="register" data-ticker="${e(item.trading_symbol)}" data-exchange="${e(item.exchange)}">Register ↗</button>`}</div></article>`).join('')}</div>` : empty('No companies found', state.query ? 'Try another company name or ticker.' : 'The stock directory has no results yet.'))}
  <div class="pagination">${state.cursor ? '<button class="pill" data-action="catalog-first">← First page</button>' : ''}${next ? '<button class="pill" data-action="catalog-next">Next page →</button>' : ''}</div>${state.job ? `<div class="notice"><strong>Registration ${e(state.job.status || state.job.state || 'submitted')}.</strong> Job ${e(state.job.job_id || state.job.id || '')}. <button class="inline-link" data-action="refresh-job">Refresh status ↗</button></div>` : ''}`;
}

export async function stock(state, ticker, exchange = 'NSE') {
  const t = encodeURIComponent(ticker);
  exchange = exchange === 'BSE' ? 'BSE' : 'NSE';
  const window = state.window || 'LAST_6M';
  const canViewEvidence = state.access?.features?.professional_evidence?.allowed ?? (state.user.is_developer || state.user.plan === 'PRO');
  const [profile, candles, financials, documents, shareholding, evidence] = await Promise.allSettled([
    api(`/market/stocks/${t}?exchange=${exchange}`),
    api(`/market/stocks/${t}/candles?exchange=${exchange}`), api(`/market/stocks/${t}/financials?window=${window}`), api(`/stocks/${t}/documents/search?limit=10`),
    api(`/market/stocks/${t}/shareholding?exchange=${exchange}`),
    canViewEvidence ? api(`/stocks/${t}/professional-evidence?limit=50`) : Promise.resolve(null),
  ]);
  const p = value(profile, {});
  state.candles = value(candles, {}).candles || [];
  return `${head(`STOCK / ${e(ticker)} / RESEARCH`, e(p.name || ticker), `${e(p.exchange || exchange)} · ${e(ticker)} · ${e(p.profile?.sector || 'Company context')}`, '<a class="pill head-action" href="#catalog">← Back to stocks</a>')}
  <div class="stock-toolbar"><span class="eyebrow">RESEARCH WINDOW</span><button class="window-button ${window === 'LAST_6M' ? 'active' : ''}" data-action="window" data-window="LAST_6M">6 months</button><button class="window-button ${window === 'LAST_1Y' ? 'active' : ''}" data-action="window" data-window="LAST_1Y">1 year</button><span class="eyebrow stock-spacer">SCHEDULED DATA / NOT LIVE</span></div>
  <section id="stock-connections" aria-label="Stock connection explorer"></section>
  <div class="stock-grid"><section><div class="panel"><span class="eyebrow">01 / COMPANY PROFILE</span><h2>About the business</h2>${detail(profile, (data) => `<p>${e(data.profile?.business_summary || 'Company profile is not available yet.')}</p><p class="eyebrow">SOURCE: ${e(data.vendor_id || 'NOT AVAILABLE')} · AS OF ${e(formatDate(data.vendor_as_of))}</p>`)}</div>
  ${section('Price history', '<span class="eyebrow">DAILY CANDLES</span>')}${detail(candles, () => state.candles.length ? '<div id="price-chart" class="price-chart" aria-label="Daily candlestick chart"></div><p class="eyebrow">SOURCE: ' + e(value(candles, {}).vendor_id || 'NOT AVAILABLE') + ' · AS OF ' + e(formatDate(state.candles.at(-1)?.vendor_as_of)) + '</p>' : empty('No price history yet', 'Available daily candles will appear here.'))}
  ${section('Professional perspectives', '<span class="eyebrow">PUBLISHED EVIDENCE</span>')}${canViewEvidence ? detail(evidence, professionalEvidence) : '<div class="notice">Professional perspectives depend on your account’s access policy. Review your current access in <a class="ticker-link" href="#profile">account settings</a>.</div>'}
  </section><aside><div class="panel soft"><span class="eyebrow">02 / RESEARCH NOTES</span><h3>Context, not a conclusion.</h3><p>Relationships are evidence to inspect, not proof of a price move. Consider the source, timing and opposing information.</p></div>
  ${section('Financial context')}${detail(financials, (data) => `<div class="panel compact-data">${financialSummary(data)}</div>`)}
  ${section('Shareholding')}${detail(shareholding, (data) => `<div class="panel compact-data">${shareholdingSummary(data)}</div>`)}
  ${section('Documents')}${detail(documents, (data) => data.items?.length ? `<ul class="row-list">${data.items.map((item) => `<li class="data-row"><div><strong>${e(item.title || item.document_title || 'Document excerpt')}</strong><p>${e(item.text || item.excerpt || item.locator || '')}</p></div></li>`).join('')}</ul>` : empty('No documents found', 'Available source excerpts will appear here.'))}</aside></div>`;
}

function financialSummary(data) {
  const rows = (data.daily_metrics || []).filter((row) => row.session_type === 'CLOSE').sort((a, b) => String(b.trade_date).localeCompare(String(a.trade_date)));
  const latest = rows[0];
  const fields = [['close_price', 'Close price'], ['delivery_pct', 'Delivery %'], ['pe_ratio', 'P/E'], ['pb_ratio', 'P/B'], ['ev_ebitda', 'EV / EBITDA']];
  const present = latest ? fields.filter(([key]) => latest[key] != null) : [];
  const quarterly = [...(data.quarterly_financials || [])].sort((a, b) => String(b.published_date).localeCompare(String(a.published_date)))[0];
  const quarterFields = [['revenue_cr', 'Revenue (₹ cr)'], ['ebitda_cr', 'EBITDA (₹ cr)'], ['pat_cr', 'Profit after tax (₹ cr)'], ['debt_to_equity', 'Debt / equity']];
  const quarterRows = quarterly ? quarterFields.filter(([key]) => quarterly[key] != null) : [];
  if (!present.length && !quarterRows.length) return '<p>Financial checkpoints are not available for this window.</p>';
  return `${present.length ? `<span class="eyebrow">CLOSE / ${e(latest.trade_date)}</span>${present.map(([key, label]) => `<div class="data-row"><span>${label}<small class="source-label">${e(key === 'delivery_pct' ? latest.delivery_vendor_id || 'SOURCE UNAVAILABLE' : latest.vendor_id || 'SOURCE UNAVAILABLE')} · ${e(formatDate(key === 'delivery_pct' ? latest.delivery_vendor_as_of : latest.vendor_as_of))}</small></span><strong>${e(latest[key])}</strong></div>`).join('')}` : ''}${quarterRows.length ? `<span class="eyebrow">QUARTER / ${e(quarterly.quarter_label)}</span>${quarterRows.map(([key, label]) => `<div class="data-row"><span>${label}<small class="source-label">${e(quarterly.source_id || 'SOURCE UNAVAILABLE')} · ${e(formatDate(quarterly.source_as_of))}</small></span><strong>${e(quarterly[key])}</strong></div>`).join('')}` : ''}`;
}

function shareholdingSummary(data) {
  const period = data.periods?.[0];
  if (!period) return '<p>Shareholding history is not available yet.</p>';
  const fields = [['promoters', 'Promoters'], ['fii', 'Foreign institutions'], ['dii', 'Domestic institutions'], ['public', 'Public']];
  return `<span class="eyebrow">${e(period.period)} / ${e(data.vendor_id || 'SOURCE UNAVAILABLE')} · ${e(formatDate(data.vendor_as_of))}</span>${fields.filter(([key]) => period[key] != null).map(([key, label]) => `<div class="data-row"><span>${label}</span><strong>${e(period[key])}%</strong></div>`).join('')}`;
}

function professionalEvidence(data) {
  if (!data?.items?.length) return empty('No published perspectives', 'Available professional evidence will appear here.');
  return data.items.map((item) => { const content = item.content || {}; return `<article class="panel review-card"><span class="eyebrow">${e(item.author_name)} · ${e(content.direction)} · ${e(content.horizon)}</span><h3>${e(content.title)}</h3><p>${e(content.body)}</p><p>Event: ${e(formatDate(content.event_at))} · Expires: ${e(formatDate(content.expires_at))}</p><p>Disclosures: ${e(content.disclosures)}</p><ul>${(content.evidence || []).map((source) => { const url = safeUrl(source.url); return `<li>${url ? `<a class="ticker-link" href="${e(url)}" target="_blank" rel="noopener noreferrer">${e(source.title)} ↗</a>` : e(source.title)} · ${e(source.locator)}</li>`; }).join('')}</ul></article>`; }).join('') + (data.pagination?.next_offset != null ? '<p class="eyebrow">SHOWING FIRST 50 PERSPECTIVES</p>' : '');
}

export async function watchlists(state) {
  const mode = state.watchlistMode === 'active' ? 'active' : 'saved';
  const [lists, selection, monitors, agent] = await Promise.allSettled([
    api('/watchlists'), api('/me/active-stocks'), api('/monitor-rules?limit=500'), api('/agent-status'),
  ]);
  const selected = value(selection, {}).tickers || [];
  const saved = value(lists, {}).items || [];
  const rules = (value(monitors, {}).items || []).filter((rule) =>
    !state.user?.id || !rule.user_id || String(rule.user_id) === String(state.user.id));
  const monitorStatus = (ticker) => {
    if (monitors.status === 'rejected') return ['Status unavailable', 'Monitoring rules could not be loaded.'];
    const matching = rules.filter((rule) => rule.effective_tickers === 'REGISTERED_MARKET' ||
      (Array.isArray(rule.effective_tickers) && rule.effective_tickers.includes(ticker)));
    const running = matching.filter((rule) => rule.active && !rule.pause_reason);
    if (running.length) {
      if (agent.status === 'rejected') return ['Rule active', 'Agent availability could not be checked.'];
      return agent.value.status === 'available'
        ? ['Rule active', `${running.length} active rule${running.length === 1 ? '' : 's'} · Agent available`]
        : ['Rule active', `Agent ${agent.value.status.replaceAll('_', ' ')} · Runs when available`];
    }
    if (matching.length) return ['Monitoring paused', matching.find((rule) => rule.pause_reason)?.pause_reason || 'The matching rules are paused.'];
    return ['No monitoring rule', 'Create a monitoring rule for a saved watchlist containing this stock.'];
  };
  const switcher = `<div class="view-toggle watchlist-toggle" role="group" aria-label="Watchlist view"><button type="button" data-action="watchlist-mode" data-mode="saved" class="${mode === 'saved' ? 'active' : ''}" aria-pressed="${mode === 'saved'}">Saved watchlists${lists.status === 'fulfilled' ? ` · ${saved.length}` : ''}</button><button type="button" data-action="watchlist-mode" data-mode="active" class="${mode === 'active' ? 'active' : ''}" aria-pressed="${mode === 'active'}">Active stocks${selection.status === 'fulfilled' ? ` · ${selected.length}` : ''}</button></div>`;
  const normal = `<form id="watchlist-form" class="panel form-grid"><div><span class="eyebrow">CREATE A WATCHLIST</span><h3>A place for your ideas.</h3><p>Use registered ticker symbols separated by commas. You can also start with an empty list.</p></div><label><span>List name</span><input name="name" maxlength="100" required placeholder="e.g. Financial services"></label><label><span>Tickers</span><input name="tickers" placeholder="e.g. RELIANCE, INFY"></label><button class="btn blue" type="submit">Create watchlist ↗</button></form>
  ${selection.status === 'rejected' ? fail(selection.reason) : ''}${section('Saved watchlists', `<span class="eyebrow">${lists.status === 'fulfilled' ? `${saved.length} LISTS` : 'UNAVAILABLE'}</span>`)}${detail(lists, () => saved.length ? `<div class="watchlist-grid">${saved.map((item) => `<article class="panel"><span class="eyebrow">WATCHLIST / ${e(formatDate(item.created_at))}</span><h3>${e(item.name)}</h3>${(item.tickers || []).length ? `<ul class="saved-tickers">${item.tickers.map((ticker) => `<li><span>${tickerLink(ticker)}</span>${selection.status === 'fulfilled' ? `<button class="inline-link" type="button" data-action="toggle-stock" data-ticker="${e(ticker)}">${selected.includes(ticker) ? 'Remove from active' : 'Add to active'} ${selected.includes(ticker) ? '−' : '+'}</button>` : ''}</li>`).join('')}</ul>` : '<p>No stocks in this list yet.</p>'}<div class="row-actions"><button class="pill" data-action="edit-list" data-id="${e(item.id)}" data-name="${e(item.name)}" data-tickers="${e((item.tickers || []).join(', '))}">Edit ↗</button><button class="pill" data-action="delete-list" data-id="${e(item.id)}" data-name="${e(item.name)}">Delete</button></div></article>`).join('')}</div>` : empty('No watchlists yet', 'Create your first list above to keep companies together.'))}`;
  const active = `<div class="notice"><strong>Your active stock selection.</strong> These stocks are available for your research. Monitoring requires a rule for a saved watchlist and an available agent. <a class="ticker-link" href="#monitoring">Manage monitoring ↗</a></div>${section('Active stocks', '<a href="#catalog">Add stocks ↗</a>')}${detail(selection, () => selected.length ? `<ul class="row-list active-stock-list">${selected.map((ticker) => { const [status, description] = monitorStatus(ticker); return `<li class="data-row"><div>${tickerLink(ticker)}<p><strong>${e(status)}</strong> · ${e(description)}</p></div><div class="row-actions"><a class="pill" href="#monitoring">Monitoring ↗</a><button type="button" class="pill" data-action="toggle-stock" data-ticker="${e(ticker)}">Remove from active −</button></div></li>`; }).join('')}</ul>` : empty('No active stocks yet', 'Choose stocks from a saved watchlist or the directory to add them to your research selection.', '<a class="pill" href="#catalog">Explore stocks ↗</a>'))}`;
  return `${head('YOUR RESEARCH / COLLECTIONS', 'Watchlists', 'Organize saved lists and manage the stocks in your active research selection.')}${switcher}${mode === 'active' ? active : normal}`;
}

export async function alerts() {
  const data = await api('/alerts?limit=50');
  const items = data.items || [];
  const liveAlerts = items.length
    ? `<ul class="row-list">${items.map((item) => `<li class="data-row"><div><span class="eyebrow">${e(item.ticker)} / ${e(formatDate(item.created_at))}</span><h3>${e(item.opportunity?.title || item.direction || 'Research update')}</h3><p>${e(item.summary || '')}</p></div><div class="row-actions">${item.job_id ? `<a class="pill" href="#agent-job/${encodeURIComponent(item.job_id)}">Inspect evidence ↗</a>` : ''}${item.seen_at ? '<span class="tag">READ</span>' : `<button class="pill" data-action="ack-alert" data-id="${e(item.id)}">Mark read</button>`}</div></li>`).join('')}</ul>`
    : empty('No live alerts yet', 'Cited research alerts will appear here when an available agent finds a supported change.');
  const examples = items.length ? '' : `${section('Example opportunity alerts', '<span class="eyebrow">ILLUSTRATIVE / NOT LIVE</span>')}<div class="notice sample-alert-note"><strong>Sample entries.</strong> These examples show the alert format only. They have no live market evidence, are not investment recommendations, and do not count toward alert usage.</div><ul class="row-list sample-alert-list">${sampleOpportunityAlerts.map((item) => `<li class="data-row sample-alert-row"><div><span class="eyebrow">${e(item.ticker)} / EXAMPLE ONLY</span><h3>${e(item.title)}</h3><p>${e(item.summary)}</p></div><span class="tag">DEMO</span></li>`).join('')}</ul>`;
  return `${head('YOUR RESEARCH / INBOX', 'Alerts', 'A record of research alerts generated for your account.')}${section('In-app alerts', `<span class="eyebrow">${items.length} LIVE</span>`)}${liveAlerts}${examples}`;
}

export async function profile(state) {
  const [usage, broker] = await Promise.allSettled([api('/me/usage'), api('/me/broker-connections/upstox')]);
  const user = state.user;
  return `${head('ACCOUNT / SETTINGS', 'Your account', 'Your identity, access and connected market-data service.')}
  <div class="profile-grid"><section class="panel"><span class="eyebrow">01 / ACCOUNT</span><h2>${e(user.name)}</h2><p>${e(user.email || 'Email not attached')}</p><p><span class="tag blue">${e(user.is_developer ? 'DEVELOPER' : user.plan)}</span> <span class="tag">${e((user.roles || []).join(' / '))}</span></p><p>Access is assigned by the platform administrator. Payments and checkout are not enabled.</p></section>
  <section class="panel"><span class="eyebrow">02 / USAGE</span><h2>Current month</h2>${detail(usage, (data) => `<p><strong>${e(data.active_stocks)}</strong> active stocks · <strong>${e(data.opportunity_alerts_this_month)}</strong> alerts issued</p><p>Alert allowance resets ${e(formatDate(data.resets_at))} in India time.</p>`)}</section></div>
  ${section('Market data connection')}${detail(broker, (data) => `<div class="panel"><span class="tag blue">${e(data.status || 'NOT CONNECTED')}</span><h3>Upstox</h3><p>Connect an Upstox access token for market-data requests. The token is never displayed after saving.</p><form id="broker-form" class="inline-form"><label><span class="sr">Upstox access token</span><input type="password" name="access_token" required autocomplete="off" placeholder="Upstox access token"></label><button class="btn" type="submit">Connect / update ↗</button><button class="pill" type="button" data-action="disconnect-broker">Disconnect</button></form></div>`)}
  ${section('Change password')}<form id="password-form" class="panel inline-form"><label><span>Current password</span><input type="password" name="current_password" required autocomplete="current-password"></label><label><span>New password</span><input type="password" name="password" minlength="12" required autocomplete="new-password"></label><button class="btn" type="submit">Update password ↗</button></form>`;
}

function reviewQueueContent(queue) {
  const items = queue.items || [];
  return `${section('Submissions awaiting review', `<span class="eyebrow">${items.length} PENDING</span>`)}${items.length ? items.map((item) => `<article class="panel review-card"><span class="eyebrow">${e(item.content?.ticker)} / ${e(item.author_name)} / REVISION ${e(item.revision)}</span><h3>${e(item.content?.title || 'Research submission')}</h3><p>${e(item.content?.body || '')}</p><p>Direction: ${e(item.content?.direction)} · Horizon: ${e(item.content?.horizon)} · Event: ${e(formatDate(item.content?.event_at))} · Expires: ${e(formatDate(item.content?.expires_at))}</p><p>Disclosures: ${e(item.content?.disclosures)}</p><h3>Sources</h3><ul>${(item.content?.evidence || []).map((source) => { const url = safeUrl(source.url); return `<li>${url ? `<a class="ticker-link" href="${e(url)}" target="_blank" rel="noopener noreferrer">${e(source.title)} ↗</a>` : e(source.title)} · ${e(source.locator)}</li>`; }).join('')}</ul><form class="review-form stack-form" data-id="${e(item.id)}" data-revision="${e(item.revision)}"><label><span>Review reason</span><textarea name="reason" required maxlength="3000" rows="2"></textarea></label><div class="row-actions"><button class="btn blue" name="decision" value="APPROVE" type="submit">Approve</button><button class="pill" name="decision" value="REJECT" type="submit">Reject</button></div></form></article>`).join('') : empty('No submissions awaiting review', 'Submitted professional insights will appear here when they are ready for your review.')}`;
}

export async function reviewInsights(state) {
  const user = state.user;
  const canReview = user.is_developer || user.roles?.includes('REVIEWER');
  const canSeeOwn = user.is_developer || user.roles?.includes('PROFESSIONAL');
  const heading = head('PROFESSIONAL / REVIEW', 'Review insights', 'Review submitted professional research and its supporting sources.', '<a class="pill" href="#contributions">Your contributions ↗</a>');
  if (canReview) {
    const queue = await api('/review-queue');
    return `${heading}<div class="notice"><strong>Review before publication.</strong> Read the thesis, sources and disclosures, then record your reason for approval or rejection.</div>${reviewQueueContent(queue)}`;
  }
  if (!canSeeOwn) return `${heading}${empty('Review access required', 'A reviewer role is required to review professional insights.')}`;
  const data = await api('/contributions');
  const pending = (data.items || []).filter((item) => item.status === 'SUBMITTED');
  return `${heading}<div class="notice"><strong>Track your submitted insights.</strong> A reviewer role is required to review other authors’ submissions.</div>${section('Your insights in review', `<span class="eyebrow">${pending.length} PENDING</span>`)}${pending.length ? `<ul class="row-list">${pending.map((item) => `<li class="data-row"><div><strong>Insight awaiting review</strong><p>Submitted · Revision ${e(item.revision)}</p></div><a class="pill" href="#contribution/${encodeURIComponent(item.id)}">View insight ↗</a></li>`).join('')}</ul>` : empty('No insights awaiting review', 'Submit a draft from Contributions to send it for review.', '<a class="pill" href="#contributions">View contributions ↗</a>')}`;
}

export async function contributions(state) {
  const canAuthor = state.user.is_developer || (state.user.professional_verified && state.user.roles?.includes('PROFESSIONAL'));
  const canReview = state.user.is_developer || state.user.roles?.includes('REVIEWER');
  const [data, queue] = await Promise.all([api('/contributions'), canReview ? api('/review-queue') : Promise.resolve(null)]);
  return `${head('PROFESSIONAL / EVIDENCE', 'Contributions', 'Create cited research and follow its independent review.')}
  ${canAuthor ? `<details class="panel contribution-form"><summary>Create a research draft <span>+</span></summary><form id="contribution-form" class="stack-form"><div class="form-pair"><label><span>Registered ticker</span><input name="ticker" required maxlength="40" placeholder="RELIANCE"></label><label><span>Direction</span><select name="direction"><option>BULLISH</option><option>BEARISH</option><option>NEUTRAL</option></select></label></div><label><span>Title</span><input name="title" required maxlength="300"></label><label><span>Research thesis</span><textarea name="body" required maxlength="50000" rows="5"></textarea></label><div class="form-pair"><label><span>Horizon</span><input name="horizon" required maxlength="200" placeholder="e.g. 6–12 months"></label><label><span>Source title</span><input name="source_title" required maxlength="300"></label></div><div class="form-pair"><label><span>Event time</span><input name="event_at" type="datetime-local" required></label><label><span>Expiry time</span><input name="expires_at" type="datetime-local" required></label></div><label><span>Source URL</span><input name="source_url" type="url" required placeholder="https://…"></label><label><span>Source locator</span><input name="locator" required maxlength="500" placeholder="Page, section, or paragraph"></label><label><span>Disclosures</span><textarea name="disclosures" required maxlength="3000" rows="2"></textarea></label><button type="submit" class="btn blue">Save draft ↗</button></form></details>` : '<div class="notice"><strong>Author access.</strong> Drafting requires verified Professional privileges or Developer access.</div>'}
  ${section('Your contributions')}${data.items?.length ? `<ul class="row-list">${data.items.map((item) => `<li class="data-row"><div><strong>${e(item.ticker || 'Contribution')}</strong><p>${e(item.status || 'DRAFT')} · Revision ${e(item.revision)}</p></div><div class="row-actions"><a class="pill" href="#contribution/${encodeURIComponent(item.id)}">Inspect ↗</a>${canAuthor && item.status === 'DRAFT' ? `<button class="pill" data-action="submit-contribution" data-id="${e(item.id)}" data-revision="${e(item.revision)}">Submit for review ↗</button>` : ''}</div></li>`).join('')}</ul>` : empty('No contributions yet', 'Saved drafts and their publication status will appear here.')}
  ${canReview ? reviewQueueContent(queue) : ''}`;
}

export async function contribution(id) {
  const data = await api(`/contributions/${encodeURIComponent(id)}`);
  return `${head('PROFESSIONAL / CONTRIBUTION', e(data.ticker || 'Research'), `Status: ${e(data.status)} · Revision ${e(data.revision)}`, '<a class="pill" href="#contributions">← Contributions</a>')}${(data.versions || []).map((version) => { const content = version.content || {}; return `<article class="panel review-card"><span class="eyebrow">VERSION ${e(version.version_number)} / ${e(content.direction)} / ${e(content.horizon)}</span><h2>${e(content.title)}</h2><p>${e(content.body)}</p><p>Event: ${e(formatDate(content.event_at))} · Expires: ${e(formatDate(content.expires_at))}</p><p>Disclosures: ${e(content.disclosures)}</p><h3>Sources</h3><ul>${(content.evidence || []).map((source) => { const url = safeUrl(source.url); return `<li>${url ? `<a class="ticker-link" href="${e(url)}" target="_blank" rel="noopener noreferrer">${e(source.title)} ↗</a>` : e(source.title)} · ${e(source.locator)}</li>`; }).join('')}</ul></article>`; }).join('') || empty('No versions found', 'Saved versions will appear here.')}`;
}

export async function admin() {
  const data = await api('/admin/users?limit=50');
  return `${head('DEVELOPER / ADMINISTRATION', 'People & access', 'Review platform accounts and manage their access.', '<a class="pill" href="#review">Review insights ↗</a>')}${section('Accounts', `<span class="eyebrow">${(data.items || []).length} SHOWN</span>`)}${data.items?.length ? `<div class="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Plan</th><th>Roles</th><th>Status</th><th>Action</th></tr></thead><tbody>${data.items.map((user) => `<tr><td>${e(user.name)}</td><td>${e(user.email || '—')}</td><td>${e(user.plan)}</td><td>${e((user.roles || []).join(', '))}</td><td>${user.disabled ? 'Disabled' : 'Active'}</td><td>${user.is_developer ? '<span class="eyebrow">ENVIRONMENT MANAGED</span>' : `<button class="inline-link" data-action="edit-user" data-id="${e(user.id)}" data-name="${e(user.name)}" data-plan="${e(user.plan)}" data-roles="${e((user.roles || []).join(','))}" data-verified="${Boolean(user.professional_verified)}" data-disabled="${Boolean(user.disabled)}">Edit ↗</button>`}</td></tr>`).join('')}</tbody></table></div>` : empty('No accounts found', 'Accounts appear here after signup.')}`;
}

export { fail, empty, safeUrl };
