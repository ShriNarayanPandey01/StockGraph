import React, { useEffect, useRef, useState } from 'react';
import { GraphEntity } from '../../types/graph';
import { getNodeImage } from '../../data/nodeImages';

interface ConstellationCanvasProps {
  activeEntity: GraphEntity | null;
  onSelectEntity: (id: string) => void;
  onOpenDetailedView: () => void;
  onDimensionsChange?: (w: number, h: number) => void;
}

interface DynamicNode {
  id: string;
  title: string;
  avatar: string;
  color: string;
  type: 'Stock' | 'Commodity' | 'Macro' | 'News' | 'Sector' | 'Star';
  neighbors: string[];
  x: number;
  y: number;
  vx: number;
  vy: number;
  homeX: number;
  homeY: number;
  radius: number;
  baseAlpha: number;
  transition: number; // 0.0 = grey dot, 1.0 = fully blossomed highlighted node/image
}

// 33 Canonical Indian Market Entities
const CANONICAL_CONFIGS: {
  id: string;
  title: string;
  avatar: string;
  color: string;
  type: 'Stock' | 'Commodity' | 'Macro' | 'News';
  neighbors: string[];
}[] = [
  // --- Cluster 0: Metals & Mining ---
  {
    id: 'TATASTEEL',
    title: 'Tata Steel Limited',
    avatar: 'TS',
    color: '#38bdf8',
    type: 'Stock',
    neighbors: ['COKING_COAL', 'HRC_STEEL', 'JSWSTEEL', 'CHINA_STIMULUS'],
  },
  {
    id: 'COKING_COAL',
    title: 'Hard Coking Coal',
    avatar: 'COAL',
    color: '#f97316',
    type: 'Commodity',
    neighbors: ['TATASTEEL', 'HRC_STEEL', 'JSWSTEEL'],
  },
  {
    id: 'HRC_STEEL',
    title: 'Hot Rolled Coil Steel',
    avatar: 'HRC',
    color: '#38bdf8',
    type: 'Commodity',
    neighbors: ['TATASTEEL', 'MARUTI', 'LT', 'CHINA_STIMULUS'],
  },
  {
    id: 'JSWSTEEL',
    title: 'JSW Steel Limited',
    avatar: 'JSW',
    color: '#0284c7',
    type: 'Stock',
    neighbors: ['COKING_COAL', 'HRC_STEEL', 'CHINA_STIMULUS', 'TATASTEEL'],
  },
  {
    id: 'CHINA_STIMULUS',
    title: 'China Infrastructure Stimulus',
    avatar: 'NEWS',
    color: '#10b981',
    type: 'News',
    neighbors: ['TATASTEEL', 'HRC_STEEL', 'JSWSTEEL', 'COPPER'],
  },
  {
    id: 'COPPER',
    title: 'Copper Cathode LME',
    avatar: 'Cu',
    color: '#ea580c',
    type: 'Commodity',
    neighbors: ['LT', 'CHINA_STIMULUS'],
  },

  // --- Cluster 1: Energy & Petrochemicals ---
  {
    id: 'RELIANCE',
    title: 'Reliance Industries Ltd',
    avatar: 'RIL',
    color: '#38bdf8',
    type: 'Stock',
    neighbors: ['BRENT_CRUDE', 'USD_INR_FX', 'TELECOM_TARIFF', 'NATURAL_GAS'],
  },
  {
    id: 'BRENT_CRUDE',
    title: 'Brent Crude Benchmark',
    avatar: 'CRUDE',
    color: '#f97316',
    type: 'Commodity',
    neighbors: ['RELIANCE', 'ASIANPAINTS', 'USD_INR_FX'],
  },
  {
    id: 'NATURAL_GAS',
    title: 'Natural Gas Henry Hub',
    avatar: 'GAS',
    color: '#38bdf8',
    type: 'Commodity',
    neighbors: ['RELIANCE', 'ASIANPAINTS'],
  },
  {
    id: 'USD_INR_FX',
    title: 'USD/INR FX Rate',
    avatar: 'FX',
    color: '#38bdf8',
    type: 'Macro',
    neighbors: ['INFY', 'TCS', 'RELIANCE', 'SUNPHARMA', 'GOLD_MCX'],
  },
  {
    id: 'TELECOM_TARIFF',
    title: 'Mobile Tariff Revision',
    avatar: 'JIO',
    color: '#10b981',
    type: 'News',
    neighbors: ['RELIANCE', 'BHARTIARTL'],
  },
  {
    id: 'ASIANPAINTS',
    title: 'Asian Paints Limited',
    avatar: 'PAINT',
    color: '#f43f5e',
    type: 'Stock',
    neighbors: ['BRENT_CRUDE', 'USD_INR_FX', 'NATURAL_GAS'],
  },

  // --- Cluster 2: Banking & Monetary Rates ---
  {
    id: 'HDFCBANK',
    title: 'HDFC Bank Limited',
    avatar: 'HDFC',
    color: '#38bdf8',
    type: 'Stock',
    neighbors: ['RBI_REPO_RATE', 'INDIA_10Y_YIELD', 'LDR_COMPLIANCE', 'FII_DII_FLOWS'],
  },
  {
    id: 'ICICIBANK',
    title: 'ICICI Bank Limited',
    avatar: 'ICICI',
    color: '#f97316',
    type: 'Stock',
    neighbors: ['RBI_REPO_RATE', 'INDIA_10Y_YIELD', 'HDFCBANK', 'FII_DII_FLOWS'],
  },
  {
    id: 'SBIN',
    title: 'State Bank of India',
    avatar: 'SBIN',
    color: '#0284c7',
    type: 'Stock',
    neighbors: ['GOVT_CAPEX_SPEND', 'INDIA_10Y_YIELD', 'RBI_REPO_RATE'],
  },
  {
    id: 'BAJFINANCE',
    title: 'Bajaj Finance Limited',
    avatar: 'BAJ',
    color: '#3b82f6',
    type: 'Stock',
    neighbors: ['RBI_REPO_RATE', 'INDIA_10Y_YIELD'],
  },
  {
    id: 'RBI_REPO_RATE',
    title: 'RBI Repo Rate (6.5%)',
    avatar: 'RBI',
    color: '#a855f7',
    type: 'Macro',
    neighbors: ['HDFCBANK', 'ICICIBANK', 'BAJFINANCE', 'INDIA_10Y_YIELD'],
  },
  {
    id: 'INDIA_10Y_YIELD',
    title: 'India 10Y Benchmark (7.15%)',
    avatar: '10Y',
    color: '#a855f7',
    type: 'Macro',
    neighbors: ['HDFCBANK', 'SBIN', 'ICICIBANK', 'RBI_REPO_RATE'],
  },
  {
    id: 'LDR_COMPLIANCE',
    title: 'Loan-to-Deposit Glidepath',
    avatar: 'LDR',
    color: '#10b981',
    type: 'News',
    neighbors: ['HDFCBANK'],
  },
  {
    id: 'FII_DII_FLOWS',
    title: 'Institutional Equity Flows',
    avatar: 'FLOWS',
    color: '#38bdf8',
    type: 'Macro',
    neighbors: ['HDFCBANK', 'ICICIBANK', 'ITC'],
  },

  // --- Cluster 3: Infrastructure, Auto & Capex ---
  {
    id: 'LT',
    title: 'Larsen & Toubro Ltd',
    avatar: 'LT',
    color: '#22c55e',
    type: 'Stock',
    neighbors: ['GOVT_CAPEX_SPEND', 'HRC_STEEL', 'ALUMINIUM', 'COPPER'],
  },
  {
    id: 'GOVT_CAPEX_SPEND',
    title: 'Govt Infrastructure Capex',
    avatar: 'CAPEX',
    color: '#10b981',
    type: 'Macro',
    neighbors: ['LT', 'SBIN'],
  },
  {
    id: 'MARUTI',
    title: 'Maruti Suzuki India',
    avatar: 'MSIL',
    color: '#6366f1',
    type: 'Stock',
    neighbors: ['HRC_STEEL', 'ALUMINIUM', 'USD_INR_FX'],
  },
  {
    id: 'ALUMINIUM',
    title: 'Aluminium Primary Ingot',
    avatar: 'AL',
    color: '#94a3b8',
    type: 'Commodity',
    neighbors: ['MARUTI', 'LT'],
  },

  // --- Cluster 4: Global Tech & US Fed ---
  {
    id: 'INFY',
    title: 'Infosys Limited',
    avatar: 'INFY',
    color: '#0284c7',
    type: 'Stock',
    neighbors: ['US_FED_RATE', 'USD_INR_FX', 'TCS'],
  },
  {
    id: 'TCS',
    title: 'Tata Consultancy Services',
    avatar: 'TCS',
    color: '#818cf8',
    type: 'Stock',
    neighbors: ['US_FED_RATE', 'USD_INR_FX', 'INFY'],
  },
  {
    id: 'US_FED_RATE',
    title: 'US Federal Funds Rate (5.25%)',
    avatar: 'FED',
    color: '#3b82f6',
    type: 'Macro',
    neighbors: ['INFY', 'TCS', 'USD_INR_FX'],
  },

  // --- Cluster 5: Consumer, FMCG & Retail ---
  {
    id: 'TITAN',
    title: 'Titan Company Limited',
    avatar: 'TITAN',
    color: '#eab308',
    type: 'Stock',
    neighbors: ['GOLD_MCX', 'INDIA_CPI'],
  },
  {
    id: 'GOLD_MCX',
    title: 'Gold MCX Futures',
    avatar: 'AU',
    color: '#eab308',
    type: 'Commodity',
    neighbors: ['TITAN', 'USD_INR_FX'],
  },
  {
    id: 'ITC',
    title: 'ITC Limited',
    avatar: 'ITC',
    color: '#eab308',
    type: 'Stock',
    neighbors: ['INDIA_CPI', 'FII_DII_FLOWS'],
  },
  {
    id: 'SUNPHARMA',
    title: 'Sun Pharmaceutical Ltd',
    avatar: 'SUN',
    color: '#ec4899',
    type: 'Stock',
    neighbors: ['USD_INR_FX', 'INDIA_CPI'],
  },
  {
    id: 'INDIA_CPI',
    title: 'India CPI Inflation (5.4%)',
    avatar: 'CPI',
    color: '#f43f5e',
    type: 'Macro',
    neighbors: ['RBI_REPO_RATE', 'ITC', 'TITAN'],
  },
  {
    id: 'BHARTIARTL',
    title: 'Bharti Airtel Limited',
    avatar: 'AIRTEL',
    color: '#ef4444',
    type: 'Stock',
    neighbors: ['TELECOM_TARIFF', 'USD_INR_FX'],
  },
];

