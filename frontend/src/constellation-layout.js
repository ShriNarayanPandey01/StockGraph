// A seeded layout keeps selection and pagination steady. Rearrange changes only
// the seed; relationship springs and label collisions still govern placement.
function hash(text) {
  let value = 2166136261;
  for (const char of text) value = Math.imul(value ^ char.charCodeAt(0), 16777619);
  return (value >>> 0) / 4294967296;
}

export function positionConstellation(input, edges, rootId, seed = 0) {
  const nodes = [...input].sort((a, b) => a.id.localeCompare(b.id));
  const width = Math.max(1100, Math.ceil(Math.sqrt(nodes.length) * 310));
  const height = Math.max(800, Math.ceil(Math.sqrt(nodes.length) * 245));
  const halfW = width / 2, halfH = height / 2;
  const root = nodes.find((node) => node.id === rootId);
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const random = (id, salt) => hash(`${rootId}|${seed}|${id}|${salt}`);
  const springs = [...new Map(edges.filter((edge) => byId.has(edge.source) && byId.has(edge.target)).map((edge) => {
    const pair = [edge.source, edge.target].sort().join('|');
    return [pair, [byId.get(edge.source), byId.get(edge.target), 230 + hash(pair) * 210]];
  })).entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, spring]) => spring);
  nodes.forEach((node, i) => {
    const angle = i * 2.39996 + random(node.id, 'angle') * 1.2;
    const radius = 120 * Math.sqrt(i + 1) * (.75 + random(node.id, 'radius') * .5);
    Object.assign(node, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius * .78, vx: 0, vy: 0 });
  });
  const pin = () => { if (root) { root.x = 0; root.y = 0; root.vx = 0; root.vy = 0; } };
  const bound = (node) => {
    node.x = Math.max(-halfW + 230, Math.min(halfW - 230, node.x));
    node.y = Math.max(-halfH + 100, Math.min(halfH - 100, node.y));
  };
  pin();
  for (let step = 0; step < 220; step++) {
    for (const node of nodes) { node.fx = -node.x * .001; node.fy = -node.y * .001; }
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j], dx = a.x - b.x || .01, dy = a.y - b.y || .01;
        const distance = Math.hypot(dx, dy), force = Math.min(8, 26000 / (distance * distance + 100));
        a.fx += dx / distance * force; a.fy += dy / distance * force;
        b.fx -= dx / distance * force; b.fy -= dy / distance * force;
        if (Math.abs(dx) < 225 && Math.abs(dy) < 108) {
          if ((225 - Math.abs(dx)) / 225 < (108 - Math.abs(dy)) / 108) {
            const push = Math.sign(dx) * (225 - Math.abs(dx)) * .1;
            a.fx += push; b.fx -= push;
          } else {
            const push = Math.sign(dy) * (108 - Math.abs(dy)) * .1;
            a.fy += push; b.fy -= push;
          }
        }
      }
    }
    for (const [a, b, length] of springs) {
      const dx = b.x - a.x, dy = b.y - a.y, distance = Math.hypot(dx, dy) || 1;
      const strength = (distance - length) * .005;
      a.fx += dx / distance * strength; a.fy += dy / distance * strength;
      b.fx -= dx / distance * strength; b.fy -= dy / distance * strength;
    }
    const cooling = .9 - step / 220 * .65;
    for (const node of nodes) {
      node.vx = (node.vx + node.fx * cooling) * .7;
      node.vy = (node.vy + node.fy * cooling) * .7;
      node.x += Math.max(-12, Math.min(12, node.vx));
      node.y += Math.max(-12, Math.min(12, node.vy));
      bound(node);
    }
    pin();
  }
  // Resolve the last label collisions after the forces settle. Keep the stock
  // pinned while neighbors move out of its label's way.
  for (let pass = 0; pass < 160; pass++) {
    let collisions = 0;
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j], dx = a.x - b.x || .01, dy = a.y - b.y || .01;
      const overlapX = 225 - Math.abs(dx), overlapY = 108 - Math.abs(dy);
      if (overlapX <= 0 || overlapY <= 0) continue;
      collisions++;
      const axis = overlapX / 225 < overlapY / 108 ? 'x' : 'y';
      const shift = Math.sign(axis === 'x' ? dx : dy) * ((axis === 'x' ? overlapX : overlapY) + .1);
      if (a === root) b[axis] -= shift;
      else if (b === root) a[axis] += shift;
      else { a[axis] += shift / 2; b[axis] -= shift / 2; }
      bound(a); bound(b); pin();
    }
    if (!collisions) break;
  }
  for (const node of nodes) {
    node.labelSide = node.x < -40 ? 'left' : 'right';
    node.x += halfW; node.y += halfH; node.showLabel = true;
    delete node.vx; delete node.vy; delete node.fx; delete node.fy;
  }
  return { width, height };
}
