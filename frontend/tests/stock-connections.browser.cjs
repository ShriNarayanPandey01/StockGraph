/* Run with node --test frontend/tests/stock-connections.browser.cjs.
 * Install Playwright separately, or set PLAYWRIGHT_MODULE to an existing
 * playwright/playwright-core package. No backend or real account is used.
 */
const assert = require('node:assert/strict');
const { before, after, test } = require('node:test');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { mkdir } = require('node:fs/promises');

let chromium;
try {
  ({ chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright'));
} catch {
  throw new Error('Playwright is required. Set PLAYWRIGHT_MODULE to an installed playwright or playwright-core package.');
}

const frontend = path.resolve(__dirname, '..');
const baseURL = process.env.STOCKGRAPH_TEST_URL || 'http://127.0.0.1:5187';
const account = { name: 'Graph Researcher', plan: 'PRO', roles: ['USER'], is_developer: false };
const root = { id: 'RELIANCE', kind: 'Stock', properties: { name: 'Reliance Industries', business_summary: 'Energy and retail businesses.' } };
const macro = { id: 'USD_INR_FX', kind: 'MacroFactor', properties: { name: 'USD / INR', description: 'Exchange-rate transmission into business costs.', embedding: [0.1, 0.2] } };
const commodity = { id: 'BRENT_CRUDE', kind: 'Commodity', properties: { name: 'Brent crude', description: 'An input to refining.' } };
const peer = { id: 'TATASTEEL', kind: 'Stock', properties: { name: 'Tata Steel', business_summary: 'A peer reached through a commodity.' } };
const graphEdges = [
  { id: 'graph-1', source: root.id, target: macro.id, relation: 'SENSITIVE_TO_MACRO', confidence: 0.9, rationale: 'Currency exposure in imported inputs.' },
  { id: 'graph-2', source: macro.id, target: commodity.id, relation: 'RELATED_TO', confidence: 0.85, rationale: 'Imported commodity costs respond to currency.' },
  { id: 'graph-3', source: commodity.id, target: peer.id, relation: 'EXPOSED_TO', confidence: 0.8, rationale: 'Shared input exposure.' },
];
const allRelationships = Array.from({ length: 24 }, (_, index) => ({
  id: `evidence-${index}`, source: 'RELIANCE', target: `DRIVER_${index}`,
  relation: 'EXPOSED_TO', confidence: 0.8, rationale: `Evidence relationship ${index + 1}`,
  provenance: { source_id: 'TEST' }, properties: {},
}));

function responseFor(url) {
  const offset = Number(url.searchParams.get('offset') || 0);
  const limit = Number(url.searchParams.get('limit') || 10);
  const hops = Number(url.searchParams.get('hops') || 1);
  const edges = allRelationships.slice(offset, offset + limit);
  const nextOffset = offset + limit < allRelationships.length ? offset + limit : null;
  const response = {
    ticker: 'RELIANCE', window: 'LAST_6M', start_ts: 1, end_ts: 2,
    processing_status: 'completed', nodes: [root, macro], edges,
    direct_news: [{ id: 'news-1', headline: 'Research source', rationale: 'Source-backed context.', citation: { title: 'Research source', publisher: 'TEST', url: 'https://example.test/source', event_date: '2026-11-01' } }],
    indirect_news: [],
    pagination: { offset, limit, next_offset: nextOffset, as_of_ts: 1793700000, has_more: { edges: nextOffset !== null } },
  };
  if (url.searchParams.has('hops')) response.exploration = {
    nodes: [root, macro, ...(hops >= 2 ? [commodity] : []), ...(hops >= 3 ? [peer] : [])],
    edges: graphEdges.slice(0, hops), hops, truncated: false, node_limit: 200, edge_limit: 500,
  };
  return response;
}

function denseExploration(hops) {
  const nodes = [root];
  const edges = [];
  let previous = [root];
  for (let depth = 1; depth <= hops; depth++) {
    const layer = Array.from({ length: depth === 1 ? 14 : 15 }, (_, index) => ({
      id: `DENSE_${depth}_${String(index).padStart(2, '0')}`,
      kind: depth === 2 ? 'MacroFactor' : 'Commodity',
      properties: { name: `Research driver ${depth}-${String(index).padStart(2, '0')}`, description: `Context for dense node ${depth}-${index}.` },
    }));
    layer.forEach((node, index) => edges.push({
      id: `dense-edge-${node.id}`, source: previous[index % previous.length].id,
      target: node.id, relation: 'RELATED_TO', confidence: 0.85, rationale: 'Dense browser fixture relationship.',
    }));
    nodes.push(...layer);
    previous = layer;
  }
  return { nodes, edges, hops, truncated: false, node_limit: 200, edge_limit: 500 };
}

let server;
let browser;
before(async () => {
  if (!process.env.STOCKGRAPH_TEST_URL) {
    server = spawn(process.execPath, [path.join(frontend, 'node_modules/vite/bin/vite.js'), '--configLoader', 'native', '--host', '127.0.0.1', '--port', '5187', '--strictPort'], {
      cwd: frontend, windowsHide: true, stdio: 'pipe',
    });
    let output = '';
    server.stdout.on('data', (chunk) => { output += chunk; });
    server.stderr.on('data', (chunk) => { output += chunk; });
    const deadline = Date.now() + 15000;
    for (;;) {
      try { if ((await fetch(baseURL)).ok) break; } catch {}
      if (server.exitCode !== null || Date.now() >= deadline) throw new Error(`Vite did not start: ${output}`);
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) });
});
after(async () => {
  await browser?.close();
  server?.kill();
});

async function fixture(t, options = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  t.after(() => context.close());
  const page = await context.newPage();
  const errors = [];
  const requests = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.addInitScript(() => sessionStorage.setItem('stockgraph.session', 'browser-test-session'));
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    requests.push(url.pathname + url.search);
    const fulfill = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (options.route && await options.route({ url, route, fulfill })) return;
    if (url.pathname.endsWith('/connections')) {
      if (options.connections && await options.connections({ route, url, fulfill })) return;
      const result = responseFor(url);
      if (options.dense && url.searchParams.has('hops')) result.exploration = denseExploration(Number(url.searchParams.get('hops')));
      return fulfill(result);
    }
    const pathname = url.pathname.replace('/api/v1', '');
    if (pathname === '/me') return fulfill({ user: account, access: { features: { professional_evidence: { allowed: true } } } });
    if (pathname === '/market/stocks/RELIANCE') return fulfill({ exchange: 'NSE', trading_symbol: 'RELIANCE', name: 'Reliance Industries', profile: { business_summary: root.properties.business_summary, sector: 'Energy' }, vendor_id: 'TEST', vendor_as_of: '2026-11-01' });
    if (pathname.endsWith('/candles')) return fulfill({ vendor_id: 'TEST', candles: [{ trade_date: '2026-11-01', open: 10, high: 12, low: 9, close: 11, vendor_as_of: '2026-11-01' }] });
    if (pathname.endsWith('/financials')) return fulfill({ daily_metrics: [], quarterly_financials: [] });
    if (pathname.endsWith('/shareholding')) return fulfill({ periods: [] });
    if (pathname.endsWith('/documents/search') || pathname.endsWith('/professional-evidence')) return fulfill({ items: [] });
    if (pathname === '/me/active-stocks') return fulfill({ tickers: ['RELIANCE'] });
    if (pathname === '/me/usage') return fulfill({ active_stocks: 1, opportunity_alerts_this_month: 0 });
    if (pathname === '/watchlists' || pathname === '/alerts') return fulfill({ items: [] });
    return fulfill({ detail: `Unmocked API: ${pathname}` }, 404);
  });
  await page.goto(`${baseURL}/app/#stock/RELIANCE/NSE`);
  await page.locator('#stock-connections svg[data-graph-canvas]').waitFor();
  await page.locator('#price-chart canvas').first().waitFor();
  await page.evaluate(() => {
    window.__connectionTest = {
      main: document.querySelector('#workspace-main'),
      heading: document.querySelector('#workspace-main h1'),
      chart: document.querySelector('#price-chart'),
    };
  });
  const unchanged = async () => {
    assert.equal(await page.evaluate(() => {
      const old = window.__connectionTest;
      return old.main === document.querySelector('#workspace-main') && old.heading === document.querySelector('#workspace-main h1') && old.chart === document.querySelector('#price-chart');
    }), true, 'Graph interactions must preserve the surrounding page and chart DOM');
    assert.deepEqual(errors, [], 'Browser must not raise uncaught JavaScript errors');
  };
  return { page, requests, errors, unchanged };
}

