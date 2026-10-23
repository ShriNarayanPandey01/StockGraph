import React, { useState } from 'react';
import { RefreshCw, Sparkles, Terminal } from 'lucide-react';
import { TECHNICAL_PILLARS } from '../../data/pillarsData';
import { PillarBhavcopyVisual } from './PillarBhavcopyVisual';
import { PillarOntologyVisual } from './PillarOntologyVisual';
import { PillarNarrativeVisual } from './PillarNarrativeVisual';
import { PillarBiTemporalVisual } from './PillarBiTemporalVisual';
import {
  TimescaleStreamLoader,
  FalkorGraphLoader,
  NarrativeDeduplicationLoader,
  BiTemporalWindowLoader,
} from '../shared/ContentLoaders';

export const TechnicalPillars: React.FC = () => {
  // Track loading state for each pillar card independently
  const [loadingCards, setLoadingCards] = useState<Record<string, boolean>>({});

  const handleSimulateInspection = (pillarNumber: string) => {
    setLoadingCards((prev) => ({ ...prev, [pillarNumber]: true }));
    setTimeout(() => {
      setLoadingCards((prev) => ({ ...prev, [pillarNumber]: false }));
    }, 1100);
  };

  const renderPillarVisual = (pillarNumber: string) => {
    switch (pillarNumber) {
      case '01':
        return <PillarBhavcopyVisual />;
      case '02':
        return <PillarOntologyVisual />;
      case '03':
        return <PillarNarrativeVisual />;
      case '04':
        return <PillarBiTemporalVisual />;
      default:
        return null;
    }
  };

  const renderPillarLoader = (pillarNumber: string) => {
    switch (pillarNumber) {
      case '01':
        return (
          <TimescaleStreamLoader
            label="Streaming Bhavcopy CSV & Z-Scores..."
            sublabel="Verifying sec_bhavdata_full.csv 20-day delivery distribution"
            className="h-44"
          />
        );
      case '02':
        return (
          <FalkorGraphLoader
            label="Synthesizing Dynamic Ontology..."
            sublabel="Injecting StockContextCard guidance & calculating margin impact"
            className="h-44"
          />
        );
      case '03':
        return (
          <NarrativeDeduplicationLoader
            label="Reconstructing Causal Chains..."
            sublabel="L1 URL hash → L2 Headline → L3 Cosine 0.92 → L4 Narrative Arc"
            className="h-44"
          />
        );
      case '04':
        return (
          <BiTemporalWindowLoader
            label="Aligning Bi-Temporal Horizon..."
            sublabel="Rotating superseded snapshots with [:SUPERSEDES] laser edge"
            className="h-44"
          />
        );
      default:
        return null;
    }
  };

  return (
    <section id="pillars" className="py-16 px-6 max-w-7xl mx-auto border-t border-white/5">
      <div className="max-w-3xl mb-12">
        <div className="text-xs font-mono text-sky-400 uppercase tracking-widest mb-1 flex items-center gap-1.5">
          <Sparkles className="w-3.5 h-3.5 text-sky-400" />
          <span>Architectural Foundations</span>
        </div>
        <h2 className="text-3xl font-extrabold text-white">
          Built for Truth. Engineered Against Hallucination.
        </h2>
        <p className="text-sm text-slate-400 mt-2">
          Standard vector embeddings fail on equities because semantic proximity does not equal economic causality. StockGraph enforces four non-negotiable architectural layers:
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {TECHNICAL_PILLARS.map((pillar) => {
          let badgeBorder = 'border-sky-500/20 bg-sky-500/10 text-sky-400';
          let hoverBorder = 'hover:border-sky-500/40';
          let hoverText = 'group-hover:text-sky-300';
          let accentGlow = 'glow-aura';

          if (pillar.accentColor === 'amber') {
            badgeBorder = 'border-amber-500/20 bg-amber-500/10 text-amber-400';
            hoverBorder = 'hover:border-amber-500/40';
            hoverText = 'group-hover:text-amber-300';
            accentGlow = 'halo-orange';
          } else if (pillar.accentColor === 'purple') {
            badgeBorder = 'border-purple-500/20 bg-purple-500/10 text-purple-400';
            hoverBorder = 'hover:border-purple-500/40';
            hoverText = 'group-hover:text-purple-300';
            accentGlow = 'halo-purple';
          } else if (pillar.accentColor === 'emerald') {
            badgeBorder = 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400';
            hoverBorder = 'hover:border-emerald-500/40';
            hoverText = 'group-hover:text-emerald-300';
            accentGlow = 'halo-emerald';
          }

          const isCardLoading = !!loadingCards[pillar.number];

          return (
            <div
              key={pillar.number}
              className={`glass-panel p-6 rounded-3xl border border-white/10 ${hoverBorder} hover:${accentGlow} transition-all duration-300 group bg-ink-1/90 flex flex-col justify-between`}
            >
              <div>
                {/* Header row with badge, store tag, and simulate button */}
                <div className="flex items-center justify-between mb-4">
                  <span className={`text-xs font-mono px-2.5 py-1 rounded border font-semibold ${badgeBorder}`}>
                    {pillar.badge}
                  </span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-slate-500">
                      {pillar.storeTag}
                    </span>
                    <button
                      onClick={() => handleSimulateInspection(pillar.number)}
                      title="Simulate telemetry load"
                      className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white border border-white/10 transition"
                    >
                      <RefreshCw className={`w-3 h-3 ${isCardLoading ? 'animate-spin text-sky-400' : ''}`} />
                    </button>
                  </div>
                </div>

                {/* 3D Visualizer or Dynamic Loading Animation */}
                <div className="mb-5">
                  {isCardLoading ? renderPillarLoader(pillar.number) : renderPillarVisual(pillar.number)}
                </div>

                <h3 className={`text-lg font-bold text-white ${hoverText} transition`}>
                  {pillar.title}
                </h3>

                <p className="text-xs sm:text-sm text-slate-400 mt-2.5 leading-relaxed">
                  {pillar.description}
                </p>
              </div>

              {/* Code Snippets & Specification tags */}
              <div className="mt-5 pt-4 border-t border-white/5 flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap gap-1.5 text-[11px] font-mono text-slate-400">
                  {pillar.codeSnippets.map((snippet, idx) => (
                    <span key={idx} className="bg-white/5 px-2 py-0.5 rounded border border-white/5 flex items-center gap-1">
                      <Terminal className="w-2.5 h-2.5 opacity-60" />
                      <span>{snippet}</span>
                    </span>
                  ))}
                </div>

                <button
                  onClick={() => handleSimulateInspection(pillar.number)}
                  className="text-[10px] font-mono text-slate-500 hover:text-slate-300 underline underline-offset-4 transition"
                >
                  Verify Telemetry
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
};
