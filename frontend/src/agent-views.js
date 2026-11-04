import { api, escapeHtml as e, formatDate } from './api.js';
import { safeUrl } from './views.js';

const title = (kicker, heading, description) => `<div class="page-head"><div><div class="eyebrow">${kicker}</div><h1>${heading}<span>.</span></h1><p>${description}</p></div></div>`;
const section = (heading, detail = '') => `<div class="section-head"><h2>${heading}</h2>${detail}</div>`;
const notice = (status) => `<div class="notice"><strong>Agent status: ${e(status.replaceAll('_', ' '))}.</strong> ${status === 'available' ? 'Research jobs can be submitted.' : status === 'pilot_restricted' ? 'The agent pilot is currently available to the developer account.' : 'Results will be available when the agent service is ready.'}</div>`;
const jobLink = (job) => `<li class="data-row"><div><span class="eyebrow">${e(job.kind)} / ${e(formatDate(job.created_at))}</span><h3>${e(job.input?.question || 'Research job')}</h3><p>${e(job.error === 'budget_blocked' ? 'Budget blocked' : job.state)}</p></div><a class="pill" href="#agent-job/${encodeURIComponent(job.id)}">View ↗</a></li>`;
const list = (items, empty) => items.length ? `<ul class="row-list">${items.map(jobLink).join('')}</ul>` : `<div class="empty-state"><h3>${empty}</h3></div>`;

export async function research(conversationId) {
  const [status, selection, conversations, jobs] = await Promise.all([
    api('/agent-status'), api('/me/active-stocks'), api('/conversations'), api('/agent-jobs?limit=25'),
  ]);
  const messages = conversationId ? await api(`/conversations/${encodeURIComponent(conversationId)}/messages`) : {items: []};
  const recent = jobs.items.filter((job) => job.kind === 'chat');
  return `${title('AGENTS / RESEARCH', 'Ask a research question', 'Explore selected stocks with cited events, company connections and financial evidence.')}${notice(status.status)}
  <div class="research-layout"><section><form id="research-form" class="panel stack-form" data-conversation="${e(conversationId || '')}"><label><span>Stock symbols (comma-separated)</span><input name="tickers" required placeholder="${e(selection.tickers.join(', ') || 'Select a stock first')}"></label><label><span>Research question</span><textarea name="question" required maxlength="8000" rows="4" placeholder="What changed, and why could it matter?"></textarea></label><label><span>Context window</span><select name="window"><option value="LAST_6M">Last 6 months</option><option value="LAST_1Y">Last year</option></select></label><button type="submit" class="btn blue" ${status.status !== 'available' ? 'disabled' : ''}>Send question ↗</button></form>
  ${section('Conversation')}${messages.items.length ? `<ul class="row-list">${messages.items.map((message) => `<li class="data-row"><div><span class="eyebrow">${e(message.role)} / ${e(formatDate(message.created_at))}</span><p>${e(message.restricted ? 'This message is restricted by current access.' : message.evidence_stale ? 'A cited professional source is no longer current.' : message.content)}</p></div></li>`).join('')}</ul>` : '<p class="agent-empty">Select a conversation or start a new one above.</p>'}</section>
  <aside>${section('Conversations', '<a href="#research">New ↗</a>')}${conversations.items.length ? `<ul class="row-list">${conversations.items.map((item) => `<li class="data-row"><a class="ticker-link" href="#research/${encodeURIComponent(item.id)}">${e(item.title)} ↗</a></li>`).join('')}</ul>` : '<p class="agent-empty">No conversations yet.</p>'}${section('Recent research jobs')}${list(recent, 'No research jobs yet')}</aside></div>`;
}