test('saved and active watchlists switch independently and reflect actual monitoring rules', async (t) => {
  let selected = ['RELIANCE'];
  const { page, errors } = await fixture(t, { route: async ({ url, route, fulfill }) => {
    const pathname = url.pathname.replace('/api/v1', '');
    if (pathname === '/me/active-stocks') {
      if (route.request().method() === 'PUT') selected = route.request().postDataJSON().tickers;
      await fulfill({ tickers: selected }); return true;
    }
    if (pathname === '/watchlists') {
      await fulfill({ items: [{ id: 'list-1', name: 'Long term', tickers: ['RELIANCE', 'TCS'], created_at: '2026-11-01' }] }); return true;
    }
    if (pathname === '/monitor-rules') {
      await fulfill({ items: [{ scope: 'watchlist', active: true, effective_tickers: ['RELIANCE'], pause_reason: null }] }); return true;
    }
    if (pathname === '/agent-status') { await fulfill({ status: 'unavailable' }); return true; }
    return false;
  } });
  await page.locator('[data-nav="watchlists"]').click();
  await page.getByRole('heading', { name: 'Long term' }).waitFor();
  await page.locator('[data-action="toggle-stock"][data-ticker="TCS"]').click();
  await page.getByText('Stock selection updated.').waitFor();
  await page.locator('[data-action="watchlist-mode"][data-mode="active"]').click();
  await page.getByRole('heading', { name: 'Active stocks', exact: true }).waitFor();
  assert.match(await page.locator('.active-stock-list').innerText(), /RELIANCE[\s\S]*Rule active[\s\S]*Agent unavailable/);
  assert.match(await page.locator('.active-stock-list').innerText(), /TCS[\s\S]*No monitoring rule/);
  await page.locator('.active-stock-list [data-action="toggle-stock"][data-ticker="TCS"]').click();
  await page.locator('.active-stock-list [data-action="toggle-stock"][data-ticker="TCS"]').waitFor({ state: 'detached' });
  assert.deepEqual(selected, ['RELIANCE']);
  assert.equal(await page.locator('.active-stock-list [data-ticker="TCS"]').count(), 0);
  assert.equal(await page.locator('[data-action="watchlist-mode"][data-mode="active"]').getAttribute('aria-pressed'), 'true');
  await page.locator('[data-action="watchlist-mode"][data-mode="saved"]').click();
  await page.getByRole('heading', { name: 'Long term' }).waitFor();
  assert.equal(await page.locator('[data-action="toggle-stock"][data-ticker="TCS"]').innerText(), 'Add to active +');
  assert.deepEqual(errors, []);
});

