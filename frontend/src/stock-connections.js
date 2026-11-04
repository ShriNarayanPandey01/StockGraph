import { api, escapeHtml as e } from './api.js';
import { PAGE_SIZE, buildGraphLayout, edgeEndpoints, mergeEvidence } from './graph-model.js';
import { evidenceMarkup, explorerShell, graphMarkup, inspectorMarkup, panelRows } from './graph-render.js';
import './stock-connections.css';

export function mountStockConnections(host, { ticker, window = 'LAST_6M', request = api }) {
  host.innerHTML = explorerShell();
  host.classList.add('connection-explorer');
  let disposed = false, graphVersion = 0, evidenceVersion = 0;
  let hops = 1, loadedHops = 1, asOf = null, model = null, selected = null;
  let evidence = {}, initialized = false, nextOffset = null, tab = 'relationships', busy = false, retryPage = false;
  let pages = { relationships: 0, news: 0, nodes: 0 };
  let zoom = 1, layoutSeed = 0, drag = null, suppressClick = false;
  const get = (selector) => host.querySelector(selector);
  const viewport = get('[data-graph-viewport]');
  const inspector = get('[data-graph-inspector]');
  const alive = () => !disposed && host.isConnected;
  const graphParams = (offset, depth) => {
    const params = new URLSearchParams({ window, offset: String(offset), limit: String(PAGE_SIZE) });
    if (depth != null) params.set('hops', String(depth));
    if (asOf != null) params.set('as_of_ts', String(asOf));
    return `/stocks/${encodeURIComponent(ticker)}/connections?${params}`;
  };
  function showError(error, page = false) {
    retryPage = page && !/snapshot expired/i.test(error.message || '');
    const target = get('[data-graph-error]');
    target.hidden = false;
    target.innerHTML = `<p>${e(error.message || 'Connections could not be loaded.')}</p><button type="button" class="pill" data-graph-action="retry">Retry connections</button>`;
  }
  function clearError() { get('[data-graph-error]').hidden = true; }
  function renderPanel(focus = false) {
    const rows = panelRows(tab, evidence, model);
    pages[tab] = Math.min(pages[tab], Math.max(0, Math.ceil(rows.length / PAGE_SIZE) - 1));
    const content = get('[data-graph-evidence]');
    const focusedAction = focus && document.activeElement?.dataset.graphAction;
    content.innerHTML = evidenceMarkup(tab, rows, pages[tab]);
    content.scrollTop = 0;
    get('[data-evidence-count]').textContent = `${rows.length} ${tab}${tab === 'nodes' ? ' in this graph' : ' loaded'}`;
    get('[data-evidence-page]').textContent = rows.length ? `Page ${pages[tab] + 1} · ${pages[tab] * PAGE_SIZE + 1}–${Math.min((pages[tab] + 1) * PAGE_SIZE, rows.length)}` : 'No results';
    get('[data-graph-action="page-prev"]').disabled = busy || pages[tab] === 0;
    get('[data-graph-action="page-next"]').disabled = busy || ((pages[tab] + 1) * PAGE_SIZE >= rows.length && (tab === 'nodes' || nextOffset == null));
    get('[data-graph-evidence]').setAttribute('aria-busy', String(busy));
    host.querySelectorAll('[data-graph-tab]').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.graphTab === tab)));
    if (focus && focusedAction && get(`[data-graph-action="${focusedAction}"]`)?.disabled) content.focus({ preventScroll: true });
  }
  function selectNode(id, focusInspector = false) {
    const node = model?.nodes.find((item) => item.id === id);
    if (!node) return;
    selected = id;
    viewport.classList.toggle('is-root-selected', node.depth === 0);
    const neighbors = new Set(model.edges.filter((edge) => edge.source === id || edge.target === id).flatMap((edge) => [edge.source, edge.target]));
    host.querySelectorAll('[data-graph-node]').forEach((element) => {
      element.classList.toggle('is-selected', element.dataset.graphNode === id);
      element.classList.toggle('is-neighbor', neighbors.has(element.dataset.graphNode));
      element.setAttribute('aria-pressed', String(element.dataset.graphNode === id));
    });
    host.querySelectorAll('[data-graph-edge]').forEach((element) => {
      const edge = model.edges.find((item) => item.id === element.dataset.graphEdge);
      element.classList.toggle('is-highlighted', edge.source === id || edge.target === id);
    });
    inspector.innerHTML = inspectorMarkup(node, model.edges);
    inspector.scrollTop = 0;
    if (focusInspector) { centerOnNode(id); inspector.focus({ preventScroll: true }); }
  }
  function centerOnNode(id) {
    const node = model?.nodes.find((item) => item.id === id);
    if (!node) return;
    viewport.scrollLeft = node.x * zoom - viewport.clientWidth / 2;
    viewport.scrollTop = node.y * zoom - viewport.clientHeight / 2;
  }
  function setZoom(next, anchorX = viewport.clientWidth / 2, anchorY = viewport.clientHeight / 2) {
    const svg = get('[data-graph-canvas]');
    if (!svg || !model) return;
    const x = (viewport.scrollLeft + anchorX) / zoom, y = (viewport.scrollTop + anchorY) / zoom;
    zoom = Math.min(3, Math.max(.25, next));
    svg.style.width = `${model.width * zoom}px`;
    svg.style.height = `${model.height * zoom}px`;
    viewport.scrollLeft = x * zoom - anchorX;
    viewport.scrollTop = y * zoom - anchorY;
  }
  async function loadGraph() {
    const version = ++graphVersion, requestedHops = hops;
    clearError();
    viewport.setAttribute('aria-busy', 'true');
    host.querySelectorAll('[data-graph-action="hop"]').forEach((button) => button.setAttribute('aria-pressed', String(Number(button.dataset.hops) === hops)));
    get('[data-graph-message]').textContent = `Loading ${requestedHops} hop${requestedHops > 1 ? 's' : ''}…`;
    try {
      let data;
      try { data = await request(graphParams(0, requestedHops)); }
      catch (error) {
        // An older Platform or Graph deployment can still serve its existing
        // context contract. Recover that graph during a rolling deployment.
        if (error.status !== 422 || !/only fixed .*parameters/i.test(error.message || '')) throw error;
        if (!alive() || version !== graphVersion) return;
        data = await request(graphParams(0));
      }
      if (!alive() || version !== graphVersion) return;
      const legacy = !data.exploration;
      const graph = data.exploration || data;
      loadedHops = legacy ? 1 : requestedHops;
      model = buildGraphLayout(graph, ticker, loadedHops, layoutSeed);
      host.querySelectorAll('[data-graph-action="hop"]').forEach((button) => {
        button.disabled = legacy && Number(button.dataset.hops) > 1;
        button.setAttribute('aria-pressed', String(Number(button.dataset.hops) === loadedHops));
      });
      asOf = data.pagination?.as_of_ts ?? asOf;
      if (!initialized) {
        evidence = mergeEvidence({}, data); nextOffset = data.pagination?.next_offset ?? null; initialized = true;
      }
      viewport.innerHTML = graphMarkup(model);
      zoom = 1;
      selectNode(model.nodes.some((node) => node.id === selected) ? selected : model.rootId);
      centerOnNode(selected || model.rootId);
      get('[data-graph-counts]').textContent = `${model.nodes.length} NODES · ${model.edges.length} CONNECTIONS · ${loadedHops} HOP${loadedHops > 1 ? 'S' : ''}`;
      get('[data-graph-message]').textContent = legacy
        ? 'Showing available one-hop connections. Deeper views are temporarily unavailable.'
        : graph.truncated
        ? `Showing a bounded graph (up to ${graph.node_limit || 200} nodes and ${graph.edge_limit || 500} connections). Choose fewer hops for a closer view.`
        : `Showing connections within ${loadedHops} hop${loadedHops > 1 ? 's' : ''} · ${window === 'LAST_1Y' ? 'Last year' : 'Last 6 months'} · ${data.processing_status || 'Available context'}`;
      renderPanel();
    } catch (error) {
      if (!alive() || version !== graphVersion) return;
      showError(error);
      get('[data-graph-message]').textContent = model ? `Showing the previous ${loadedHops}-hop graph.` : 'Connections are unavailable. Other stock information is still available below.';
      if (!model) viewport.innerHTML = '<p class="connection-empty">The graph could not be loaded. Retry this section.</p>';
    } finally { if (alive() && version === graphVersion) viewport.setAttribute('aria-busy', 'false'); }
  }
  async function nextPage() {
    if (busy) return;
    const rows = panelRows(tab, evidence, model);
    if ((pages[tab] + 1) * PAGE_SIZE < rows.length) { pages[tab]++; renderPanel(true); return; }
    if (nextOffset == null || tab === 'nodes') return;
    const version = ++evidenceVersion, activeTab = tab;
    busy = true; clearError(); renderPanel();
    get('[data-evidence-note]').textContent = 'Loading more information…';
    try {
      const data = await request(graphParams(nextOffset));
      if (!alive() || version !== evidenceVersion) return;
      evidence = mergeEvidence(evidence, data);
      nextOffset = data.pagination?.next_offset ?? null;
      const count = panelRows(activeTab, evidence, model).length;
      if ((pages[activeTab] + 1) * PAGE_SIZE < count) pages[activeTab]++;
      get('[data-evidence-note]').textContent = count === rows.length && nextOffset != null ? 'No additional items of this type in this batch. Continue to check the next batch.' : '';
    } catch (error) { if (alive() && version === evidenceVersion) { showError(error, true); get('[data-evidence-note]').textContent = 'The current page has been kept.'; } }
    finally { if (alive() && version === evidenceVersion) { busy = false; renderPanel(true); } }
  }
  function onClick(event) {
    if (suppressClick) { suppressClick = false; return; }
    const selectedNode = event.target.closest('[data-graph-node], [data-graph-select]');
    if (selectedNode) { selectNode(selectedNode.dataset.graphNode || selectedNode.dataset.graphSelect, Boolean(selectedNode.dataset.graphSelect)); return; }
    const tabButton = event.target.closest('[data-graph-tab]');
    if (tabButton) { tab = tabButton.dataset.graphTab; get('[data-evidence-note]').textContent = ''; renderPanel(); return; }
    const button = event.target.closest('[data-graph-action]');
    if (!button) return;
    const action = button.dataset.graphAction;
    if (action === 'hop') { hops = Number(button.dataset.hops); loadGraph(); }
    if (action === 'retry') {
      if (retryPage) nextPage();
      else { asOf = null; initialized = false; evidenceVersion++; busy = false; pages = { relationships: 0, news: 0, nodes: 0 }; loadGraph(); }
    }
    if (action === 'page-next') nextPage();
    if (action === 'page-prev') { pages[tab] = Math.max(0, pages[tab] - 1); renderPanel(true); }
    if (action === 'zoom-in' || action === 'zoom-out') setZoom(zoom * (action === 'zoom-in' ? 1.25 : .8));
    if ((action === 'fit' || action === 'shuffle') && model) {
      layoutSeed = action === 'fit' ? 0 : layoutSeed + 1;
      const selectedId = action === 'fit' ? model.rootId : selected;
      model = buildGraphLayout(model, ticker, loadedHops, layoutSeed);
      viewport.innerHTML = graphMarkup(model); zoom = 1;
      selectNode(selectedId || model.rootId); centerOnNode(model.rootId);
    }
  }
  function onKey(event) {
    const node = event.target.closest('[data-graph-node]');
    if (node && ['Enter', ' '].includes(event.key)) { event.preventDefault(); selectNode(node.dataset.graphNode); }
    if (event.target === viewport) {
      const steps = { ArrowLeft: [-120, 0], ArrowRight: [120, 0], ArrowUp: [0, -120], ArrowDown: [0, 120] };
      if (steps[event.key]) { event.preventDefault(); viewport.scrollBy(...steps[event.key]); }
      if (event.key === 'Home') { event.preventDefault(); centerOnNode(model?.rootId); }
    }
  }
  function point(event, svg) {
    const p = svg.createSVGPoint(); p.x = event.clientX; p.y = event.clientY;
    return p.matrixTransform(svg.getScreenCTM().inverse());
  }
  function onPointerDown(event) {
    const svg = event.target.closest('[data-graph-canvas]');
    if (!svg || event.button !== 0 || !model) return;
    const id = event.target.closest('[data-graph-node]')?.dataset.graphNode;
    const node = model.nodes.find((item) => item.id === id);
    drag = { svg, pointerId: event.pointerId, origin: point(event, svg), clientX: event.clientX, clientY: event.clientY, node, x: node?.x, y: node?.y, scrollLeft: viewport.scrollLeft, scrollTop: viewport.scrollTop, moved: false };
    svg.setPointerCapture(event.pointerId);
  }
  function onPointerMove(event) {
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (Math.hypot(event.clientX - drag.clientX, event.clientY - drag.clientY) > 4) drag.moved = true;
    if (!drag.moved) return;
    const current = point(event, drag.svg), dx = current.x - drag.origin.x, dy = current.y - drag.origin.y;
    if (drag.node) {
      drag.node.x = drag.x + dx; drag.node.y = drag.y + dy;
      host.querySelectorAll('[data-graph-node]').forEach((element) => { if (element.dataset.graphNode === drag.node.id) element.setAttribute('transform', `translate(${drag.node.x} ${drag.node.y})`); });
      const byId = new Map(model.nodes.map((node) => [node.id, node]));
      host.querySelectorAll('[data-graph-edge], [data-graph-flow]').forEach((element) => {
        const edge = model.edges.find((item) => item.id === (element.dataset.graphEdge || element.dataset.graphFlow)), a = byId.get(edge.source), b = byId.get(edge.target);
        for (const [key, value] of Object.entries(edgeEndpoints(a, b))) element.setAttribute(key, value);
      });
    } else {
      viewport.scrollLeft = drag.scrollLeft - (event.clientX - drag.clientX);
      viewport.scrollTop = drag.scrollTop - (event.clientY - drag.clientY);
    }
  }
  function onPointerUp(event) {
    if (!drag || drag.pointerId !== event.pointerId) return;
    suppressClick = drag.moved;
    if (!drag.moved && drag.node) selectNode(drag.node.id);
    if (drag.svg.hasPointerCapture(event.pointerId)) drag.svg.releasePointerCapture(event.pointerId);
    drag = null;
  }
  const handlers = { click: onClick, keydown: onKey, pointerdown: onPointerDown, pointermove: onPointerMove, pointerup: onPointerUp, pointercancel: onPointerUp };
  function onWheel(event) {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    const bounds = viewport.getBoundingClientRect();
    setZoom(zoom * Math.exp(-event.deltaY * .002), event.clientX - bounds.left, event.clientY - bounds.top);
  }
  viewport.addEventListener('wheel', onWheel, { passive: false });
  for (const [type, handler] of Object.entries(handlers)) host.addEventListener(type, handler);
  loadGraph();
  return () => { disposed = true; graphVersion++; evidenceVersion++; viewport.removeEventListener('wheel', onWheel); for (const [type, handler] of Object.entries(handlers)) host.removeEventListener(type, handler); };
}
