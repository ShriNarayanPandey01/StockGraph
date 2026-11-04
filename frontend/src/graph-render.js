import { escapeHtml as e } from './api.js';
import { PAGE_SIZE, edgeEndpoints, nodeLabel, publicFields, readable } from './graph-model.js';

export const safeUrl = (value) => { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : ''; } catch { return ''; } };
const kindClass = (kind) => ['Stock', 'Commodity', 'MacroFactor', 'Sector', 'NewsEvent'].includes(kind) ? kind : 'Other';
const titleCase = (text) => String(text).replaceAll('_', ' ').replace(/([a-z])([A-Z])/g, '$1 $2');
const fields = (values) => `<dl class="graph-properties">${publicFields(values).map(([key, value]) => `<dt>${e(titleCase(key))}</dt><dd>${e(readable(value))}</dd>`).join('')}</dl>`;

export function graphMarkup(model) {
  if (!model.nodes.length) return '<div class="connection-empty">No graph nodes are available for this window.</div>';
  const byId = new Map(model.nodes.map((n) => [n.id, n]));
  return `<svg data-graph-canvas role="group" aria-label="Scrollable stock connections. Drag the background or scroll to explore; select nodes for details." viewBox="0 0 ${model.width} ${model.height}" style="width:${model.width}px;height:${model.height}px"><defs><marker id="connection-arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"/></marker></defs><g data-graph-world><g class="connection-edges">${model.edges.map((edge, index) => {
    const a = byId.get(edge.source), b = byId.get(edge.target), points = edgeEndpoints(a, b);
    const coordinates = `x1="${points.x1}" y1="${points.y1}" x2="${points.x2}" y2="${points.y2}"`;
    return `<line data-graph-edge="${e(edge.id)}" ${coordinates} marker-end="url(#connection-arrow)"><title>${e(`${nodeLabel(a)} → ${nodeLabel(b)}: ${titleCase(edge.relation)}`)}</title></line>${index < 12 ? `<line class="connection-flow" data-graph-flow="${e(edge.id)}" ${coordinates} style="animation-delay:-${index % 8}s" aria-hidden="true"/>` : ''}`;
  }).join('')}</g>${model.nodes.map((node) => {
    const left = node.labelSide === 'left', anchor = left ? 'end' : 'start', labelX = left ? -16 : 16;
    const label = node.depth === 0 ? String(node.properties?.ticker || nodeLabel(node)) : nodeLabel(node);
    const width = Math.min(200, Math.max(65, label.length * 7 + 12));
    const rectX = left ? -16 - width : 16;
    return `<g class="connection-node kind-${kindClass(node.kind)} ${node.depth === 0 ? 'is-root' : ''}" data-graph-node="${e(node.id)}" transform="translate(${node.x} ${node.y})" role="button" tabindex="0" aria-label="${e(`${nodeLabel(node)}, ${titleCase(node.kind)}, ${node.depth} hops from ${model.rootId}`)}" aria-pressed="false"><title>${e(nodeLabel(node))}</title>${node.depth === 0 ? '<circle class="connection-root-halo" r="22"/>' : ''}<circle class="connection-node-hit" r="20"/>${node.kind === 'Stock' ? `<circle class="connection-node-dot" r="${node.depth === 0 ? 9 : 5}"/>` : '<path class="connection-node-dot" d="M 0 -5 L 5 0 L 0 5 L -5 0 Z"/>'}<rect class="connection-label-hit" x="${rectX}" y="-25" width="${width}" height="42"/><text class="connection-node-label" x="${labelX}" y="5" text-anchor="${anchor}">${e(label.slice(0, 28))}${label.length > 28 ? '…' : ''}</text><text class="connection-node-caption" x="${labelX}" y="-11" text-anchor="${anchor}">${e(titleCase(node.kind))} · ${node.depth === 0 ? 'Starting stock' : `${node.depth} hop${node.depth > 1 ? 's' : ''}`}</text></g>`;
  }).join('')}</g></svg>`;
}

export function inspectorMarkup(node, edges) {
  if (!node) return '<p>Select a node to inspect its information and relationships.</p>';
  const linked = edges.filter((edge) => edge.source === node.id || edge.target === node.id);
  const url = safeUrl(node.properties?.source_url);
  return `<span class="eyebrow">SELECTED NODE / ${e(titleCase(node.kind))}</span><h3>${e(nodeLabel(node))}</h3><p class="graph-node-id">${e(node.id)} · ${node.depth} hop${node.depth === 1 ? '' : 's'} from the stock</p>${url ? `<a class="ticker-link" href="${e(url)}" target="_blank" rel="noopener noreferrer">Read original source ↗</a>` : ''}${fields(node.properties)}<h4>Connected relationships (${linked.length})</h4>${linked.length ? linked.map((edge) => `<details class="graph-relationship"><summary>${e(titleCase(edge.relation))} <span>${edge.confidence == null ? '' : `${Math.round(edge.confidence * 100)}%`}</span></summary><p>${e(edge.source)} → ${e(edge.target)}</p><p>${e(edge.rationale || 'No rationale supplied.')}</p>${fields(edge.provenance)}</details>`).join('') : '<p>No relationships returned for this node.</p>'}`;
}