export async function discovery() {
  const [status, jobs] = await Promise.all([api('/agent-status'), api('/agent-jobs?limit=25')]);
  const scans = jobs.items.filter((job) => job.kind === 'discovery');
  return `${title('AGENTS / DISCOVERY', 'Discover opportunities', 'Screen recent events for supported equity swing ideas and inspect the evidence behind each one.')}${notice(status.status)}
  <form id="discovery-form" class="panel stack-form"><label><span>Research focus</span><textarea name="question" required maxlength="8000" rows="3">Find recent event-driven equity opportunities with supporting and opposing evidence.</textarea></label><label><span>Stock symbols, optional</span><input name="tickers" placeholder="Leave empty to scan the registered market"></label><label><span>Background context</span><select name="window"><option value="LAST_6M">Last 6 months</option><option value="LAST_1Y">Last year</option></select></label><button class="btn blue" type="submit" ${status.status !== 'available' ? 'disabled' : ''}>Run discovery ↗</button></form>
  <details class="panel contribution-form"><summary>Enable hourly market monitoring <span>+</span></summary><form id="market-monitor-form" class="stack-form"><label><span>What should the monitor look for?</span><textarea name="question" required maxlength="8000" rows="3">Find new event-driven equity opportunities supported by evidence.</textarea></label><button class="btn" type="submit">Create hourly market rule ↗</button></form></details>
  ${section('Recent scans')}${list(scans, 'No discovery scans yet')}`;
}

export async function monitoring() {
  const [status, monitors, lists, jobs] = await Promise.all([api('/agent-status'), api('/monitor-rules'), api('/watchlists'), api('/agent-jobs?limit=25')]);
  return `${title('AGENTS / MONITORING', 'Watch for change', 'Track watchlists for recent events that may support an equity opportunity.')}${notice(status.status)}
  <form id="monitor-form" class="panel form-grid"><div><span class="eyebrow">NEW MONITOR</span><h3>What would you like to follow?</h3><p>Runs hourly when the agent worker is available.</p></div><label><span>Watchlist</span><select name="watchlist_id" required><option value="">Choose a watchlist</option>${lists.items.map((item) => `<option value="${e(item.id)}">${e(item.name)}</option>`).join('')}</select></label><label><span>Research question</span><input name="question" required maxlength="8000" placeholder="What should change my view?"></label><input name="interval_seconds" type="hidden" value="3600"><button class="btn blue" type="submit">Save monitor ↗</button></form>
  ${section('Monitoring rules')}${monitors.items.length ? `<ul class="row-list">${monitors.items.map((item) => `<li class="data-row"><div><strong>${e(item.question)}</strong><p>${e(item.pause_reason || (item.active ? 'Active' : 'Paused'))} · ${e(item.scope)}</p></div><div class="row-actions"><a class="pill" href="#monitor/${encodeURIComponent(item.id)}">History ↗</a><button class="pill" data-action="toggle-monitor" data-id="${e(item.id)}" data-active="${item.active ? 'true' : 'false'}">${item.active ? 'Pause' : 'Resume'}</button><button class="pill" data-action="delete-monitor" data-id="${e(item.id)}">Remove</button></div></li>`).join('')}</ul>` : '<p class="agent-empty">Create a watchlist rule or an hourly market rule.</p>'}
  ${section('Recent evaluations')}${list(jobs.items.filter((job) => job.kind === 'monitor'), 'No monitoring jobs yet')}`;
}

function citations(refs, sources) {
  return refs.length ? `<ul class="agent-citations">${refs.map((ref) => { const item = sources.find((entry) => entry.kind === ref.kind && entry.id === ref.id && (!ref.ticker || entry.ticker === ref.ticker) && (entry.locator || '') === (ref.locator || '')); const source = item?.source || {}; const url = safeUrl(source.source_url || source.url); const provenance = [source.vendor_id || source.source_id || source.publisher, source.vendor_as_of || source.source_as_of || source.event_date].filter(Boolean).join(' · '); const path = source.relation ? `${source.source || ''} → ${source.target || ''} (${source.relation})` : ''; return `<li><span class="eyebrow">${e(ref.kind)} / ${e(ref.ticker || '')}${ref.locator ? ` / ${e(ref.locator)}` : ''}</span>${provenance ? `<p class="eyebrow">${e(provenance)}</p>` : ''}${path ? `<p>${e(path)}</p>` : ''}<p>“${e(ref.quote)}”</p>${url ? `<a class="ticker-link" href="${e(url)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>` : ''}</li>`; }).join('')}</ul>` : '<p class="agent-empty">No source references were returned.</p>';
}