// Mapping each node to its community cluster
const CLUSTER_MAP: Record<string, number> = {
  // 0: Metals & Mining
  TATASTEEL: 0,
  COKING_COAL: 0,
  HRC_STEEL: 0,
  JSWSTEEL: 0,
  CHINA_STIMULUS: 0,
  COPPER: 0,

  // 1: Energy & Petrochemicals
  RELIANCE: 1,
  BRENT_CRUDE: 1,
  NATURAL_GAS: 1,
  USD_INR_FX: 1,
  TELECOM_TARIFF: 1,
  ASIANPAINTS: 1,

  // 2: Banking & Monetary Rates
  HDFCBANK: 2,
  ICICIBANK: 2,
  SBIN: 2,
  BAJFINANCE: 2,
  RBI_REPO_RATE: 2,
  INDIA_10Y_YIELD: 2,
  LDR_COMPLIANCE: 2,
  FII_DII_FLOWS: 2,

  // 3: Infrastructure & Heavy Engineering
  LT: 3,
  GOVT_CAPEX_SPEND: 3,
  MARUTI: 3,
  ALUMINIUM: 3,

  // 4: Tech Exporters & US Fed
  INFY: 4,
  TCS: 4,
  US_FED_RATE: 4,

  // 5: Consumer, FMCG & Retail
  TITAN: 5,
  GOLD_MCX: 5,
  ITC: 5,
  SUNPHARMA: 5,
  INDIA_CPI: 5,
  BHARTIARTL: 5,
};

