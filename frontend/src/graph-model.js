import { positionConstellation } from './constellation-layout.js';

export const PAGE_SIZE = 10;

export function buildGraphLayout(data, ticker, maxHops = Infinity, seed = 0) {
  const unique = new Map((data.nodes || []).map((node) => [node.id, { ...node }]));
  const rootId = unique.has(`Stock:${ticker}`) ? `Stock:${ticker}` : [...unique.values()].find((n) => n.kind === 'Stock' && n.properties?.ticker === ticker)?.id || unique.keys().next().value;
  const edges = [...new Map((data.edges || []).filter((edge) => unique.has(edge.source) && unique.has(edge.target)).map((edge) => [edge.id, edge])).values()];
  const distances = new Map(rootId ? [[rootId, 0]] : []);
  const adjacent = new Map([...unique.keys()].map((id) => [id, []]));
  for (const edge of edges) { adjacent.get(edge.source).push(edge.target); adjacent.get(edge.target).push(edge.source); }
  const queue = rootId ? [rootId] : [];
  for (let i = 0; i < queue.length; i++) {
    for (const id of adjacent.get(queue[i])) if (!distances.has(id)) { distances.set(id, distances.get(queue[i]) + 1); queue.push(id); }
  }
  const rings = new Map();
  for (const node of unique.values()) {
    if (!distances.has(node.id) || distances.get(node.id) > maxHops) continue;
    node.depth = distances.get(node.id);
    const ring = rings.get(node.depth) || []; ring.push(node); rings.set(node.depth, ring);
  }
  const nodes = [...rings.values()].flat();
  const visible = new Set(nodes.map((node) => node.id));
  const links = edges.filter((edge) => visible.has(edge.source) && visible.has(edge.target));
  const { width, height } = positionConstellation(nodes, links, rootId, seed);
  return { nodes, edges: links, rootId, width, height, span: Math.max(width, height) / 2 };
}

export function edgeEndpoints(a, b) {
  const dx = b.x - a.x, dy = b.y - a.y, distance = Math.hypot(dx, dy) || 1;
  const start = a.depth === 0 ? 14 : 8, end = b.depth === 0 ? 14 : 8;
  return { x1: a.x + dx / distance * start, y1: a.y + dy / distance * start, x2: b.x - dx / distance * end, y2: b.y - dy / distance * end };
}

export function nodeLabel(node) {
  return String(node.properties?.name || node.properties?.headline || node.properties?.title || node.properties?.ticker || node.id);
}

export function readable(value) {
  if (value == null) return 'Not available';
  if (typeof value === 'object') return Array.isArray(value) ? value.map(readable).join(' · ') : JSON.stringify(value);
  return String(value);
}

export function publicFields(properties = {}) {
  return Object.entries(properties).filter(([key, value]) => value != null && !/embedding|vector|password|token|metadata_json/i.test(key));
}

export function mergeEvidence(previous, incoming) {
  const dedup = (items, key) => [...new Map(items.map((item) => [key(item), item])).values()];
  return {
    nodes: dedup([...(previous.nodes || []), ...(incoming.nodes || [])], (n) => n.id),
    edges: dedup([...(previous.edges || []), ...(incoming.edges || [])], (e) => e.id),
    news: dedup([...(previous.news || []), ...(incoming.direct_news || []).map((n) => ({ ...n, impact: 'Direct' })), ...(incoming.indirect_news || []).map((n) => ({ ...n, impact: 'Indirect' }))], (n) => n.id || n.citation?.url || n.headline),
  };
}