test('reviewers can find and approve a submitted professional insight', async (t) => {
  let pending = [{ id: 'insight-1', revision: 4, author_name: 'Research Author', content: {
    ticker: 'RELIANCE', title: 'Business outlook', body: 'A cited research thesis.', direction: 'NEUTRAL',
    horizon: 'Six months', event_at: '2026-10-01T00:00:00Z', expires_at: '2027-10-01T00:00:00Z',
    disclosures: 'No holdings.', evidence: [{ title: 'Source report', url: 'https://example.test/report', locator: 'Page 1' }],
  } }];
  let decision;
  const { page, errors } = await fixture(t, { route: async ({ url, route, fulfill }) => {
    const pathname = url.pathname.replace('/api/v1', '');
    if (pathname === '/me') { await fulfill({ user: { ...account, roles: ['USER', 'REVIEWER'] }, access: {} }); return true; }
    if (pathname === '/review-queue') { await fulfill({ items: pending }); return true; }
    if (pathname === '/contributions/insight-1/review' && route.request().method() === 'POST') {
      decision = route.request().postDataJSON(); pending = []; await fulfill({ status: 'PUBLISHED' }); return true;
    }
    return false;
  } });
  await page.locator('[data-nav="review"]').click();
  await page.getByRole('heading', { name: 'Business outlook' }).waitFor();
  assert.equal(await page.getByRole('link', { name: 'Source report ↗' }).getAttribute('href'), 'https://example.test/report');
  await page.locator('.review-form textarea[name="reason"]').fill('Sources support the thesis.');
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await page.getByText('No submissions awaiting review').waitFor();
  assert.deepEqual(decision, { expected_revision: 4, decision: 'APPROVE', reason: 'Sources support the thesis.' });
  assert.deepEqual(errors, []);
});