// Preloaded images cache
const PRELOADED_IMAGES: Record<string, HTMLImageElement> = {};
function getImage(id: string): HTMLImageElement {
  if (!PRELOADED_IMAGES[id]) {
    const img = new Image();
    img.src = getNodeImage(id);
    PRELOADED_IMAGES[id] = img;
  }
  return PRELOADED_IMAGES[id];
}

// Pre-warm all images
CANONICAL_CONFIGS.forEach((c) => getImage(c.id));

export const ConstellationCanvas: React.FC<ConstellationCanvasProps> = ({
  activeEntity,
  onSelectEntity,
  onOpenDetailedView,
  onDimensionsChange,
}) => {
  const activeEntityIdRef = useRef<string | null>(null);
  activeEntityIdRef.current = activeEntity?.id || null;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nodesRef = useRef<DynamicNode[]>([]);
  const mouseRef = useRef<{ x: number; y: number; isInside: boolean }>({ x: -1000, y: -1000, isInside: false });
  const prevMouseRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const mouseVelocityRef = useRef<{ vx: number; vy: number }>({ vx: 0, vy: 0 });
  const hoveredNodeIdRef = useRef<string | null>(null);
  const lastTimeRef = useRef<number>(performance.now());
  const [dimensions, setDimensions] = useState<{ width: number; height: number }>({ width: 0, height: 0 });

  const dimensionsChangeRef = useRef(onDimensionsChange);
  dimensionsChangeRef.current = onDimensionsChange;

  // Initialize nodes clustered together with their connected peers
  const initNodes = (w: number, h: number) => {
    const nodes: DynamicNode[] = [];

    // Thematic community cluster hubs distributed around the central search bar
    const clusterCenters = [
      { x: w * 0.22, y: h * 0.27 }, // 0: Metals (Top-Left)
      { x: w * 0.78, y: h * 0.27 }, // 1: Energy & Petrochem (Top-Right)
      { x: w * 0.20, y: h * 0.75 }, // 2: Banking & Rates (Bottom-Left)
      { x: w * 0.80, y: h * 0.75 }, // 3: Infra & Auto (Bottom-Right)
      { x: w * 0.50, y: h * 0.17 }, // 4: Tech & US Fed (Top-Center)
      { x: w * 0.50, y: h * 0.83 }, // 5: Consumer & FMCG (Bottom-Center)
    ];

    const clusterCounters: Record<number, number> = { 0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };

    CANONICAL_CONFIGS.forEach((cfg) => {
      const clusterIdx = CLUSTER_MAP[cfg.id] ?? 0;
      const center = clusterCenters[clusterIdx];
      const memberIdx = clusterCounters[clusterIdx]++;
      const memberCount = CANONICAL_CONFIGS.filter((c) => CLUSTER_MAP[c.id] === clusterIdx).length;

      // Arrange cluster members in tight cohesive orbits around their community center
      const angle = (memberIdx / Math.max(1, memberCount)) * Math.PI * 2 + 0.3;
      const spreadR = 48 + (memberIdx % 2) * 28;
      const hx = Math.max(50, Math.min(w - 50, center.x + Math.cos(angle) * spreadR));
      const hy = Math.max(50, Math.min(h - 50, center.y + Math.sin(angle) * spreadR));

      nodes.push({
        id: cfg.id,
        title: cfg.title,
        avatar: cfg.avatar,
        color: cfg.color,
        type: cfg.type,
        neighbors: cfg.neighbors,
        x: hx,
        y: hy,
        homeX: hx,
        homeY: hy,
        vx: (Math.random() - 0.5) * 0.15,
        vy: (Math.random() - 0.5) * 0.15,
        radius: 6,
        baseAlpha: 0.85,
        transition: 0.0, // starts fully at default grey dot
      });
    });

    // Ambient background stars for cosmic depth
    const ambientCount = 50;
    for (let i = 0; i < ambientCount; i++) {
      const sx = Math.random() * w;
      const sy = Math.random() * h;
      nodes.push({
        id: `star_${i}`,
        title: `Star ${i}`,
        avatar: '',
        color: '#64748b',
        type: 'Star',
        neighbors: [],
        x: sx,
        y: sy,
        homeX: sx,
        homeY: sy,
        vx: (Math.random() - 0.5) * 0.1,
        vy: (Math.random() - 0.5) * 0.1,
        radius: Math.random() * 1.6 + 0.6,
        baseAlpha: Math.random() * 0.35 + 0.12,
        transition: 0.0,
      });
    }

    nodesRef.current = nodes;
  };

  // ResizeObserver to fill container
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const container = canvas.parentElement;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = Math.floor(entry.contentRect.width);
        const h = Math.floor(entry.contentRect.height);
        if (w === 0 || h === 0) return;

        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = w * dpr;
        canvas.height = h * dpr;

        setDimensions((prev) => {
          if (prev.width === w && prev.height === h) return prev;
          if (nodesRef.current.length === 0) {
            initNodes(w, h);
          }
          if (dimensionsChangeRef.current) {
            dimensionsChangeRef.current(w, h);
          }
          return { width: w, height: h };
        });
      }
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // Mouse hover & motion tracking
  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || dimensions.width === 0 || dimensions.height === 0) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    // Track mouse velocity to impart fluid collective motion to all nodes
    const dx = mx - prevMouseRef.current.x;
    const dy = my - prevMouseRef.current.y;
    prevMouseRef.current = { x: mx, y: my };
    mouseVelocityRef.current.vx = dx * 0.06;
    mouseVelocityRef.current.vy = dy * 0.06;

    mouseRef.current = { x: mx, y: my, isInside: true };

    // Find closest node within proximity radius (44px) to trigger highlight
    let foundId: string | null = null;
    let minD = 44;
    for (const node of nodesRef.current) {
      if (node.type === 'Star') continue;
      const dist = Math.hypot(node.x - mx, node.y - my);
      if (dist < minD) {
        minD = dist;
        foundId = node.id;
      }
    }
    hoveredNodeIdRef.current = foundId;
  };

  const handleMouseLeave = () => {
    mouseRef.current.isInside = false;
    hoveredNodeIdRef.current = null;
    mouseVelocityRef.current = { vx: 0, vy: 0 };
  };

  // Click on ANY node opens the detailed view modal
  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || dimensions.width === 0 || dimensions.height === 0) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    for (const node of nodesRef.current) {
      const dist = Math.hypot(node.x - mx, node.y - my);
      const hitRadius = node.type !== 'Star' ? 32 : 18;
      if (dist < hitRadius) {
        if (node.type !== 'Star') {
          onSelectEntity(node.id);
          onOpenDetailedView();
          return;
        } else {
          let nearestCanonical: DynamicNode | null = null;
          let minD = Infinity;
          for (const cand of nodesRef.current) {
            if (cand.type !== 'Star') {
              const d = Math.hypot(cand.x - node.x, cand.y - node.y);
              if (d < minD) {
                minD = d;
                nearestCanonical = cand;
              }
            }
          }
          if (nearestCanonical) {
            onSelectEntity(nearestCanonical.id);
            onOpenDetailedView();
            return;
          }
        }
      }
    }
  };

  // Safe image rendering with guaranteed procedural vector fallback
  const drawImageSafe = (
    ctx: CanvasRenderingContext2D,
    id: string,
    x: number,
    y: number,
    radius: number,
    fallbackColor: string,
    fallbackAvatar: string
  ) => {
    const img = getImage(id);
    let rendered = false;

    if (img && img.complete && img.naturalWidth > 0 && img.naturalHeight > 0) {
      try {
        ctx.save();
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.clip();
        ctx.drawImage(img, x - radius, y - radius, radius * 2, radius * 2);
        ctx.restore();
        rendered = true;
      } catch {
        rendered = false;
      }
    }

    if (!rendered) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fillStyle = '#0f172a';
      ctx.fill();

      const grad = ctx.createRadialGradient(x, y, 2, x, y, radius);
      grad.addColorStop(0, fallbackColor + '44');
      grad.addColorStop(1, '#090d16');
      ctx.fillStyle = grad;
      ctx.fill();

      ctx.fillStyle = '#ffffff';
      ctx.font = `bold ${Math.max(9, Math.round(radius * 0.52))}px JetBrains Mono, monospace`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(fallbackAvatar || id.substring(0, 3), x, y);
      ctx.restore();
    }
  };

  // Main Animation Render Loop with 0.3s Smooth Transition
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animId: number;

    const render = () => {
      const now = performance.now();
      const dt = Math.min((now - lastTimeRef.current) / 1000, 0.1);
      lastTimeRef.current = now;

      // Exactly 0.3 seconds smooth animation transition rate
      const transitionStep = dt / 0.3;

      const w = dimensions.width;
      const h = dimensions.height;
      if (w === 0 || h === 0) {
        animId = requestAnimationFrame(render);
        return;
      }

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, h);

      // 1. Sleek Background: Deep Radial Gradient (NO GRID)
      const bgGrad = ctx.createRadialGradient(w / 2, h / 2, 60, w / 2, h / 2, Math.max(w, h) * 0.72);
      bgGrad.addColorStop(0, '#101524'); // Ambient midnight glow in center
      bgGrad.addColorStop(0.5, '#090c13'); // Deep slate-ink
      bgGrad.addColorStop(1, '#050608'); // Pure obsidian edges
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, w, h);

      const nodes = nodesRef.current;
      const hoveredId = hoveredNodeIdRef.current;

      // Fast lookup map for nodes
      const nodeMap = new Map<string, DynamicNode>();
      for (const n of nodes) {
        if (n.type !== 'Star') {
          nodeMap.set(n.id, n);
        }
      }

      const hoveredNode = hoveredId ? nodeMap.get(hoveredId) : null;
      const neighborIds = new Set<string>(hoveredNode ? hoveredNode.neighbors : []);

      // 2. Physics: Interactive Cursor Impulse & Connected Node Cohesion
      const mVel = mouseVelocityRef.current;
      const mouseIsInside = mouseRef.current.isInside;
      const mx = mouseRef.current.x;
      const my = mouseRef.current.y;

      for (const node of nodes) {
        // A. Impart collective cursor movement to ALL nodes
        if (Math.abs(mVel.vx) > 0.001 || Math.abs(mVel.vy) > 0.001) {
          node.vx += mVel.vx * 0.022;
          node.vy += mVel.vy * 0.022;
        }

        // B. Gentle fluid push if mouse goes near a node
        if (mouseIsInside) {
          const cdx = node.x - mx;
          const cdy = node.y - my;
          const cdist = Math.hypot(cdx, cdy);
          if (cdist < 130 && cdist > 0) {
            const push = (130 - cdist) * 0.00028;
            node.vx += (cdx / cdist) * push;
            node.vy += (cdy / cdist) * push;
          }
        }

        // C. Connected Nodes Stay Together: Spring attraction between connected pairs
        if (node.type !== 'Star') {
          for (const neighborId of node.neighbors) {
            const neighbor = nodeMap.get(neighborId);
            if (neighbor) {
              const ndx = neighbor.x - node.x;
              const ndy = neighbor.y - node.y;
              const ndist = Math.hypot(ndx, ndy);
              if (ndist > 110) {
                // Pull closer if drifting too far
                const pull = (ndist - 110) * 0.0003;
                node.vx += (ndx / ndist) * pull;
                node.vy += (ndy / ndist) * pull;
              } else if (ndist < 45 && ndist > 0) {
                // Repel gently so they don't overlap completely
                const repel = (45 - ndist) * 0.0005;
                node.vx -= (ndx / ndist) * repel;
                node.vy -= (ndy / ndist) * repel;
              }
            }
          }

          // D. Anchor lightly to home cluster center so constellations stay grouped
          const hdx = node.homeX - node.x;
          const hdy = node.homeY - node.y;
          node.vx += hdx * 0.00035;
          node.vy += hdy * 0.00035;
        }

        // Apply velocity with natural damping
        node.vx *= 0.94;
        node.vy *= 0.94;
        node.x += node.vx;
        node.y += node.vy;

        // Soft bounce boundaries
        const padding = node.type !== 'Star' ? 45 : 10;
        if (node.x < padding) {
          node.x = padding;
          node.vx = Math.abs(node.vx);
        } else if (node.x > w - padding) {
          node.x = w - padding;
          node.vx = -Math.abs(node.vx);
        }

        if (node.y < padding) {
          node.y = padding;
          node.vy = Math.abs(node.vy);
        } else if (node.y > h - padding) {
          node.y = h - padding;
          node.vy = -Math.abs(node.vy);
        }

        // E. Smooth 0.3s Transition Interpolation for each node
        const isHovered = node.id === hoveredId;
        const isNeighbor = neighborIds.has(node.id);
        const targetT = isHovered || isNeighbor ? 1.0 : 0.0;

        if (node.transition < targetT) {
          node.transition = Math.min(targetT, node.transition + transitionStep);
        } else if (node.transition > targetT) {
          node.transition = Math.max(targetT, node.transition - transitionStep);
        }
      }

      // Decay mouse velocity
      mVel.vx *= 0.88;
      mVel.vy *= 0.88;

      // 3. Ambient Micro-Star Interlinks
      for (let i = 0; i < nodes.length; i++) {
        if (nodes[i].type !== 'Star') continue;
        for (let j = i + 1; j < nodes.length; j++) {
          if (nodes[j].type !== 'Star') continue;
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist = Math.hypot(dx, dy);
          if (dist < 75) {
            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.strokeStyle = `rgba(148, 163, 184, ${0.06 * (1 - dist / 75)})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }

      // 4. Draw Straight Solid Lines to Neighbors with Smooth 0.3s Fade
      if (hoveredNode && hoveredNode.transition > 0.01) {
        for (const neighborId of hoveredNode.neighbors) {
          const neighborNode = nodeMap.get(neighborId);
          if (neighborNode && neighborNode.transition > 0.01) {
            const edgeT = Math.min(hoveredNode.transition, neighborNode.transition);

            ctx.save();
            ctx.beginPath();
            ctx.moveTo(hoveredNode.x, hoveredNode.y);
            ctx.lineTo(neighborNode.x, neighborNode.y);

            // Straight, solid line with vivid glow (NO dotted line)
            ctx.strokeStyle = neighborNode.color || '#38bdf8';
            ctx.lineWidth = 2.0 * edgeT;
            ctx.globalAlpha = edgeT;
            ctx.shadowColor = neighborNode.color || '#38bdf8';
            ctx.shadowBlur = 10 * edgeT;
            ctx.stroke();
            ctx.restore();
          }
        }
      }

      // 5. Draw All Nodes: Default GREY -> Smooth 0.3s Transition into Highlighted / Image Node
      for (const node of nodes) {
        const isHovered = node.id === hoveredId;
        const isNeighbor = neighborIds.has(node.id);
        const t = node.transition; // Smooth transition value [0.0 - 1.0]

        // ---- CASE A: Regular Ambient Star ----
        if (node.type === 'Star') {
          const starAlpha = hoveredId ? node.baseAlpha * 0.35 : node.baseAlpha;
          ctx.beginPath();
          ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(148, 163, 184, ${starAlpha})`;
          ctx.fill();
          continue;
        }

        // ---- CASE B: Connected Neighbor Node (Smooth 0.3s blossom from Grey to Image) ----
        if (isNeighbor || (t > 0.01 && !isHovered)) {
          // Radius smoothly expands from 6.0px (grey dot) to 22.0px (image circle)
          const currentRadius = 6.0 + (22.0 - 6.0) * t;

          // 1. Draw smooth grey base underneath when partially transitioned
          if (t < 0.99) {
            ctx.save();
            ctx.globalAlpha = 1.0 - t;
            ctx.beginPath();
            ctx.arc(node.x, node.y, 6.0, 0, Math.PI * 2);
            ctx.fillStyle = '#64748b';
            ctx.fill();
            ctx.restore();
          }

          // 2. Draw blossoming image and glowing border with smooth opacity `t`
          if (t > 0.02) {
            ctx.save();
            ctx.globalAlpha = t;

            // Outer glowing halo border in its vivid color
            ctx.beginPath();
            ctx.arc(node.x, node.y, currentRadius + 3 * t, 0, Math.PI * 2);
            ctx.strokeStyle = node.color || '#38bdf8';
            ctx.lineWidth = 2.2 * t;
            ctx.shadowColor = node.color || '#38bdf8';
            ctx.shadowBlur = 12 * t;
            ctx.stroke();
            ctx.shadowBlur = 0;

            // Safe image rendering
            drawImageSafe(ctx, node.id, node.x, node.y, currentRadius, node.color, node.avatar);

            // Tiny label pill below image node
            ctx.font = 'bold 9px JetBrains Mono, monospace';
            const text = node.id;
            const textW = ctx.measureText(text).width;
            ctx.fillStyle = 'rgba(11, 12, 14, 0.95)';
            ctx.fillRect(node.x - textW / 2 - 4, node.y + currentRadius + 4, textW + 8, 14);
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
            ctx.strokeRect(node.x - textW / 2 - 4, node.y + currentRadius + 4, textW + 8, 14);
            ctx.fillStyle = '#ffffff';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(text, node.x, node.y + currentRadius + 11);
            ctx.restore();
          }
        }
        // ---- CASE C: Hovered Focal Node (Smooth 0.3s blossom from Grey to Focal Highlight) ----
        else if (isHovered || (t > 0.01 && isHovered)) {
          // Radius smoothly expands from 6.0px to 24.0px
          const hoverRadius = 6.0 + (24.0 - 6.0) * t;

          ctx.save();
          // Outer pulsing glow aura in vivid color
          ctx.beginPath();
          ctx.arc(node.x, node.y, hoverRadius + 8 * t, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(56, 189, 248, ${0.12 * t})`;
          ctx.fill();
          ctx.strokeStyle = node.color || '#38bdf8';
          ctx.lineWidth = 1.5 * t;
          ctx.globalAlpha = t;
          ctx.stroke();

          // Safe image or avatar
          drawImageSafe(ctx, node.id, node.x, node.y, hoverRadius, node.color, node.avatar);

          // Prominent illuminated border
          ctx.beginPath();
          ctx.arc(node.x, node.y, hoverRadius, 0, Math.PI * 2);
          ctx.strokeStyle = node.color || '#38bdf8';
          ctx.lineWidth = 2.5 * t;
          ctx.shadowColor = node.color || '#38bdf8';
          ctx.shadowBlur = 16 * t;
          ctx.stroke();
          ctx.shadowBlur = 0;

          // Title label below
          ctx.font = 'bold 10px Inter, sans-serif';
          const label = node.title || node.id;
          const labelW = ctx.measureText(label).width;
          ctx.fillStyle = 'rgba(11, 12, 14, 0.92)';
          ctx.fillRect(node.x - labelW / 2 - 6, node.y + hoverRadius + 5, labelW + 12, 16);
          ctx.strokeStyle = node.color || '#38bdf8';
          ctx.strokeRect(node.x - labelW / 2 - 6, node.y + hoverRadius + 5, labelW + 12, 16);
          ctx.fillStyle = '#ffffff';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(label, node.x, node.y + hoverRadius + 13);
          ctx.restore();
        }
        // ---- CASE D: Default Canonical Node: SLEEK METALLIC GREY ----
        else {
          const alpha = hoveredId ? 0.25 : 0.85;
          const radius = 6.0;

          const defaultGrey = '#64748b'; // slate-500
          const defaultGreyHalo = 'rgba(100, 116, 139, 0.18)';

          // Subtle grey halo
          ctx.beginPath();
          ctx.arc(node.x, node.y, radius + 4, 0, Math.PI * 2);
          ctx.fillStyle = defaultGreyHalo;
          ctx.fill();

          // Solid celestial core in grey
          ctx.beginPath();
          ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
          ctx.fillStyle = defaultGrey;
          ctx.globalAlpha = alpha;
          ctx.fill();
          ctx.globalAlpha = 1.0;

          // Active selected entity indicator
          if (node.id === activeEntityIdRef.current) {
            ctx.beginPath();
            ctx.arc(node.x, node.y, radius + 6, 0, Math.PI * 2);
            ctx.strokeStyle = '#94a3b8';
            ctx.lineWidth = 1.4;
            ctx.stroke();
          }

          // Subtle grey label text next to node
          if (!hoveredId) {
            ctx.font = 'bold 8.5px JetBrains Mono, monospace';
            ctx.fillStyle = 'rgba(148, 163, 184, 0.65)';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText(node.avatar || node.id.substring(0, 3), node.x + radius + 4, node.y);
          }
        }
      }

      ctx.restore();
      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(animId);
  }, [dimensions]);

  return (
    <canvas
      ref={canvasRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      onClick={handleCanvasClick}
      className="absolute inset-0 w-full h-full cursor-pointer"
      style={{ touchAction: 'none' }}
    />
  );
};
