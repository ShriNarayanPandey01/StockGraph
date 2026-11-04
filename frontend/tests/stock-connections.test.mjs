import assert from 'node:assert/strict';
import test from 'node:test';
import { buildGraphLayout, mergeEvidence, nodeLabel, publicFields } from '../src/graph-model.js';

const node = (id, kind = 'Commodity', properties = {}) => ({ id, kind, properties });
const edge = (id, source, target) => ({ id, source, target, relation: 'RELATED_TO' });

function denseData() {
  const nodes = [node('Stock:RELIANCE', 'Stock')];
  const edges = [];
  const layers = [[nodes[0]]];
  for (let depth = 1; depth <= 3; depth++) {
    const layer = Array.from({ length: depth === 1 ? 14 : 15 }, (_, i) => node(`hop${depth}-${i}`, 'Commodity', { name: `Driver ${depth}-${i}` }));
    layer.forEach((item, i) => edges.push(edge(`e-${item.id}`, layers[depth - 1][i % layers[depth - 1].length].id, item.id)));
    layers.push(layer);
    nodes.push(...layer);
  }
  return { nodes, edges };
}

test('graph layout finds the selected stock and shortest undirected hop distances, preserving edge directions', () => {
  const data = {
    nodes: [node('third'), node('second'), node('first'), node('Stock:RELIANCE', 'Stock')],
    edges: [edge('one', 'first', 'Stock:RELIANCE'), edge('two', 'first', 'second'), edge('three', 'third', 'second')],
  };
  const original = JSON.stringify(data);
  const graph = buildGraphLayout(data, 'RELIANCE');
  assert.equal(graph.rootId, 'Stock:RELIANCE');
  assert.deepEqual(Object.fromEntries(graph.nodes.map(({ id, depth }) => [id, depth])), {
    'Stock:RELIANCE': 0, first: 1, second: 2, third: 3,
  });
  assert(graph.nodes.every(({ x, y }) => Number.isFinite(x) && Number.isFinite(y)));
  assert.equal(graph.edges[0].source, 'first');
  assert.equal(graph.edges[0].target, 'Stock:RELIANCE');
  assert.equal(JSON.stringify(data), original, 'Layout must not mutate API data');
});

test('cycles use shortest distance; duplicate identities and dangling edges do not create visual nodes', () => {
  const graph = buildGraphLayout({
    nodes: [node('root', 'Stock', { ticker: 'RELIANCE' }), node('first'), node('second'), node('second')],
    edges: [edge('one', 'root', 'first'), edge('two', 'first', 'second'), edge('shortcut', 'second', 'root'), edge('one', 'root', 'first'), edge('dangling', 'root', 'missing')],
  }, 'RELIANCE');
  assert.equal(graph.rootId, 'root');
  assert.equal(graph.nodes.length, 3);
  assert.equal(graph.edges.length, 3);
  assert.equal(graph.nodes.find(({ id }) => id === 'second').depth, 1);
});

test('empty graph has a finite viewport and no nodes', () => {
  const graph = buildGraphLayout({}, 'RELIANCE');
  assert.deepEqual(graph.nodes, []);
  assert.deepEqual(graph.edges, []);
  assert(Number.isFinite(graph.span));
});

test('dense neighborhoods grow the canvas and keep nodes spaced apart at the default scale', () => {
  const data = denseData();
  const layout = buildGraphLayout(data, 'RELIANCE', 3);
  assert.equal(layout.nodes.length, 45);
  assert(layout.width > 1000 && layout.height > 1000, 'Dense graphs must gain canvas space instead of shrinking');
  for (let i = 0; i < layout.nodes.length; i++) {
    for (const other of layout.nodes.slice(i + 1)) {
      assert(Math.hypot(layout.nodes[i].x - other.x, layout.nodes[i].y - other.y) >= 80, 'Default node centers must remain separated');
    }
  }
  assert(layout.nodes.every(({ showLabel }) => showLabel), 'All nodes retain labels in a spacious layout');
  const close = buildGraphLayout(data, 'RELIANCE', 1);
  assert.equal(close.nodes.length, 15);
  assert(close.nodes.every(({ depth }) => depth <= 1));
});

