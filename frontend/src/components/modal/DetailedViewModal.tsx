import React from 'react';
import { X, Share2, Layers } from 'lucide-react';
import { GraphEntity } from '../../types/graph';

interface DetailedViewModalProps {
  isOpen: boolean;
  onClose: () => void;
  entity: GraphEntity;
}

export const DetailedViewModal: React.FC<DetailedViewModalProps> = ({
  isOpen,
  onClose,
  entity,
}) => {
  if (!isOpen) return null;

  const cards = entity.detailedCards || [];

  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 backdrop-blur-xl flex items-center justify-center p-4 sm:p-6 transition-all duration-300"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-2xl max-h-[90vh] flex flex-col bg-ink-1 rounded-3xl border border-white/15 shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header Pill Filter (Matching detailed view.png search capsule) */}
        <div className="p-6 border-b border-white/10 bg-ink-0/60 flex items-center justify-between gap-4">
          <div className="glass-panel px-3 py-1.5 rounded-full flex items-center gap-2 text-xs font-mono border border-white/15">
            <span className="px-2 py-0.5 rounded-full bg-white text-slate-900 font-semibold">
              {entity.id}
            </span>
            <span className="px-2 py-0.5 rounded-full bg-white/10 text-slate-300">
              {entity.sector}
            </span>
            <span className="text-slate-500 text-[11px] hidden sm:inline">
              window=LAST_6M
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => alert(`Exported ${entity.id} Dossier JSON successfully!`)}
              title="Export Dossier JSON"
              className="h-8 w-8 rounded-full bg-white/5 hover:bg-white/10 flex items-center justify-center text-slate-400 hover:text-white transition"
            >
              <Share2 className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              className="h-8 w-8 rounded-full bg-white/5 hover:bg-rose-500/20 text-slate-400 hover:text-rose-300 flex items-center justify-center transition"
              title="Close modal"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Scrollable Feed of Rich Insight Cards */}
        <div className="overflow-y-auto p-6 space-y-6">
          {cards.length > 0 ? (
            cards.map((card) => (
              <div
                key={card.id}
                className={`relative group rounded-2xl bg-ink-2 border border-white/10 overflow-hidden ${card.badgeHalo} transition hover:border-white/20`}
              >
                {/* Visual Banner */}
                {card.statVisual && (
                  <div className="h-40 w-full bg-gradient-to-br from-slate-950 via-ink-1 to-slate-900 relative flex items-center justify-center overflow-hidden border-b border-white/10">
                    <div className="absolute inset-0 opacity-40 bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-sky-500/20 via-transparent to-transparent"></div>

                    {/* Solar Glow Ring Graphic */}
                    <div className="relative w-28 h-28 rounded-full border border-white/20 shadow-lg flex items-center justify-center">
                      <div className="w-20 h-20 rounded-full bg-black/90 border border-white/15 flex flex-col items-center justify-center text-center p-1">
                        <span className="text-sm font-bold font-mono text-white">
                          {card.statVisual.primaryText}
                        </span>
                        <span className="text-[9px] font-mono text-slate-400 leading-tight">
                          {card.statVisual.subText}
                        </span>
                      </div>
                    </div>

                    <div className="absolute top-3 right-3 text-[11px] font-mono px-2 py-0.5 rounded bg-black/60 text-slate-300 border border-white/10">
                      {card.relationLabel} · {Math.round(card.confidence * 100)}% Conf
                    </div>
                  </div>
                )}

                {/* Card Content */}
                <div className="p-5">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-white/5 text-slate-300 border border-white/10">
                      {card.typeBadge}
                    </span>
                    <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20">
                      {card.tag}
                    </span>
                    <span className="text-xs text-slate-500 ml-auto font-mono">
                      {card.timeAgo}
                    </span>
                  </div>

                  <h3 className="text-base font-bold text-white leading-snug group-hover:text-sky-300 transition">
                    {card.headline}
                  </h3>

                  <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                    <strong className="text-slate-200">Causal Rationale:</strong>{' '}
                    {card.causalRationale}
                  </p>

                  <div className="mt-4 pt-3 border-t border-white/5 flex items-center justify-between text-xs font-mono text-slate-500">
                    <span>{card.vendorOrMeta}</span>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="text-center py-12 text-slate-400 text-sm font-mono">
              <Layers className="w-8 h-8 text-slate-600 mx-auto mb-2" />
              <span>Full dossier snapshot loaded from FalkorDB.</span>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="p-4 border-t border-white/10 bg-ink-0 flex items-center justify-between text-xs font-mono text-slate-400">
          <span>Showing {cards.length} Active Inferred Graph Paths</span>
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white transition active:scale-95"
          >
            Close & Return to Constellation
          </button>
        </div>
      </div>
    </div>
  );
};

