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
  neighbors: string[]; // Dynamic list of connected neighbor IDs
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  baseAlpha: number;
}

// 33 Canonical Indian Market Entities across Equities, Commodities, Macro, and Catalysts
const CANONICAL_CONFIGS: {
  id: string;
  title: string;
  avatar: string;
  color: string;
  type: 'Stock' | 'Commodity' | 'Macro' | 'News';
  neighbors: string[];
}[] = [
  // 1. TATA STEEL
  {
    id: 'TATASTEEL',
    title: 'Tata Steel Limited',
    avatar: 'TS',
    color: '#38bdf8',
    type: 'Stock',
    neighbors: ['COKING_COAL', 'HRC_STEEL', 'RBI_REPO_RATE', 'CHINA_STIMULUS', 'JSWSTEEL'],
  },
  // 2. COKING COAL
  {
    id: 'COKING_COAL',
    title: 'Hard Coking Coal',
    avatar: 'COAL',
    color: '#f97316',
    type: 'Commodity',
    neighbors: ['TATASTEEL', 'HRC_STEEL', 'JSWSTEEL'],
  },
  // 3. HRC STEEL
  {
    id: 'HRC_STEEL',
    title: 'Hot Rolled Coil Steel',
    avatar: 'HRC',
    color: '#38bdf8',
    type: 'Commodity',
    neighbors: ['TATASTEEL', 'MARUTI', 'LT', 'CHINA_STIMULUS'],
  },
  // 4. RBI REPO RATE
  {
    id: 'RBI_REPO_RATE',
    title: 'RBI Repo Rate (6.5%)',
    avatar: 'RBI',
    color: '#a855f7',
    type: 'Macro',
    neighbors: ['HDFCBANK', 'ICICIBANK', 'BAJFINANCE', 'INDIA_10Y_YIELD'],
  },
  // 5. CHINA STIMULUS
  {
    id: 'CHINA_STIMULUS',
    title: 'China Infrastructure Stimulus',
    avatar: 'NEWS',
    color: '#10b981',
    type: 'News',
    neighbors: ['TATASTEEL', 'HRC_STEEL', 'JSWSTEEL', 'COPPER'],
  },
  // 6. RELIANCE
  {
    id: 'RELIANCE',
    title: 'Reliance Industries Ltd',
    avatar: 'RIL',
    color: '#38bdf8',
    type: 'Stock',
    neighbors: ['BRENT_CRUDE', 'USD_INR_FX', 'TELECOM_TARIFF', 'NATURAL_GAS'],
  },
  // 7. BRENT CRUDE
  {
    id: 'BRENT_CRUDE',
    title: 'Brent Crude Benchmark',
    avatar: 'CRUDE',
    color: '#f97316',
    type: 'Commodity',
    neighbors: ['RELIANCE', 'ASIANPAINTS', 'USD_INR_FX'],
  },
  // 8. USD / INR FX
  {
    id: 'USD_INR_FX',
    title: 'USD/INR FX Rate',
    avatar: 'FX',
    color: '#38bdf8',
    type: 'Macro',
    neighbors: ['INFY', 'TCS', 'RELIANCE', 'SUNPHARMA', 'GOLD_MCX'],
  },
  // 9. TELECOM TARIFF
  {
    id: 'TELECOM_TARIFF',
    title: 'Mobile Tariff Revision',
    avatar: 'JIO',
    color: '#10b981',
    type: 'News',
    neighbors: ['RELIANCE', 'BHARTIARTL'],
  },
  // 10. HDFC BANK
  {
    id: 'HDFCBANK',
    title: 'HDFC Bank Limited',
    avatar: 'HDFC',
    color: '#38bdf8',
    type: 'Stock',
    neighbors: ['RBI_REPO_RATE', 'INDIA_10Y_YIELD', 'LDR_COMPLIANCE', 'FII_DII_FLOWS'],
  },
  // 11. INDIA 10Y YIELD
  {
    id: 'INDIA_10Y_YIELD',
    title: 'India 10Y Benchmark (7.15%)',
    avatar: '10Y',
    color: '#a855f7',
    type: 'Macro',
    neighbors: ['HDFCBANK', 'SBIN', 'ICICIBANK', 'RBI_REPO_RATE'],
  },
  // 12. LDR COMPLIANCE
  {
    id: 'LDR_COMPLIANCE',
    title: 'Loan-to-Deposit Glidepath',
    avatar: 'LDR',
    color: '#10b981',
    type: 'News',
    neighbors: ['HDFCBANK'],
  },
  // 13. ASIAN PAINTS
  {
    id: 'ASIANPAINTS',
    title: 'Asian Paints Limited',
    avatar: 'PAINT',
    color: '#f43f5e',
    type: 'Stock',
    neighbors: ['BRENT_CRUDE', 'USD_INR_FX', 'NATURAL_GAS'],
  },
  // 14. INFOSYS
  {
    id: 'INFY',
    title: 'Infosys Limited',
    avatar: 'INFY',
    color: '#0284c7',
    type: 'Stock',
    neighbors: ['US_FED_RATE', 'USD_INR_FX', 'TCS'],
  },
  // 15. TCS
  {
    id: 'TCS',
    title: 'Tata Consultancy Services',
    avatar: 'TCS',
    color: '#818cf8',
    type: 'Stock',
    neighbors: ['US_FED_RATE', 'USD_INR_FX', 'INFY'],
  },
  // 16. ICICI BANK
  {
    id: 'ICICIBANK',
    title: 'ICICI Bank Limited',
    avatar: 'ICICI',
    color: '#f97316',
    type: 'Stock',
    neighbors: ['RBI_REPO_RATE', 'INDIA_10Y_YIELD', 'HDFCBANK', 'FII_DII_FLOWS'],
  },
  // 17. STATE BANK OF INDIA
  {
    id: 'SBIN',
    title: 'State Bank of India',
    avatar: 'SBIN',
    color: '#0284c7',
    type: 'Stock',
    neighbors: ['GOVT_CAPEX_SPEND', 'INDIA_10Y_YIELD', 'RBI_REPO_RATE'],
  },
  // 18. LARSEN & TOUBRO
  {
    id: 'LT',
    title: 'Larsen & Toubro Ltd',
    avatar: 'LT',
    color: '#22c55e',
    type: 'Stock',
    neighbors: ['GOVT_CAPEX_SPEND', 'HRC_STEEL', 'ALUMINIUM', 'COPPER'],
  },
  // 19. MARUTI SUZUKI
  {
    id: 'MARUTI',
    title: 'Maruti Suzuki India',
    avatar: 'MSIL',
    color: '#6366f1',
    type: 'Stock',
    neighbors: ['HRC_STEEL', 'ALUMINIUM', 'USD_INR_FX'],
  },
  // 20. SUN PHARMA
  {
    id: 'SUNPHARMA',
    title: 'Sun Pharmaceutical Ltd',
    avatar: 'SUN',
    color: '#ec4899',
    type: 'Stock',
    neighbors: ['USD_INR_FX', 'INDIA_CPI'],
  },
  // 21. ITC LIMITED
  {
    id: 'ITC',
    title: 'ITC Limited',
    avatar: 'ITC',
    color: '#eab308',
    type: 'Stock',
    neighbors: ['INDIA_CPI', 'FII_DII_FLOWS'],
  },
  // 22. BAJAJ FINANCE
  {
    id: 'BAJFINANCE',
    title: 'Bajaj Finance Limited',
    avatar: 'BAJ',
    color: '#3b82f6',
    type: 'Stock',
    neighbors: ['RBI_REPO_RATE', 'INDIA_10Y_YIELD'],
  },
  // 23. JSW STEEL
  {
    id: 'JSWSTEEL',
    title: 'JSW Steel Limited',
    avatar: 'JSW',
    color: '#0284c7',
    type: 'Stock',
    neighbors: ['COKING_COAL', 'HRC_STEEL', 'CHINA_STIMULUS', 'TATASTEEL'],
  },
  // 24. BHARTI AIRTEL
  {
    id: 'BHARTIARTL',
    title: 'Bharti Airtel Limited',
    avatar: 'AIRTEL',
    color: '#ef4444',
    type: 'Stock',
    neighbors: ['TELECOM_TARIFF', 'USD_INR_FX'],
  },
  // 25. TITAN COMPANY
  {
    id: 'TITAN',
    title: 'Titan Company Limited',
    avatar: 'TITAN',
    color: '#eab308',
    type: 'Stock',
    neighbors: ['GOLD_MCX', 'INDIA_CPI'],
  },
  // 26. ALUMINIUM
  {
    id: 'ALUMINIUM',
    title: 'Aluminium Primary Ingot',
    avatar: 'AL',
    color: '#94a3b8',
    type: 'Commodity',
    neighbors: ['MARUTI', 'LT'],
  },
  // 27. GOLD MCX
  {
    id: 'GOLD_MCX',
    title: 'Gold MCX Futures',
    avatar: 'AU',
    color: '#eab308',
    type: 'Commodity',
    neighbors: ['TITAN', 'USD_INR_FX'],
  },
  // 28. NATURAL GAS
  {
    id: 'NATURAL_GAS',
    title: 'Natural Gas Henry Hub',
    avatar: 'GAS',
    color: '#38bdf8',
    type: 'Commodity',
    neighbors: ['RELIANCE', 'ASIANPAINTS'],
  },
  // 29. COPPER
  {
    id: 'COPPER',
    title: 'Copper Cathode LME',
    avatar: 'Cu',
    color: '#ea580c',
    type: 'Commodity',
    neighbors: ['LT', 'CHINA_STIMULUS'],
  },
  // 30. INDIA CPI
  {
    id: 'INDIA_CPI',
    title: 'India CPI Inflation (5.4%)',
    avatar: 'CPI',
    color: '#f43f5e',
    type: 'Macro',
    neighbors: ['RBI_REPO_RATE', 'ITC', 'TITAN'],
  },
  // 31. US FED RATE
  {
    id: 'US_FED_RATE',
    title: 'US Federal Funds Rate (5.25%)',
    avatar: 'FED',
    color: '#3b82f6',
    type: 'Macro',
    neighbors: ['INFY', 'TCS', 'USD_INR_FX'],
  },
  // 32. GOVT CAPEX SPEND
  {
    id: 'GOVT_CAPEX_SPEND',
    title: 'Govt Infrastructure Capex',
    avatar: 'CAPEX',
    color: '#10b981',
    type: 'Macro',
    neighbors: ['LT', 'SBIN'],
  },
  // 33. FII & DII FLOWS
  {
    id: 'FII_DII_FLOWS',
    title: 'Institutional Equity Flows',
    avatar: 'FLOWS',
    color: '#38bdf8',
    type: 'Macro',
    neighbors: ['HDFCBANK', 'ICICIBANK', 'ITC'],
  },
];

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