function opportunityCard(item, sources) {
  return `<article class="panel opportunity-card"><div class="row-actions"><span class="tag blue">${e(item.ticker)}</span><span class="tag">${e(item.direction)}</span><span class="eyebrow">${e(item.horizon_sessions)} TRADING SESSIONS</span></div><h3>${e(item.title)}</h3><p>${e(item.thesis)}</p><dl class="opportunity-details"><dt>Why now</dt><dd>${e(item.why_now)}</dd><dt>Risks</dt><dd>${e(item.risks)}</dd><dt>Invalidation</dt><dd>${e(item.invalidation)}</dd></dl><details><summary>Inspect catalyst and connections</summary>${citations([item.catalyst, ...item.connections, ...item.corroboration], sources)}</details><details><summary>Opposing evidence</summary>${citations(item.counter_evidence || [], sources)}</details></article>`;
}

export async function agentJob(id) {
  const job = await api(`/agent-jobs/${encodeURIComponent(id)}`);
  const result = job.result || {};
  let sources = [];
  if (job.state === 'completed' && !job.restricted && !job.evidence_stale) {
    try { sources = (await api(`/agent-jobs/${encodeURIComponent(id)}/evidence`)).items; } catch { sources = []; }
  }
  const state = job.error === 'budget_blocked' ? 'budget blocked' : job.state;
  return {job, html: `${title('AGENTS / JOB', 'Research result', e(job.input?.question || 'Agent evaluation'))}<div class="agent-job-status"><span class="tag blue">${e(state)}</span>${job.input?.conversation_id ? `<a class="pill" href="#research/${encodeURIComponent(job.input.conversation_id)}">Open conversation ↗</a>` : ''}${['pending', 'running'].includes(job.state) ? `<button class="pill" data-action="cancel-agent-job" data-id="${e(job.id)}">Cancel job</button>` : ''}<button class="pill" data-action="retry">Refresh ↻</button></div>
  ${job.restricted ? '<div class="notice">This result is restricted by your current access.</div>' : job.evidence_stale ? '<div class="notice">A cited professional source is no longer current. Run a new evaluation to refresh the evidence.</div>' : job.state === 'completed' ? `<div class="panel"><span class="eyebrow">${e(result.status || 'COMPLETED')}</span><h2>${e(result.answer || 'Evaluation completed.')}</h2>${result.scope_note ? `<p>${e(result.scope_note)}</p>` : ''}${result.coverage ? `<p>Evaluated ${e(result.coverage.evaluated_tickers?.length || 0)} stocks from ${e(result.coverage.candidates_total)} candidate events${result.coverage.partial ? ' · partial coverage' : ''}.</p>` : ''}${result.alerts_suppressed ? `<p>${e(result.alerts_suppressed)} alerts were suppressed by the current allowance.</p>` : ''}</div>
  ${(result.opportunities || []).map((item) => opportunityCard(item, sources)).join('')}
  ${(result.claims || []).length ? `${section('Research claims')}${result.claims.map((claim) => `<article class="panel review-card"><p>${e(claim.text)}</p>${citations(claim.evidence, sources)}</article>`).join('')}` : result.evidence?.length ? `${section('Sources')}${citations(result.evidence, sources)}` : ''}` : `<div class="notice">${e(job.error === 'budget_blocked' ? 'The configured model budget is unavailable or exhausted.' : job.error || 'The job is waiting for the agent worker.')}</div>`}`};
}

export async function monitorHistory(id) {
  const data = await api(`/monitor-rules/${encodeURIComponent(id)}/evaluations`);
  return `${title('AGENTS / MONITORING', 'Evaluation history', 'Review the outcomes recorded for this monitor.')}<a class="pill" href="#monitoring">← Monitoring</a>${section('Evaluations')}${data.items.length ? `<ul class="row-list">${data.items.map((item) => `<li class="data-row"><div><strong>${e(item.restricted ? 'Restricted' : item.outcome?.status || 'Completed')}</strong><p>${e(formatDate(item.evaluated_at))}</p></div><a class="pill" href="#agent-job/${encodeURIComponent(item.job_id)}">Inspect ↗</a></li>`).join('')}</ul>` : '<p class="agent-empty">No completed evaluations yet.</p>'}`;
}