test('professional authors can track their submissions without reviewer access', async (t) => {
  const { page, requests, errors } = await fixture(t, { route: async ({ url, fulfill }) => {
    const pathname = url.pathname.replace('/api/v1', '');
    if (pathname === '/me') { await fulfill({ user: { ...account, roles: ['USER', 'PROFESSIONAL'], professional_verified: true }, access: {} }); return true; }
    if (pathname === '/contributions') { await fulfill({ items: [{ id: 'own-insight', status: 'SUBMITTED', revision: 2 }] }); return true; }
    return false;
  } });
  await page.locator('[data-nav="review"]').click();
  await page.getByRole('heading', { name: 'Your insights in review' }).waitFor();
  assert.equal(await page.getByRole('link', { name: 'View insight ↗' }).getAttribute('href'), '#contribution/own-insight');
  assert.equal(await page.locator('.review-form').count(), 0);
  assert.equal(requests.some((request) => request.startsWith('/api/v1/review-queue')), false);
  assert.deepEqual(errors, []);
});

test('developer administration links directly to the review queue', async (t) => {
  const { page, errors } = await fixture(t, { route: async ({ url, fulfill }) => {
    const pathname = url.pathname.replace('/api/v1', '');
    if (pathname === '/me') { await fulfill({ user: { ...account, is_developer: true }, access: {} }); return true; }
    if (pathname === '/admin/users' || pathname === '/review-queue') { await fulfill({ items: [] }); return true; }
    return false;
  } });
  await page.locator('[data-nav="admin"]').click();
  await page.locator('#workspace-main').getByRole('link', { name: 'Review insights ↗' }).click();
  await page.getByText('No submissions awaiting review').waitFor();
  assert.equal(await page.locator('[data-nav="review"]').getAttribute('aria-current'), 'page');
  assert.deepEqual(errors, []);
});

test('nodes are clickable and keyboard accessible; hop selection changes the visible graph', async (t) => {
  const { page, requests, unchanged } = await fixture(t);
  const graphNode = (id) => page.locator(`svg[data-graph-canvas] [data-graph-node="${id}"]`);
  await graphNode('USD_INR_FX').click();
  await page.locator('[data-graph-inspector]').getByText('Exchange-rate transmission into business costs.').waitFor();
  assert.equal(await page.locator('[data-graph-inspector]').innerText().then((text) => /embedding|0\.1,\s*0\.2/i.test(text)), false, 'Embedding vectors are not useful node details');
  await graphNode('RELIANCE').focus();
  await page.keyboard.press('Enter');
  await page.locator('[data-graph-inspector]').getByText('Energy and retail businesses.').waitFor();
  assert.equal(await graphNode('BRENT_CRUDE').count(), 0);
  await page.locator('[data-graph-action="hop"][data-hops="2"]').click();
  await graphNode('BRENT_CRUDE').waitFor();
  assert.equal(await graphNode('TATASTEEL').count(), 0);
  await page.locator('[data-graph-action="hop"][data-hops="3"]').click();
  await graphNode('TATASTEEL').waitFor();
  assert(requests.some((url) => /connections\?.*hops=2/.test(url)));
  assert(requests.some((url) => /connections\?.*hops=3/.test(url)));
  if (process.env.STOCKGRAPH_SCREENSHOTS) {
    const artifacts = path.resolve(frontend, '../artifacts');
    await mkdir(artifacts, { recursive: true });
    await page.locator('#stock-connections').screenshot({ path: path.join(artifacts, 'graph-explorer-desktop.png') });
  }
  await unchanged();
});

