import React, { useState } from 'react';
import { GraphEdge, GraphMode } from '../../types/graph';

interface NodeCardOverlayProps {
  edges: GraphEdge[];
  mode: GraphMode;
  width: number;
  height: number;
  hoveredEdgeId: string | null;
  onHoverEdge: (id: string | null) => void;
  onCardClick: (edge: GraphEdge) => void;
}

// Fallback high-contrast graphics in case external images are blocked or slow
const FALLBACK_ICONS: Record<string, string> = {
  COKING_COAL: '🪨',
  HRC_STEEL: '⚙️',
  RBI_REPO_RATE: '🏛️',
  CHINA_STIMULUS: '🏗️',
  BRENT_CRUDE: '🛢️',
  USD_INR_FX: '💵',
  TELECOM_TARIFF: '📡',
  INDIA_10Y_YIELD: '📈',
  LDR_COMPLIANCE: '🏦',
  ASIANPAINTS: '🎨',
  RELIANCE: '⚡',
  TATASTEEL: '🏭',
  HDFCBANK: '💳',
};

export const NodeCardOverlay: React.FC<NodeCardOverlayProps> = ({
  edges,
  mode,
  width,
  height,
  hoveredEdgeId,
  onHoverEdge,
  onCardClick,
}) => {
  const [failedImages, setFailedImages] = useState<Record<string, boolean>>({});

  if (!edges || edges.length === 0 || width === 0 || height === 0) return null;

  const cx = width / 2;
  const cy = height / 2 + 10;
  const edgeCount = edges.length;

  // Smaller edge distance closer to the node itself (115px instead of 260px+)
  const distance = Math.min(Math.min(width, height) * 0.18, 120);
  const NODE_SIZE = 52; // Compact, sleek image node size in pixels

  const handleImageError = (id: string) => {
    setFailedImages((prev) => ({ ...prev, [id]: true }));
  };

  return (
    <div className="absolute inset-0 pointer-events-none z-10 overflow-hidden">
      {edges.map((edge, index) => {
        let targetX: number;
        let targetY: number;

        if (mode === 'constellation' || mode === 'cluster') {
          const angle = (index / edgeCount) * Math.PI * 2 - Math.PI / 2;
          targetX = cx + Math.cos(angle) * distance;
          targetY = cy + Math.sin(angle) * distance;
        } else {
          // Linear mode
          const spacing = Math.min(width / (edgeCount + 1), 110);
          const startX = cx - ((edgeCount - 1) * spacing) / 2;
          targetX = startX + index * spacing;
          targetY = cy + 95;
        }

        const isHovered = hoveredEdgeId === edge.id;
        const hasFailed = failedImages[edge.id];

        // Glow halo border based on economic impact
        let haloBorder = 'border-sky-400 ring-sky-400/30';
        let badgeBg = 'bg-sky-500/90 text-white';

        if (edge.impact === 'NEGATIVE') {
          haloBorder = 'border-rose-400 ring-rose-500/40 shadow-[0_0_15px_rgba(239,68,68,0.4)]';
          badgeBg = 'bg-rose-500 text-white';
        } else if (edge.impact === 'POSITIVE') {
          haloBorder = 'border-emerald-400 ring-emerald-500/40 shadow-[0_0_15px_rgba(16,185,129,0.4)]';
          badgeBg = 'bg-emerald-500 text-white';
        } else if (edge.impact === 'MIXED') {
          haloBorder = 'border-amber-400 ring-amber-500/40 shadow-[0_0_15px_rgba(249,115,22,0.4)]';
          badgeBg = 'bg-amber-500 text-slate-950';
        }

        return (
          <div
            key={edge.id}
            className={`absolute pointer-events-auto cursor-pointer transition-all duration-300 ${
              isHovered ? 'scale-125 z-30' : 'hover:scale-115 z-20'
            }`}
            style={{
              left: `${targetX - NODE_SIZE / 2}px`,
              top: `${targetY - NODE_SIZE / 2}px`,
            }}
            onMouseEnter={() => onHoverEdge(edge.id)}
            onMouseLeave={() => onHoverEdge(null)}
            onClick={() => onCardClick(edge)}
            title={`Click to open detailed view: ${edge.id}`}
          >
            {/* Small Compact Image Node (without bulky information card) */}
            <div
              className={`relative w-[52px] h-[52px] rounded-full border-2 ${haloBorder} ring-4 shadow-xl overflow-hidden bg-slate-900 group transition-all duration-200 flex items-center justify-center`}
            >
              {edge.imageUrl && !hasFailed ? (
                <img
                  src={edge.imageUrl}
                  alt={edge.id}
                  onError={() => handleImageError(edge.id)}
                  className="w-full h-full object-cover rounded-full group-hover:scale-115 transition-transform duration-300"
                  loading="eager"
                />
              ) : (
                <div className="w-full h-full flex flex-col items-center justify-center bg-gradient-to-tr from-slate-900 via-ink-1 to-slate-800 text-sm">
                  <span>{FALLBACK_ICONS[edge.id] || '⚡'}</span>
                </div>
              )}

              {/* Subtle inner dark gradient ring */}
              <div className="absolute inset-0 rounded-full border border-white/20 pointer-events-none" />

              {/* Tiny relation indicator pip */}
              <div
                className={`absolute bottom-0 right-0 h-3 w-3 rounded-full border-2 border-ink-0 ${
                  edge.impact === 'NEGATIVE'
                    ? 'bg-rose-500'
                    : edge.impact === 'POSITIVE'
                    ? 'bg-emerald-500'
                    : 'bg-amber-400'
                }`}
              />
            </div>

            {/* Floating Minimal Tooltip Pill (Shows clean label on hover / focus) */}
            <div
              className={`absolute left-1/2 -translate-x-1/2 top-full mt-1.5 whitespace-nowrap pointer-events-none transition-all duration-200 ${
                isHovered ? 'opacity-100 scale-100' : 'opacity-85 scale-95'
              }`}
            >
              <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-ink-0/95 border border-white/20 backdrop-blur-md shadow-2xl text-[10px] font-mono">
                <span className="font-bold text-white tracking-tight">{edge.id}</span>
                <span className={`px-1 rounded text-[8px] font-semibold ${badgeBg}`}>
                  {Math.round(edge.confidence * 100)}%
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};
