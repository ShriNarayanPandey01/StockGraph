import React from 'react';
import { ArrowRight, Layers, Sparkles } from 'lucide-react';
import { GraphEntity } from '../../types/graph';

interface BottomDockProps {
  entity: GraphEntity | null;
  onOpenDetailedView: () => void;
}

export const BottomDock: React.FC<BottomDockProps> = ({
  entity,
  onOpenDetailedView,
}) => {
  return (
    <div className="absolute bottom-6 inset-x-0 mx-auto w-full max-w-2xl px-4 z-20 pointer-events-auto">
      <div className="glass-panel rounded-2xl p-3 shadow-2xl flex flex-col sm:flex-row items-center justify-between gap-3 border border-white/15 bg-ink-1/90 backdrop-blur-md">
        {entity ? (
          <>
            <div className="flex items-center gap-3">
              <div
                className="h-10 w-10 rounded-xl flex items-center justify-center font-mono font-bold text-xs border"
                style={{
                  backgroundColor: `${entity.color}20`,
                  borderColor: `${entity.color}50`,
                  color: entity.color,
                }}
              >
                {entity.avatar}
              </div>

              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-white">{entity.title}</span>
                  <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-white/10 text-slate-300">
                    {entity.exchange}: {entity.id}
                  </span>
                </div>
                <div className="text-xs text-slate-400 flex items-center gap-2 mt-0.5">
                  <span>{entity.edges.length} Connected Edges</span>
                  <span>•</span>
                  <span className="text-sky-400">{entity.sector}</span>
                  <span>•</span>
                  <span className="text-emerald-400 font-mono">Enforced Conf ≥ 0.65</span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto">
              <button
                onClick={onOpenDetailedView}
                className="w-full sm:w-auto px-4 py-2 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-bold text-xs transition shadow-lg shadow-sky-500/25 flex items-center justify-center gap-1.5 active:scale-95"
              >
                <Layers className="w-3.5 h-3.5" />
                <span>Open Detailed View</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </>
        ) : (
          <div className="flex items-center justify-between w-full text-xs font-mono px-2 py-1">
            <span className="text-slate-300 flex items-center gap-2">
              <Sparkles className="w-3.5 h-3.5 text-sky-400 animate-pulse" />
              <span>Hover or click any celestial node to blossom its transmission edges</span>
            </span>
            <span className="text-[11px] text-slate-500 hidden sm:inline">
              90 Canonical Entities • 0% Free-Text IDs
            </span>
          </div>
        )}
      </div>
    </div>
  );
};