test('an older API rejecting hops still displays its available graph', async (t) => {
  const { page, requests, unchanged } = await fixture(t, { connections: async ({ url, fulfill }) => {
    if (url.searchParams.has('hops')) {
      await fulfill({ detail: 'Only fixed windows and pagination parameters are accepted' }, 422);
    } else {
      await fulfill({ ...responseFor(url), nodes: [root, macro], edges: [graphEdges[0]] });
    }
    return true;
  } });
  await page.locator('svg[data-graph-canvas] [data-graph-node="USD_INR_FX"]').click();
  await page.locator('[data-graph-inspector]').getByText('Exchange-rate transmission into business costs.').waitFor();
  assert.equal(await page.locator('[data-graph-action="hop"][data-hops="2"]').isDisabled(), true);
  assert.equal(await page.locator('[data-graph-action="hop"][data-hops="3"]').isDisabled(), true);
  assert.match(await page.locator('[data-graph-message]').innerText(), /one-hop connections.*temporarily unavailable/);
  assert.equal(requests.filter((url) => url.includes('/connections')).length, 2);
  await unchanged();
});

test('evidence has local pagination and news/nodes tabs without refetching the graph or stock sections', async (t) => {
  const { page, requests, unchanged } = await fixture(t);
  const stockReads = requests.filter((url) => !url.includes('/connections')).length;
  await page.locator('[data-graph-action="page-next"]').click();
  await page.locator('#stock-connections').getByText('Evidence relationship 11', { exact: true }).waitFor();
  const pageRequests = requests.filter((url) => url.includes('/connections'));
  assert.equal(pageRequests.length, 2);
  const nextURL = new URL(pageRequests[1], baseURL);
  assert.equal(nextURL.searchParams.get('offset'), '10');
  assert.equal(nextURL.searchParams.has('hops'), false, 'Evidence pagination must not rebuild exploration');
  assert.equal(await page.locator('svg[data-graph-canvas] [data-graph-node="USD_INR_FX"]').count(), 1);
  assert.equal(requests.filter((url) => !url.includes('/connections')).length, stockReads, 'Pagination must not refetch profile, candles or financial sections');
  await page.locator('[data-graph-tab="news"]').click();
  await page.locator('#stock-connections').getByText('Research source', { exact: true }).waitFor();
  await page.locator('[data-graph-tab="nodes"]').click();
  await page.locator('[data-graph-evidence] [data-graph-select="USD_INR_FX"]').click();
  await page.locator('[data-graph-inspector]').getByText('Exchange-rate transmission into business costs.').waitFor();
  await unchanged();
});

test('failed pagination stays local, preserves the graph and can be retried', async (t) => {
  let failNext = true;
  const { page, unchanged } = await fixture(t, { connections: async ({ url, fulfill }) => {
    if (url.searchParams.get('offset') === '10' && failNext) {
      failNext = false;
      await fulfill({ detail: 'Graph page deliberately unavailable' }, 422);
      return true;
    }
    return false;
  } });
  await page.locator('[data-graph-action="page-next"]').click();
  await page.locator('[data-graph-error]').getByText('Graph page deliberately unavailable', { exact: false }).waitFor();
  assert.equal(await page.locator('svg[data-graph-canvas] [data-graph-node="RELIANCE"]').count(), 1);
  await page.locator('[data-graph-action="retry"]').click();
  await page.locator('#stock-connections').getByText('Evidence relationship 11', { exact: true }).waitFor();
  await unchanged();
});

