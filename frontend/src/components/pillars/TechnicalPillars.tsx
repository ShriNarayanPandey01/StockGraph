import React from 'react';
import { TECHNICAL_PILLARS } from '../../data/pillarsData';

export const TechnicalPillars: React.FC = () => {
  return (
    <section id="pillars" className="py-16 px-6 max-w-7xl mx-auto border-t border-white/5">
      <div className="max-w-3xl mb-12">
        <div className="text-xs font-mono text-sky-400 uppercase tracking-widest mb-1">
          Architectural Foundations
        </div>
        <h2 className="text-3xl font-extrabold text-white">
          Built for Truth. Engineered Against Hallucination.
        </h2>
        <p className="text-sm text-slate-400 mt-2">
          Standard vector embeddings fail on equities because semantic proximity does not equal economic causality. StockGraph enforces four non-negotiable architectural layers:
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {TECHNICAL_PILLARS.map((pillar) => {
          let badgeBorder = 'border-sky-500/20 bg-sky-500/10 text-sky-400';
          let hoverBorder = 'hover:border-sky-500/30';
          let hoverText = 'group-hover:text-sky-300';

          if (pillar.accentColor === 'amber') {
            badgeBorder = 'border-amber-500/20 bg-amber-500/10 text-amber-400';
            hoverBorder = 'hover:border-amber-500/30';
            hoverText = 'group-hover:text-amber-300';
          } else if (pillar.accentColor === 'purple') {
            badgeBorder = 'border-purple-500/20 bg-purple-500/10 text-purple-400';
            hoverBorder = 'hover:border-purple-500/30';
            hoverText = 'group-hover:text-purple-300';
          } else if (pillar.accentColor === 'emerald') {
            badgeBorder = 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400';
            hoverBorder = 'hover:border-emerald-500/30';
            hoverText = 'group-hover:text-emerald-300';
          }

          return (
            <div
              key={pillar.number}
              className={`glass-panel p-6 rounded-2xl border border-white/10 ${hoverBorder} transition-all duration-200 group bg-ink-1/90`}
            >
              <div className="flex items-center justify-between mb-4">
                <span
                  className={`text-xs font-mono px-2.5 py-1 rounded border ${badgeBorder}`}
                >
                  {pillar.badge}
                </span>
                <span className="text-xs font-mono text-slate-500">
                  {pillar.storeTag}
                </span>
              </div>

              <h3 className={`text-lg font-bold text-white ${hoverText} transition`}>
                {pillar.title}
              </h3>

              <p className="text-xs sm:text-sm text-slate-400 mt-2 leading-relaxed">
                {pillar.description}
              </p>

              <div className="mt-4 pt-4 border-t border-white/5 flex flex-wrap gap-2 text-[11px] font-mono text-slate-400">
                {pillar.codeSnippets.map((snippet, idx) => (
                  <span key={idx} className="bg-white/5 px-2 py-0.5 rounded border border-white/5">
                    {snippet}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
};