// Pre-warm all images immediately
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
  const hoveredNodeIdRef = useRef<string | null>(null);
  const [dimensions, setDimensions] = useState<{ width: number; height: number }>({ width: 0, height: 0 });

  const dimensionsChangeRef = useRef(onDimensionsChange);
  dimensionsChangeRef.current = onDimensionsChange;

  // Initialize nodes distributed gracefully across canvas
  const initNodes = (w: number, h: number) => {
    const nodes: DynamicNode[] = [];

    // 1. Place all Canonical Nodes spread gracefully across the screen
    CANONICAL_CONFIGS.forEach((cfg, i) => {
      // Golden spiral distribution so entities are pleasantly distributed across width & height
      const angle = i * 2.39996; // Golden angle in radians
      const maxR = Math.min(w, h) * 0.42;
      const r = maxR * Math.sqrt((i + 1) / CANONICAL_CONFIGS.length) + 40;
      const x = w / 2 + Math.cos(angle) * r;
      const y = h / 2 + Math.sin(angle) * r;

      nodes.push({
        id: cfg.id,
        title: cfg.title,
        avatar: cfg.avatar,
        color: cfg.color,
        type: cfg.type,
        neighbors: cfg.neighbors,
        x: Math.max(60, Math.min(w - 60, x)),
        y: Math.max(60, Math.min(h - 60, y)),
        // Graceful, calm moving action like in interactive_wireframe.html
        vx: (Math.random() - 0.5) * 0.22,
        vy: (Math.random() - 0.5) * 0.22,
        radius: 6,
        baseAlpha: 0.85,
      });
    });

    // 2. Add 55 ambient background micro-stars for celestial constellation depth
    const ambientCount = 55;
    for (let i = 0; i < ambientCount; i++) {
      nodes.push({
        id: `star_${i}`,
        title: `Star ${i}`,
        avatar: '',
        color: '#ffffff',
        type: 'Star',
        neighbors: [],
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.18,
        vy: (Math.random() - 0.5) * 0.18,
        radius: Math.random() * 1.8 + 0.8,
        baseAlpha: Math.random() * 0.4 + 0.15,
      });
    }

    nodesRef.current = nodes;
  };

  // ResizeObserver to fill parent container
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

  // Mouse hover tracking
  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || dimensions.width === 0 || dimensions.height === 0) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    mouseRef.current = { x: mx, y: my, isInside: true };

    // Find closest node within hover radius
    let foundId: string | null = null;
    for (const node of nodesRef.current) {
      if (node.type === 'Star') continue;
      const dist = Math.hypot(node.x - mx, node.y - my);
      if (dist < 28) {
        foundId = node.id;
        break;
      }
    }
    hoveredNodeIdRef.current = foundId;
  };

  const handleMouseLeave = () => {
    mouseRef.current.isInside = false;
    hoveredNodeIdRef.current = null;
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
          // If clicked on an ambient star, jump to the nearest canonical entity
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

    // Check if the image element is valid, completed, and has positive natural dimensions
    if (img && img.complete && img.naturalWidth > 0 && img.naturalHeight > 0) {
      try {
        ctx.save();
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.clip();
        ctx.drawImage(img, x - radius, y - radius, radius * 2, radius * 2);
        ctx.restore();
        rendered = true;
      } catch (err) {
        rendered = false;
      }
    }

    // High-contrast procedural vector fallback if image is loading or broken
    if (!rendered) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fillStyle = '#0f172a';
      ctx.fill();

      // Subtle colored gradient
      const grad = ctx.createRadialGradient(x, y, 2, x, y, radius);
      grad.addColorStop(0, fallbackColor + '44');
      grad.addColorStop(1, '#090d16');
      ctx.fillStyle = grad;
      ctx.fill();

      // Avatar text
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

      // 1. Subtle Background Grid
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.02)';
      ctx.lineWidth = 1;
      const gridSize = 48;
      for (let x = 0; x < w; x += gridSize) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
      for (let y = 0; y < h; y += gridSize) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }

      const nodes = nodesRef.current;
      const hoveredId = hoveredNodeIdRef.current;

      // Map canonical nodes for fast neighbor lookup
      const nodeMap = new Map<string, DynamicNode>();
      for (const n of nodes) {
        if (n.type !== 'Star') {
          nodeMap.set(n.id, n);
        }
      }

      const hoveredNode = hoveredId ? nodeMap.get(hoveredId) : null;
      const neighborIds = new Set<string>(hoveredNode ? hoveredNode.neighbors : []);

      // 2. Physics Update: Graceful gentle drift for all nodes
      for (const node of nodes) {
        node.x += node.vx;
        node.y += node.vy;

        // Soft bounce at boundaries
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
      }

      // 3. Ambient Micro-Star Interlinks
      for (let i = 0; i < nodes.length; i++) {
        if (nodes[i].type !== 'Star') continue;
        for (let j = i + 1; j < nodes.length; j++) {
          if (nodes[j].type !== 'Star') continue;
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist = Math.hypot(dx, dy);
          if (dist < 80) {
            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.strokeStyle = `rgba(255, 255, 255, ${0.08 * (1 - dist / 80)})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }

      // 4. Draw Illuminated Edges to Neighbors when a Node is Hovered
      if (hoveredNode) {
        for (const neighborId of hoveredNode.neighbors) {
          const neighborNode = nodeMap.get(neighborId);
          if (neighborNode) {
            ctx.beginPath();
            ctx.moveTo(hoveredNode.x, hoveredNode.y);
            ctx.lineTo(neighborNode.x, neighborNode.y);

            // Glowing illuminated edge line
            ctx.strokeStyle = neighborNode.color || '#38bdf8';
            ctx.lineWidth = 2.2;
            ctx.shadowColor = neighborNode.color || '#38bdf8';
            ctx.shadowBlur = 12;
            ctx.setLineDash([5, 5]);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.shadowBlur = 0;
          }
        }
      }

      // 5. Draw All Nodes (Dots or Dynamic Images)
      for (const node of nodes) {
        const isHovered = node.id === hoveredId;
        const isNeighbor = neighborIds.has(node.id);
        const hasActiveHover = hoveredId !== null;

        // ---- CASE A: Connected Neighbor Node turns into a small circular image! ----
        if (isNeighbor) {
          const imgRadius = 22; // 44px diameter circular image

          // Outer glowing halo border
          ctx.beginPath();
          ctx.arc(node.x, node.y, imgRadius + 3, 0, Math.PI * 2);
          ctx.strokeStyle = node.color || '#38bdf8';
          ctx.lineWidth = 2.2;
          ctx.shadowColor = node.color || '#38bdf8';
          ctx.shadowBlur = 12;
          ctx.stroke();
          ctx.shadowBlur = 0;

          // Safe image rendering (with guaranteed fallback)
          drawImageSafe(ctx, node.id, node.x, node.y, imgRadius, node.color, node.avatar);

          // Tiny label pill below image node
          ctx.font = 'bold 9px JetBrains Mono, monospace';
          const text = node.id;
          const textW = ctx.measureText(text).width;
          ctx.fillStyle = 'rgba(11, 12, 14, 0.95)';
          ctx.fillRect(node.x - textW / 2 - 4, node.y + imgRadius + 4, textW + 8, 14);
          ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
          ctx.strokeRect(node.x - textW / 2 - 4, node.y + imgRadius + 4, textW + 8, 14);
          ctx.fillStyle = '#ffffff';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(text, node.x, node.y + imgRadius + 11);
        }
        // ---- CASE B: Hovered Focal Node ----
        else if (isHovered && node.type !== 'Star') {
          const hoverRadius = 24;

          // Outer pulsing glow aura
          ctx.beginPath();
          ctx.arc(node.x, node.y, hoverRadius + 8, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(56, 189, 248, 0.12)';
          ctx.fill();
          ctx.strokeStyle = 'rgba(56, 189, 248, 0.5)';
          ctx.lineWidth = 1.5;
          ctx.stroke();

          // Safe image or avatar
          drawImageSafe(ctx, node.id, node.x, node.y, hoverRadius, node.color, node.avatar);

          // Prominent border
          ctx.beginPath();
          ctx.arc(node.x, node.y, hoverRadius, 0, Math.PI * 2);
          ctx.strokeStyle = node.color || '#38bdf8';
          ctx.lineWidth = 2.5;
          ctx.shadowColor = node.color || '#38bdf8';
          ctx.shadowBlur = 16;
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
        }
        // ---- CASE C: Regular Ambient Star ----
        else if (node.type === 'Star') {
          const starAlpha = hasActiveHover ? node.baseAlpha * 0.4 : node.baseAlpha;
          ctx.beginPath();
          ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255, 255, 255, ${starAlpha})`;
          ctx.fill();
        }
        // ---- CASE D: Regular Canonical Node (Default floating state) ----
        else {
          const alpha = hasActiveHover ? 0.22 : 0.95;
          const radius = 6.5;

          // Subtle glowing halo
          ctx.beginPath();
          ctx.arc(node.x, node.y, radius + 4, 0, Math.PI * 2);
          ctx.fillStyle = node.color;
          ctx.globalAlpha = alpha * 0.18;
          ctx.fill();
          ctx.globalAlpha = 1.0;

          // Solid celestial core
          ctx.beginPath();
          ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
          ctx.fillStyle = node.color;
          ctx.globalAlpha = alpha;
          ctx.shadowColor = node.color;
          ctx.shadowBlur = 8;
          ctx.fill();
          ctx.shadowBlur = 0;
          ctx.globalAlpha = 1.0;

          // If this is currently the active selected entity, draw a subtle outer ring
          if (node.id === activeEntityIdRef.current) {
            ctx.beginPath();
            ctx.arc(node.x, node.y, radius + 6, 0, Math.PI * 2);
            ctx.strokeStyle = node.color;
            ctx.lineWidth = 1.4;
            ctx.stroke();
          }

          // Subtle label pill next to node
          if (!hasActiveHover) {
            ctx.font = 'bold 8.5px JetBrains Mono, monospace';
            ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
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