test('connection explorer stays within mobile viewport and retains visible pagination', async (t) => {
  const { page, unchanged } = await fixture(t);
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    const bounds = await page.locator('#stock-connections').boundingBox();
    assert(bounds && bounds.width <= width && bounds.x >= 0 && bounds.x + bounds.width <= width + 1, `Explorer must fit ${width}px viewport`);
    assert.equal(await page.locator('[data-graph-action="page-next"]').isVisible(), true);
    const viewport = await page.locator('[data-graph-viewport]').boundingBox();
    assert(viewport && viewport.height <= 700, 'Graph viewport height must remain bounded even when its canvas grows');
    const nodeSizes = await page.locator('svg[data-graph-canvas] [data-graph-node]').evaluateAll((nodes) => nodes.map((node) => {
      const label = node.querySelector('.connection-node-label');
      const matrix = label.getScreenCTM();
      return {
        labelSize: parseFloat(getComputedStyle(label).fontSize) * Math.hypot(matrix.a, matrix.b),
        hitSize: Math.max(...[...node.querySelectorAll('circle')].map((circle) => circle.getBoundingClientRect().width)),
      };
    }));
    assert(nodeSizes.every(({ labelSize }) => labelSize >= 9.9), `Graph labels must remain readable at ${width}px`);
    assert(nodeSizes.every(({ hitSize }) => hitSize >= 31.9), `Graph node tap targets must remain usable at ${width}px`);
    const evidence = await page.locator('[data-graph-evidence]').evaluate((element) => ({ height: element.getBoundingClientRect().height, overflow: getComputedStyle(element).overflowY }));
    assert(evidence.height <= 500 && ['auto', 'scroll'].includes(evidence.overflow), 'Evidence list must have its own bounded scroll area');
    if (width === 320 && process.env.STOCKGRAPH_SCREENSHOTS) {
      const artifacts = path.resolve(frontend, '../artifacts');
      await mkdir(artifacts, { recursive: true });
      await page.locator('#stock-connections').screenshot({ path: path.join(artifacts, 'graph-explorer-mobile.png') });
    }
  }
  await unchanged();
});

test('leaving a stock while a graph request is pending does not replace the next page', async (t) => {
  let release;
  let requested;
  const entered = new Promise((resolve) => { requested = resolve; });
  const delayed = new Promise((resolve) => { release = resolve; });
  const { page, errors } = await fixture(t, { connections: async ({ url, fulfill }) => {
    if (url.searchParams.get('hops') === '2') {
      requested();
      await delayed;
      await fulfill(responseFor(url));
      return true;
    }
    return false;
  } });
  await page.locator('[data-graph-action="hop"][data-hops="2"]').click();
  await entered;
  await page.locator('[data-nav="dashboard"]').click();
  await page.getByRole('heading', { name: /Good to see you/ }).waitFor();
  release();
  await page.waitForTimeout(150);
  assert.equal(await page.locator('#stock-connections').count(), 0);
  assert.equal(await page.getByRole('heading', { name: /Good to see you/ }).count(), 1);
  assert.deepEqual(errors, []);
});

test('zoom, node dragging and fit controls update the graph without refreshing stock data', async (t) => {
  const { page, requests, unchanged } = await fixture(t);
  const initialRequests = requests.length;
  const canvas = page.locator('svg[data-graph-canvas]');
  const initialCanvas = await canvas.boundingBox();
  const rootNode = page.locator('svg[data-graph-canvas] [data-graph-node="RELIANCE"]');
  const before = await rootNode.getAttribute('transform');
  const bounds = await rootNode.boundingBox();
  assert(bounds);
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width / 2 + 45, bounds.y + bounds.height / 2 + 25, { steps: 5 });
  await page.mouse.up();
  assert.notEqual(await rootNode.getAttribute('transform'), before, 'Dragging must move a node');
  await page.locator('[data-graph-action="zoom-in"]').click();
  let zoomedCanvas = await canvas.boundingBox();
  assert(Math.abs(zoomedCanvas.width / initialCanvas.width - 1.25) < 0.02, 'Zoom in must enlarge the scrollable SVG');
  await page.locator('[data-graph-action="zoom-out"]').click();
  zoomedCanvas = await canvas.boundingBox();
  assert(Math.abs(zoomedCanvas.width - initialCanvas.width) < 1, 'Zoom out must restore the canvas scale');
  await page.locator('[data-graph-action="fit"]').click();
  assert.equal(await rootNode.getAttribute('transform'), before, 'Fit must restore the node layout');
  assert(Math.abs((await canvas.boundingBox()).width - initialCanvas.width) < 1, 'Reset view must restore scale 1');
  assert.equal(requests.length, initialRequests, 'Canvas controls must not refetch data');
  await unchanged();
});

