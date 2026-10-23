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
  hoverTransition: number; // 0.0 to 1.0 smooth hover line transition over 0.5s
  randomWeight: number; // Random sensitivity factor (0.5 to 1.4) for varied movement
  randomAngleOffset: number; // Random angle offset (-0.35 to 0.35 rad)
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
  TATASTEEL: 0,
  COKING_COAL: 0,
  HRC_STEEL: 0,
  JSWSTEEL: 0,
  CHINA_STIMULUS: 0,
  COPPER: 0,

  RELIANCE: 1,
  BRENT_CRUDE: 1,
  NATURAL_GAS: 1,
  USD_INR_FX: 1,
  TELECOM_TARIFF: 1,
  ASIANPAINTS: 1,

  HDFCBANK: 2,
  ICICIBANK: 2,
  SBIN: 2,
  BAJFINANCE: 2,
  RBI_REPO_RATE: 2,
  INDIA_10Y_YIELD: 2,
  LDR_COMPLIANCE: 2,
  FII_DII_FLOWS: 2,

  LT: 3,
  GOVT_CAPEX_SPEND: 3,
  MARUTI: 3,
  ALUMINIUM: 3,

  INFY: 4,
  TCS: 4,
  US_FED_RATE: 4,

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
  onOpenDetailedView: _onOpenDetailedView, // Kept in props interface but disabled on node click
  onDimensionsChange,
}) => {
  const selectedNodeIdRef = useRef<string | null>(activeEntity?.id || null);
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

  // Sync selected node with prop
  useEffect(() => {
    selectedNodeIdRef.current = activeEntity?.id || null;
  }, [activeEntity]);

  // Initialize nodes clustered together with their connected peers
  const initNodes = (w: number, h: number) => {
    const nodes: DynamicNode[] = [];

    // Thematic community cluster hubs distributed symmetrically around the central tagline
    const clusterCenters = [
      { x: w * 0.12, y: h * 0.22 }, // 0: Metals (Far Upper-Left)
      { x: w * 0.88, y: h * 0.22 }, // 1: Energy & Petrochem (Far Upper-Right)
      { x: w * 0.12, y: h * 0.72 }, // 2: Banking & Rates (Far Lower-Left)
      { x: w * 0.88, y: h * 0.72 }, // 3: Infra & Auto (Far Lower-Right)
      { x: w * 0.50, y: h * 0.10 }, // 4: Tech & US Fed (Top Orbit, well above tagline)
      { x: w * 0.50, y: h * 0.82 }, // 5: Consumer & FMCG (Bottom Orbit, below tagline)
    ];

    const textCx = w * 0.5;
    const textCy = h * 0.44;
    const textHalfW = Math.min(w * 0.42, 420);
    const textHalfH = 100;
    const safeMargin = 40;

    // Helper to ensure any node spawns strictly outside the hero text box
    const ensureOutsideText = (x: number, y: number): { x: number; y: number } => {
      const dx = x - textCx;
      const dy = y - textCy;
      if (Math.abs(dx) < textHalfW + safeMargin && Math.abs(dy) < textHalfH + safeMargin) {
        if (Math.abs(dx) / (textHalfW + safeMargin) > Math.abs(dy) / (textHalfH + safeMargin)) {
          const signX = dx >= 0 ? 1 : -1;
          return { x: textCx + signX * (textHalfW + safeMargin + 35), y };
        } else {
          const signY = dy >= 0 ? 1 : -1;
          return { x, y: textCy + signY * (textHalfH + safeMargin + 35) };
        }
      }
      return { x, y };
    };

    const clusterCounters: Record<number, number> = { 0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };

    CANONICAL_CONFIGS.forEach((cfg) => {
      const clusterIdx = CLUSTER_MAP[cfg.id] ?? 0;
      const center = clusterCenters[clusterIdx];
      const memberIdx = clusterCounters[clusterIdx]++;
      const memberCount = CANONICAL_CONFIGS.filter((c) => CLUSTER_MAP[c.id] === clusterIdx).length;

      // Arrange cluster members in tight cohesive orbits around their community center
      const angle = (memberIdx / Math.max(1, memberCount)) * Math.PI * 2 + 0.3;
      const spreadR = 48 + (memberIdx % 2) * 22;
      let rawX = Math.max(55, Math.min(w - 55, center.x + Math.cos(angle) * spreadR));
      let rawY = Math.max(55, Math.min(h - 55, center.y + Math.sin(angle) * spreadR));

      // Guarantee no canonical node is initialized within the hero text zone
      const safePos = ensureOutsideText(rawX, rawY);
      const hx = safePos.x;
      const hy = safePos.y;

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
        vx: (Math.random() - 0.5) * 0.08,
        vy: (Math.random() - 0.5) * 0.08,
        radius: 6,
        baseAlpha: 0.85,
        transition: 0.0,
        hoverTransition: 0.0,
        // Each node gets a randomized sensitivity factor and angle offset for organic varied movement
        randomWeight: 0.5 + Math.random() * 0.9,
        randomAngleOffset: (Math.random() - 0.5) * 0.7,
      });
    });

    // Ambient background stars for cosmic depth (guaranteed outside text zone)
    const ambientCount = 50;
    for (let i = 0; i < ambientCount; i++) {
      let sx = Math.random() * w;
      let sy = Math.random() * h;
      const safeStar = ensureOutsideText(sx, sy);
      sx = safeStar.x;
      sy = safeStar.y;

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
        vx: (Math.random() - 0.5) * 0.06,
        vy: (Math.random() - 0.5) * 0.06,
        radius: Math.random() * 1.6 + 0.6,
        baseAlpha: Math.random() * 0.35 + 0.12,
        transition: 0.0,
        hoverTransition: 0.0,
        randomWeight: 0.4 + Math.random() * 0.6,
        randomAngleOffset: (Math.random() - 0.5) * 0.6,
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

    // Track mouse velocity
    const dx = mx - prevMouseRef.current.x;
    const dy = my - prevMouseRef.current.y;
    prevMouseRef.current = { x: mx, y: my };
    mouseVelocityRef.current.vx = dx * 0.08;
    mouseVelocityRef.current.vy = dy * 0.08;

    mouseRef.current = { x: mx, y: my, isInside: true };

    // Find closest node within hover radius (40px)
    let foundId: string | null = null;
    let minD = 40;
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

  // Click on a node reveals its actual colorful relations on canvas
  // Detailed modal is disabled for now as explicitly requested
  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || dimensions.width === 0 || dimensions.height === 0) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    let clickedNodeId: string | null = null;

    for (const node of nodesRef.current) {
      const dist = Math.hypot(node.x - mx, node.y - my);
      const hitRadius = node.type !== 'Star' ? 32 : 18;
      if (dist < hitRadius) {
        if (node.type !== 'Star') {
          clickedNodeId = node.id;
          break;
        } else {
          // If clicked on an ambient star, find the nearest canonical entity
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
            clickedNodeId = nearestCanonical.id;
            break;
          }
        }
      }
    }

    if (clickedNodeId) {
      // Toggle or select the clicked node to show full colorful relations
      selectedNodeIdRef.current = clickedNodeId;
      onSelectEntity(clickedNodeId);
      // NOTE: onOpenDetailedView() is disabled for now per user instruction
    } else {
      // Deselect if clicked empty canvas area
      selectedNodeIdRef.current = null;
      onSelectEntity('');
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

  // Main Animation Render Loop
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

      // Exactly 0.5 seconds smooth transition rate for hover grey lines
      const hoverTransitionStep = dt / 0.5;

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

      // 1. Sleek Blackish Canvas Background: Pure Obsidian Void
      const bgGrad = ctx.createRadialGradient(w * 0.5, h * 0.44, 50, w * 0.5, h * 0.44, Math.max(w, h) * 0.85);
      bgGrad.addColorStop(0, '#0a0d14'); // Ambient midnight glow behind center text
      bgGrad.addColorStop(0.45, '#040507'); // Deep black
      bgGrad.addColorStop(1, '#000000'); // Pure obsidian black
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, w, h);

      const nodes = nodesRef.current;
      const hoveredId = hoveredNodeIdRef.current;
      const selectedId = selectedNodeIdRef.current;

      // Fast lookup map for nodes
      const nodeMap = new Map<string, DynamicNode>();
      for (const n of nodes) {
        if (n.type !== 'Star') {
          nodeMap.set(n.id, n);
        }
      }

      const selectedNode = selectedId ? nodeMap.get(selectedId) : null;
      const selectedNeighborIds = new Set<string>(selectedNode ? selectedNode.neighbors : []);

      // 2. Physics: Subtle celestial drift + proximity cursor response + stable non-oscillating constraints
      const mVel = mouseVelocityRef.current;
      const mouseIsInside = mouseRef.current.isInside;
      const mx = mouseRef.current.x;
      const my = mouseRef.current.y;
      const mouseSpeed = Math.hypot(mVel.vx, mVel.vy);

      // Hero text exclusion box parameters
      const textCx = w * 0.5;
      const textCy = h * 0.44;
      const textHalfW = Math.min(w * 0.42, 420);
      const textHalfH = 100;
      const safeBuffer = 28;
      const boxW = textHalfW + safeBuffer;
      const boxH = textHalfH + safeBuffer;

      for (const node of nodes) {
        // A. Minimal celestial breathing drift (subtle, tiny 1-2px organic float)
        const nodeHash = (node.id.charCodeAt(0) * 19 + (node.id.charCodeAt(1) || 7)) % 100;
        const driftT = now * 0.0006 + nodeHash;
        node.vx += Math.sin(driftT) * 0.003;
        node.vy += Math.cos(driftT * 0.85) * 0.003;

        // B. Minimal cursor response: ONLY nearby nodes within 125px move a tiny bit when cursor actively moves
        if (mouseIsInside && mouseSpeed > 0.02) {
          const cdx = node.x - mx;
          const cdy = node.y - my;
          const cdist = Math.hypot(cdx, cdy);
          const influenceRadius = 125;

          if (cdist < influenceRadius && cdist > 0) {
            const proximity = 1 - cdist / influenceRadius; // 1.0 at cursor, 0.0 at edge
            const weight = node.randomWeight; // Each nearby node has a unique sensitivity
            const angle = Math.atan2(cdy, cdx) + node.randomAngleOffset;

            // Very small, subtle displacement (max 3-5px deflection)
            const impulse = Math.min(mouseSpeed, 1.8) * 0.006 * proximity * weight;
            node.vx += Math.cos(angle) * impulse + mVel.vx * 0.003 * proximity * weight;
            node.vy += Math.sin(angle) * impulse + mVel.vy * 0.003 * proximity * weight;
          }
        }

        // C. Maintain cluster cohesion & firm anchor to home position
        if (node.type !== 'Star') {
          const myCluster = CLUSTER_MAP[node.id];
          for (const neighborId of node.neighbors) {
            const neighbor = nodeMap.get(neighborId);
            if (neighbor) {
              const neighborCluster = CLUSTER_MAP[neighborId];
              // Only apply gentle separation if two connected nodes in same cluster overlap tightly (< 32px)
              if (myCluster === neighborCluster) {
                const ndx = neighbor.x - node.x;
                const ndy = neighbor.y - node.y;
                const ndist = Math.hypot(ndx, ndy);
                if (ndist < 32 && ndist > 0) {
                  const repel = (32 - ndist) * 0.0001;
                  node.vx -= (ndx / ndist) * repel;
                  node.vy -= (ndy / ndist) * repel;
                }
              }
            }
          }

          // Firm, smooth anchor to home position so nodes remain in their curated spots
          const hdx = node.homeX - node.x;
          const hdy = node.homeY - node.y;
          node.vx += hdx * 0.003;
          node.vy += hdy * 0.003;
        } else {
          // Ambient stars also gently anchored to their cosmic coordinates
          const hdx = node.homeX - node.x;
          const hdy = node.homeY - node.y;
          node.vx += hdx * 0.002;
          node.vy += hdy * 0.002;
        }

        // D. Strict Hero Text Exclusion Zone: GUARANTEE NO NODE EVER OVERLAPS THE HEADLINE
        const tdx = node.x - textCx;
        const tdy = node.y - textCy;
        const overlapX = boxW - Math.abs(tdx);
        const overlapY = boxH - Math.abs(tdy);

        if (overlapX > 0 && overlapY > 0) {
          // Inside the text box: cleanly clamp to nearest boundary & zero out inward velocity
          if (overlapX < overlapY) {
            const signX = tdx >= 0 ? 1 : -1;
            node.x = textCx + signX * boxW;
            if (node.vx * signX < 0) {
              node.vx = 0;
            }
          } else {
            const signY = tdy >= 0 ? 1 : -1;
            node.y = textCy + signY * boxH;
            if (node.vy * signY < 0) {
              node.vy = 0;
            }
          }
        }

        // Velocity damping (critically damped so any movement settles quickly and smoothly)
        node.vx *= 0.88;
        node.vy *= 0.88;
        node.x += node.vx;
        node.y += node.vy;

        // Canvas outer boundary clamping
        const padding = node.type !== 'Star' ? 45 : 10;
        const bottomPadding = node.type !== 'Star' ? 88 : 15;

        if (node.x < padding) {
          node.x = padding;
          node.vx = Math.abs(node.vx) * 0.5;
        } else if (node.x > w - padding) {
          node.x = w - padding;
          node.vx = -Math.abs(node.vx) * 0.5;
        }

        if (node.y < padding) {
          node.y = padding;
          node.vy = Math.abs(node.vy) * 0.5;
        } else if (node.y > h - bottomPadding) {
          node.y = h - bottomPadding;
          node.vy = -Math.abs(node.vy) * 0.5;
        }

        // D. 0.3s Transition target: ONLY CLICKED/SELECTED node & its neighbors blossom into color!
        const isSelectedFocal = node.id === selectedId;
        const isSelectedNeighbor = selectedNeighborIds.has(node.id);
        const targetT = isSelectedFocal || isSelectedNeighbor ? 1.0 : 0.0;

        if (node.transition < targetT) {
          node.transition = Math.min(targetT, node.transition + transitionStep);
        } else if (node.transition > targetT) {
          node.transition = Math.max(targetT, node.transition - transitionStep);
        }

        // E. 0.5s Transition target for hover grey lines
        const isCurrentlyHovered = node.id === hoveredId && node.id !== selectedId;
        const targetHT = isCurrentlyHovered ? 1.0 : 0.0;

        if (node.hoverTransition < targetHT) {
          node.hoverTransition = Math.min(targetHT, node.hoverTransition + hoverTransitionStep);
        } else if (node.hoverTransition > targetHT) {
          node.hoverTransition = Math.max(targetHT, node.hoverTransition - hoverTransitionStep);
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

      // 4. ON HOVER: Draw SIMPLE GREYISH EDGES with 0.5s smooth transition & reduced transparency (higher contrast)
      for (const srcNode of nodes) {
        if (srcNode.hoverTransition > 0.005 && srcNode.id !== selectedId) {
          const hAlpha = srcNode.hoverTransition * 0.75; // Reduced transparency (0.75 max opacity for clear visibility)
          for (const neighborId of srcNode.neighbors) {
            const neighborNode = nodeMap.get(neighborId);
            if (neighborNode) {
              ctx.save();
              ctx.beginPath();
              ctx.moveTo(srcNode.x, srcNode.y);
              ctx.lineTo(neighborNode.x, neighborNode.y);

              // Solid, crisp light greyish edge with reduced transparency & 0.5s smooth fade
              ctx.strokeStyle = `rgba(226, 232, 240, ${hAlpha})`;
              ctx.lineWidth = 1.5;
              ctx.stroke();
              ctx.restore();
            }
          }
        }
      }

      // 5. ON CLICK: Draw THE ACTUAL RELATION COLORFUL EDGES for the selected node!
      if (selectedNode && selectedNode.transition > 0.01) {
        for (const neighborId of selectedNode.neighbors) {
          const neighborNode = nodeMap.get(neighborId);
          if (neighborNode && neighborNode.transition > 0.01) {
            const edgeT = Math.min(selectedNode.transition, neighborNode.transition);

            ctx.save();
            ctx.beginPath();
            ctx.moveTo(selectedNode.x, selectedNode.y);
            ctx.lineTo(neighborNode.x, neighborNode.y);

            // Vibrant colorful illuminated straight edge
            ctx.strokeStyle = neighborNode.color || '#38bdf8';
            ctx.lineWidth = 2.0 * edgeT;
            ctx.globalAlpha = edgeT;
            ctx.shadowColor = neighborNode.color || '#38bdf8';
            ctx.shadowBlur = 12 * edgeT;
            ctx.stroke();
            ctx.restore();
          }
        }
      }

      // 6. Draw All Nodes
      for (const node of nodes) {
        const isSelectedFocal = node.id === selectedId;
        const isSelectedNeighbor = selectedNeighborIds.has(node.id);
        const isHovered = node.id === hoveredId;
        const t = node.transition; // Smooth 0.3s transition [0.0 - 1.0]

        // ---- CASE A: Regular Ambient Star ----
        if (node.type === 'Star') {
          const starAlpha = selectedId ? node.baseAlpha * 0.35 : node.baseAlpha;
          ctx.beginPath();
          ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(148, 163, 184, ${starAlpha})`;
          ctx.fill();
          continue;
        }

        // ---- CASE B: Clicked Selected Focal Node (Shows full vibrant color + title) ----
        if (isSelectedFocal || (t > 0.01 && isSelectedFocal)) {
          const hoverRadius = 6.0 + (24.0 - 6.0) * t;

          ctx.save();
          // Outer pulsing glow aura in vivid brand color
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
        // ---- CASE C: Selected Neighbor Node (Blossoms into circular image on click) ----
        else if (isSelectedNeighbor || (t > 0.01 && !isSelectedFocal)) {
          const currentRadius = 6.0 + (22.0 - 6.0) * t;

          // Draw grey base when blending
          if (t < 0.99) {
            ctx.save();
            ctx.globalAlpha = 1.0 - t;
            ctx.beginPath();
            ctx.arc(node.x, node.y, 6.0, 0, Math.PI * 2);
            ctx.fillStyle = '#64748b';
            ctx.fill();
            ctx.restore();
          }

          // Blossoming image with glowing colored border
          if (t > 0.02) {
            ctx.save();
            ctx.globalAlpha = t;

            ctx.beginPath();
            ctx.arc(node.x, node.y, currentRadius + 3 * t, 0, Math.PI * 2);
            ctx.strokeStyle = node.color || '#38bdf8';
            ctx.lineWidth = 2.2 * t;
            ctx.shadowColor = node.color || '#38bdf8';
            ctx.shadowBlur = 12 * t;
            ctx.stroke();
            ctx.shadowBlur = 0;

            drawImageSafe(ctx, node.id, node.x, node.y, currentRadius, node.color, node.avatar);

            // Tiny label pill below image
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
        // ---- CASE D: Default Canonical Node: GREY (with subtle focus ring on hover) ----
        else {
          const alpha = selectedId ? 0.25 : 0.85;
          const radius = 6.0;

          // Subtle grey halo
          ctx.beginPath();
          ctx.arc(node.x, node.y, radius + 4, 0, Math.PI * 2);
          ctx.fillStyle = isHovered ? 'rgba(203, 213, 225, 0.3)' : 'rgba(100, 116, 139, 0.18)';
          ctx.fill();

          // Solid celestial core in grey
          ctx.beginPath();
          ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
          ctx.fillStyle = isHovered ? '#94a3b8' : '#64748b';
          ctx.globalAlpha = alpha;
          ctx.fill();
          ctx.globalAlpha = 1.0;

          // On hover: subtle light grey ring around the hovered node with smooth 0.5s transition
          if (node.hoverTransition > 0.01) {
            ctx.beginPath();
            ctx.arc(node.x, node.y, radius + 6, 0, Math.PI * 2);
            ctx.strokeStyle = `rgba(255, 255, 255, ${node.hoverTransition * 0.6})`;
            ctx.lineWidth = 1.4;
            ctx.stroke();
          }

          // Subtle grey label text next to node
          if (!selectedId || isHovered) {
            ctx.font = 'bold 8.5px JetBrains Mono, monospace';
            ctx.fillStyle = isHovered ? '#ffffff' : 'rgba(148, 163, 184, 0.65)';
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