export function panelRows(tab, evidence, model) {
  if (tab === 'nodes') return model?.nodes || [];
  return tab === 'news' ? evidence.news || [] : evidence.edges || [];
}

export function evidenceMarkup(tab, rows, page) {
  const items = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  if (!items.length) return `<p class="connection-empty">No ${e(tab)} available in this window.</p>`;
  return `<ul class="connection-evidence-list">${items.map((item) => {
    if (tab === 'nodes') return `<li><button class="connection-node-row" data-graph-select="${e(item.id)}"><span class="tag">${e(item.kind)} · ${item.depth} HOP${item.depth === 1 ? '' : 'S'}</span><strong>${e(nodeLabel(item))}</strong><span>Inspect node →</span></button></li>`;
    if (tab === 'news') {
      const url = safeUrl(item.citation?.url || item.source_url);
      return `<li><span class="eyebrow">${e(item.impact)} · ${e(item.citation?.event_date || item.event_date || 'DATE UNAVAILABLE')}</span><h3>${e(item.citation?.title || item.headline || 'Related news')}</h3><p>${e(item.rationale || item.summary || '')}</p>${url ? `<a class="ticker-link" href="${e(url)}" target="_blank" rel="noopener noreferrer">${e(item.citation?.publisher || 'Read source')} ↗</a>` : ''}</li>`;
    }
    return `<li><span class="tag blue">${e(titleCase(item.relation))}</span><h3>${e(item.source)} <span>→</span> ${e(item.target)}</h3><p>${e(item.rationale || 'No rationale supplied.')}</p><span class="eyebrow">${item.confidence == null ? 'CONFIDENCE NOT AVAILABLE' : `${Math.round(item.confidence * 100)}% CONFIDENCE`}</span>${fields(item.provenance)}</li>`;
  }).join('')}</ul>`;
}

export function explorerShell() {
  return `<div class="connection-heading"><div><span class="eyebrow">CONNECTION EXPLORER</span><h2 id="connections-title">Follow the connections</h2><p>Choose a depth, then select a node to inspect its context.</p></div><div class="connection-depth" role="group" aria-label="Graph depth">${[1, 2, 3].map((hops) => `<button type="button" class="pill" data-graph-action="hop" data-hops="${hops}" aria-pressed="${hops === 1}">${hops} hop${hops > 1 ? 's' : ''}</button>`).join('')}</div></div><div class="connection-message" data-graph-message role="status"></div><div data-graph-error role="alert" hidden></div><div class="connection-layout"><div class="connection-stage"><div class="connection-stage-tools"><span class="eyebrow" data-graph-counts>LOADING CONNECTIONS</span><div role="group" aria-label="Graph view controls"><button type="button" data-graph-action="zoom-in" aria-label="Zoom in">+</button><button type="button" data-graph-action="zoom-out" aria-label="Zoom out">−</button><button type="button" data-graph-action="shuffle">Rearrange</button><button type="button" data-graph-action="fit">Reset view</button></div></div><div class="connection-viewport" data-graph-viewport aria-busy="true" tabindex="0" aria-label="Scrollable graph canvas. Use arrow keys, scroll, or drag to explore."><p class="connection-empty">Loading stock connections…</p></div><div class="connection-legend"><span><i class="kind-Stock"></i>Stock</span><span><i class="kind-Commodity"></i>Commodity</span><span><i class="kind-MacroFactor"></i>Macro</span><span><i class="kind-Sector"></i>Sector</span><span><i class="kind-NewsEvent"></i>News</span><small>Scroll or drag the background to explore · Ctrl + scroll to zoom</small></div></div><aside class="connection-inspector" data-graph-inspector tabindex="0" aria-label="Selected node information"><p>Select a node to inspect it.</p></aside></div><section class="connection-evidence" aria-label="Connection information"><div class="connection-evidence-top"><div class="connection-tabs" role="group" aria-label="Connection information type">${['relationships', 'news', 'nodes'].map((tab) => `<button type="button" data-graph-tab="${tab}" aria-pressed="${tab === 'relationships'}">${tab[0].toUpperCase() + tab.slice(1)}</button>`).join('')}</div><span class="eyebrow" data-evidence-count></span></div><div class="connection-evidence-scroll" data-graph-evidence tabindex="0" aria-label="Paginated connection information"><p class="connection-empty">Loading information…</p></div><div class="connection-pagination" aria-label="Connection information pagination"><button type="button" class="pill" data-graph-action="page-prev" disabled>← Previous</button><span data-evidence-page role="status"></span><button type="button" class="pill" data-graph-action="page-next" disabled>Next page →</button></div><p class="connection-page-note" data-evidence-note role="status"></p></section>`;
}