test('dense graphs preserve spacing and can be explored by scrolling, background drag and node-list selection', async (t) => {
  const { page, requests, unchanged } = await fixture(t, { dense: true });
  await page.locator('[data-graph-action="hop"][data-hops="3"]').click();
  const allNodes = page.locator('svg[data-graph-canvas] [data-graph-node]');
  await page.waitForFunction(() => document.querySelectorAll('svg[data-graph-canvas] [data-graph-node]').length === 45);
  const positions = await allNodes.evaluateAll((nodes) => nodes.map((node) => {
    const matrix = node.getScreenCTM();
    return { x: matrix.e, y: matrix.f };
  }));
  for (let index = 0; index < positions.length; index++) {
    for (const other of positions.slice(index + 1)) assert(Math.hypot(positions[index].x - other.x, positions[index].y - other.y) >= 80, 'Dense node centers must stay separated at default scale');
  }
  const viewport = page.locator('[data-graph-viewport]');
  await viewport.scrollIntoViewIfNeeded();
  const dimensions = await viewport.evaluate((element) => ({ width: element.clientWidth, height: element.clientHeight, scrollWidth: element.scrollWidth, scrollHeight: element.scrollHeight, overflow: getComputedStyle(element).overflow }));
  assert(dimensions.scrollWidth > dimensions.width && dimensions.scrollHeight > dimensions.height, 'Large graphs need independent horizontal and vertical scrolling');
  assert.match(dimensions.overflow, /auto|scroll/);
  if (process.env.STOCKGRAPH_SCREENSHOTS) {
    const artifacts = path.resolve(frontend, '../artifacts');
    await mkdir(artifacts, { recursive: true });
    await page.locator('#stock-connections').screenshot({ path: path.join(artifacts, 'graph-explorer-dense.png') });
  }
  const initialRequests = requests.length;
  const farId = await viewport.evaluate((element) => {
    const view = element.getBoundingClientRect();
    return [...element.querySelectorAll('[data-graph-node]')].filter((node) => node.dataset.graphNode !== 'RELIANCE').map((node) => {
      const bounds = node.getBoundingClientRect();
      const visible = bounds.x >= view.x && bounds.y >= view.y && bounds.right <= view.right && bounds.bottom <= view.bottom;
      return { id: node.dataset.graphNode, visible, distance: Math.hypot(bounds.x - view.x - view.width / 2, bounds.y - view.y - view.height / 2) };
    }).filter(({ visible }) => !visible).sort((a, b) => b.distance - a.distance)[0]?.id;
  });
  assert(farId, 'A spacious graph should initially contain offscreen nodes');
  const farNode = page.locator(`svg[data-graph-canvas] [data-graph-node="${farId}"]`);
  const contained = async () => {
    const node = await farNode.boundingBox();
    const view = await viewport.boundingBox();
    return node.x >= view.x && node.y >= view.y && node.x + node.width <= view.x + view.width && node.y + node.height <= view.y + view.height;
  };
  assert.equal(await contained(), false, 'A spacious graph should initially contain offscreen nodes');
  await viewport.evaluate((element, id) => {
    const node = [...element.querySelectorAll('[data-graph-node]')].find((node) => node.dataset.graphNode === id);
    const bounds = node.getBoundingClientRect(), view = element.getBoundingClientRect();
    element.scrollLeft += bounds.x + bounds.width / 2 - view.x - view.width / 2;
    element.scrollTop += bounds.y + bounds.height / 2 - view.y - view.height / 2;
  }, farId);
  assert.equal(await contained(), true, 'Native scrolling must reveal distant nodes');
  await viewport.evaluate((element) => { element.scrollLeft = (element.scrollWidth - element.clientWidth) / 2; element.scrollTop = (element.scrollHeight - element.clientHeight) / 2; });
  const beforeDrag = await viewport.evaluate((element) => ({ left: element.scrollLeft, top: element.scrollTop }));
  const point = await viewport.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    for (const [dx, dy] of [[20, 20], [60, 20], [20, 80], [rect.width - 25, 30]]) {
      const x = rect.x + dx, y = rect.y + dy;
      if (!document.elementFromPoint(x, y)?.closest('[data-graph-node]')) return { x, y };
    }
    return null;
  });
  assert(point, 'Fixture must expose graph background for dragging');
  await page.mouse.move(point.x, point.y);
  await page.mouse.down();
  await page.mouse.move(point.x + 90, point.y + 70, { steps: 5 });
  await page.mouse.up();
  const afterDrag = await viewport.evaluate((element) => ({ left: element.scrollLeft, top: element.scrollTop }));
  assert(afterDrag.left < beforeDrag.left - 50 && afterDrag.top < beforeDrag.top - 40, 'Dragging the background must pan the scroll viewport');
  await page.locator('[data-graph-action="fit"]').click();
  assert.equal(await contained(), false);
  await page.locator('[data-graph-tab="nodes"]').click();
  const listed = page.locator(`[data-graph-evidence] [data-graph-select="${farId}"]`);
  while (await listed.count() === 0) await page.locator('[data-graph-action="page-next"]').click();
  await listed.click();
  assert.equal(await contained(), true, 'Selecting an offscreen node from the list must bring it into view');
  const [, depth, index] = /^DENSE_(\d)_(\d+)$/.exec(farId);
  await page.locator('[data-graph-inspector]').getByText(`Context for dense node ${depth}-${Number(index)}.`, { exact: true }).waitFor();
  assert.equal(requests.length, initialRequests, 'Scrolling, panning and local node pages must not fetch stock data');
  if (process.env.STOCKGRAPH_SCREENSHOTS) {
    const artifacts = path.resolve(frontend, '../artifacts');
    await mkdir(artifacts, { recursive: true });
    await page.locator('#stock-connections').screenshot({ path: path.join(artifacts, 'graph-explorer-dense-selected.png') });
  }
  await unchanged();
});