test('constellation layout is seeded, stable under input reordering and spatially varied around its pinned stock', () => {
  const data = denseData();
  const positions = (layout) => Object.fromEntries(layout.nodes.map(({ id, x, y }) => [id, { x, y }]).sort(([a], [b]) => a.localeCompare(b)));
  const first = buildGraphLayout(data, 'RELIANCE', 3, 0);
  const repeated = buildGraphLayout(data, 'RELIANCE', 3, 0);
  const reordered = buildGraphLayout({ nodes: [...data.nodes].reverse(), edges: [...data.edges].reverse() }, 'RELIANCE', 3, 0);
  const shuffled = buildGraphLayout(data, 'RELIANCE', 3, 1);
  assert.deepEqual(positions(first), positions(repeated), 'Ordinary renders must preserve the constellation');
  assert.deepEqual(positions(first), positions(reordered), 'API ordering must not rearrange the graph');
  assert.notDeepEqual(positions(first), positions(shuffled), 'A new seed must produce another arrangement');
  const center = first.nodes.find(({ id }) => id === first.rootId);
  const shuffledCenter = shuffled.nodes.find(({ id }) => id === shuffled.rootId);
  assert.deepEqual({ x: center.x, y: center.y }, { x: first.width / 2, y: first.height / 2 });
  assert.deepEqual({ x: center.x, y: center.y }, { x: shuffledCenter.x, y: shuffledCenter.y }, 'Rearrange must keep the selected stock pinned');
  const neighbors = first.nodes.filter(({ depth }) => depth === 1);
  assert(new Set(neighbors.map(({ x }) => Math.round(x))).size >= 8, 'Neighbors must spread organically instead of sharing hop-column x positions');
  const distances = neighbors.map(({ x, y }) => Math.hypot(x - center.x, y - center.y));
  assert(Math.max(...distances) - Math.min(...distances) >= 80, 'Same-hop neighbors must not form a perfect ring');
  for (let i = 0; i < shuffled.nodes.length; i++) {
    for (const other of shuffled.nodes.slice(i + 1)) assert(Math.hypot(shuffled.nodes[i].x - other.x, shuffled.nodes[i].y - other.y) >= 80, 'Shuffled nodes must preserve usable spacing');
  }
});

test('node detail fields hide vectors and credentials while retaining evidence and business context', () => {
  const fields = publicFields({ name: 'Stock', business_summary: 'Context', profile_embedding: [1, 2], embedding: [3, 4], access_token: 'secret', password: 'secret', confidence: 0.9, missing: null });
  assert.deepEqual(fields, [['name', 'Stock'], ['business_summary', 'Context'], ['confidence', 0.9]]);
  assert.equal(nodeLabel(node('id', 'NewsEvent', { headline: 'An event headline' })), 'An event headline');
});

test('paginated evidence merges by identity and preserves previously loaded nodes and source citations', () => {
  const first = mergeEvidence({}, {
    nodes: [node('stock', 'Stock')], edges: [edge('one', 'stock', 'driver')],
    direct_news: [{ id: 'story', headline: 'News', citation: { url: 'https://example.test/story' } }],
  });
  const second = mergeEvidence(first, {
    nodes: [node('driver'), node('stock', 'Stock')], edges: [edge('one', 'stock', 'driver'), edge('two', 'driver', 'other')],
    direct_news: [{ id: 'story', headline: 'News', citation: { url: 'https://example.test/story' } }],
    indirect_news: [{ id: 'another', headline: 'Other news', citation: { url: 'https://example.test/other' } }],
  });
  assert.equal(second.nodes.length, 2);
  assert.equal(second.edges.length, 2);
  assert.equal(second.news.length, 2);
  assert.equal(second.news[0].citation.url, 'https://example.test/story');
  assert.equal(first.edges.length, 1, 'Previous pages must remain immutable');
});