test('rearrange changes the constellation locally while reset restores its original seeded positions', async (t) => {
  const { page, requests, unchanged } = await fixture(t, { dense: true });
  await page.locator('[data-graph-action="hop"][data-hops="3"]').click();
  await page.waitForFunction(() => document.querySelectorAll('svg[data-graph-canvas] [data-graph-node]').length === 45);
  const positions = () => page.locator('svg[data-graph-canvas] [data-graph-node]').evaluateAll((nodes) => Object.fromEntries(nodes.map((node) => [node.dataset.graphNode, node.getAttribute('transform')]).sort(([a], [b]) => a.localeCompare(b))));
  const original = await positions();
  const count = requests.length;
  await page.locator('[data-graph-action="shuffle"]').click();
  const shuffled = await positions();
  assert.notDeepEqual(shuffled, original, 'Rearrange must change the neighboring node positions');
  assert.equal(shuffled.RELIANCE, original.RELIANCE, 'The selected stock remains at the center');
  await page.locator('[data-graph-action="fit"]').click();
  assert.deepEqual(await positions(), original, 'Reset must return to the original seed');
  assert.equal(requests.length, count, 'Rearranging the canvas must not refetch stock or graph data');
  await unchanged();
});

test('a slower old hop response cannot overwrite a newer selected hop', async (t) => {
  let release;
  let requested;
  const entered = new Promise((resolve) => { requested = resolve; });
  const delayed = new Promise((resolve) => { release = resolve; });
  t.after(() => release());
  const { page, unchanged } = await fixture(t, { connections: async ({ url, fulfill }) => {
    if (url.searchParams.get('hops') === '2') {
      requested();
      await delayed;
      await fulfill(responseFor(url));
      return true;
    }
    return false;
  } });
  await page.locator('[data-graph-action="hop"][data-hops="2"]').click();
  await entered;
  await page.locator('[data-graph-action="hop"][data-hops="3"]').click();
  await page.locator('svg[data-graph-canvas] [data-graph-node="TATASTEEL"]').waitFor();
  release();
  await page.waitForTimeout(150);
  assert.equal(await page.locator('svg[data-graph-canvas] [data-graph-node="TATASTEEL"]').count(), 1);
  assert.equal(await page.locator('[data-graph-action="hop"][data-hops="3"]').getAttribute('aria-pressed'), 'true');
  await unchanged();
});
