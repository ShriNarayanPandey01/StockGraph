import React from 'react';
import { ArrowDown, Terminal, Sparkles } from 'lucide-react';
import { NeonCircuitBackground } from './NeonCircuitBackground';
import { WavyRocketCanvas } from './WavyRocketCanvas';

interface HeroSectionProps {
  onSelectTicker: (ticker: string) => void;
  onExploreClick: () => void;
}

export const HeroSection: React.FC<HeroSectionProps> = ({
  onSelectTicker,
  onExploreClick,
}) => {
  return (
    <section className="relative pt-16 pb-20 overflow-hidden border-b border-white/5">
      {/* 1. Subtle Hardware-Accelerated Neon LED Circuit Background */}
      <NeonCircuitBackground />

      {/* 2. Motion Graphics: Character Sitting on a Rocket Flying in a Wavy Pattern (Bottom-Left to Top-Right) */}
      <WavyRocketCanvas />

      <div className="max-w-6xl mx-auto px-4 sm:px-6 relative z-10 text-center">
        {/* Eyebrow Badge */}
        <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-sky-500/10 border border-sky-500/20 text-sky-400 text-xs font-mono mb-8 backdrop-blur-md shadow-[0_0_20px_rgba(56,189,248,0.15)]">
          <Sparkles className="w-3.5 h-3.5 text-sky-400 animate-pulse" />
          <span>INDIAN EQUITIES (NSE/BSE) · DUAL-STORE GRAPHRAG</span>
        </div>

        {/* Main Headline */}
        <h1 className="text-4xl sm:text-6xl lg:text-7xl font-extrabold tracking-tight text-white max-w-4xl mx-auto leading-[1.1] drop-shadow-lg">
          The Stock Intelligence Engine That Connects The{' '}
          <span className="bg-gradient-to-r from-sky-400 via-indigo-300 to-purple-400 bg-clip-text text-transparent drop-shadow-[0_0_30px_rgba(56,189,248,0.35)]">
            Invisible Dots
          </span>
          .
        </h1>

        {/* Subheadline */}
        <p className="mt-6 text-base sm:text-lg lg:text-xl text-slate-300 max-w-3xl mx-auto leading-relaxed drop-shadow">
          Equity markets don't live in isolated spreadsheets. When global coking coal spikes, when RBI raises repo rates, or when China unleashes infrastructure stimulus, StockGraph computes the multi-hop transmission across your stock universe with zero hallucinated edges.
        </p>

        {/* Hero Actions */}
        <div className="mt-9 flex flex-wrap items-center justify-center gap-4">
          <button
            onClick={onExploreClick}
            className="px-7 py-3.5 rounded-xl bg-gradient-to-r from-sky-400 to-indigo-500 text-slate-950 font-bold text-sm hover:from-sky-300 hover:to-indigo-400 transition shadow-xl shadow-sky-500/20 flex items-center gap-2 active:scale-95"
          >
            <span>Interact with Constellation Graph</span>
            <ArrowDown className="w-4 h-4" />
          </button>
          <a
            href="#api-section"
            className="px-6 py-3.5 rounded-xl bg-ink-1/90 hover:bg-ink-2 text-slate-200 border border-white/10 font-mono text-xs transition flex items-center gap-2 shadow-lg backdrop-blur-md active:scale-95"
          >
            <Terminal className="w-3.5 h-3.5 text-sky-400" />
            <span>curl GET /api/v1/stocks/TATASTEEL/context</span>
          </a>
        </div>

        {/* Quick Ticker Chips */}
        <div className="mt-10 flex flex-wrap items-center justify-center gap-2 text-xs font-mono text-slate-400">
          <span className="text-slate-400 mr-1">Jump straight into graph:</span>
          <button
            onClick={() => onSelectTicker('TATASTEEL')}
            className="px-3 py-1.5 rounded-lg bg-ink-1/90 hover:bg-sky-500/20 hover:text-sky-300 border border-white/10 transition backdrop-blur-sm shadow-sm"
          >
            TATASTEEL (Metals)
          </button>
          <button
            onClick={() => onSelectTicker('RELIANCE')}
            className="px-3 py-1.5 rounded-lg bg-ink-1/90 hover:bg-sky-500/20 hover:text-sky-300 border border-white/10 transition backdrop-blur-sm shadow-sm"
          >
            RELIANCE (Energy/Retail)
          </button>
          <button
            onClick={() => onSelectTicker('HDFCBANK')}
            className="px-3 py-1.5 rounded-lg bg-ink-1/90 hover:bg-sky-500/20 hover:text-sky-300 border border-white/10 transition backdrop-blur-sm shadow-sm"
          >
            HDFCBANK (Financials)
          </button>
          <button
            onClick={() => onSelectTicker('BRENT_CRUDE')}
            className="px-3 py-1.5 rounded-lg bg-ink-1/90 hover:bg-amber-500/20 hover:text-amber-300 border border-white/10 transition backdrop-blur-sm shadow-sm"
          >
            BRENT_CRUDE (Commodity)
          </button>
          <button
            onClick={() => onSelectTicker('RBI_REPO_RATE')}
            className="px-3 py-1.5 rounded-lg bg-ink-1/90 hover:bg-purple-500/20 hover:text-purple-300 border border-white/10 transition backdrop-blur-sm shadow-sm"
          >
            RBI_REPO_RATE (Macro)
          </button>
        </div>

        {/* Trust Metrics Bar */}
        <div className="mt-16 pt-8 border-t border-white/10 grid grid-cols-2 md:grid-cols-4 gap-6 text-left backdrop-blur-md bg-ink-0/60 p-6 rounded-2xl border border-white/5 shadow-2xl">
          <div className="border-l-2 border-sky-500/50 pl-4">
            <div className="text-2xl font-bold font-mono text-white">0% Numbers</div>
            <div className="text-xs text-slate-400 mt-1">
              In Graph (TimescaleDB stores all numeric series strictly)
            </div>
          </div>
          <div className="border-l-2 border-emerald-500/50 pl-4">
            <div className="text-2xl font-bold font-mono text-white">100% Traceable</div>
            <div className="text-xs text-slate-400 mt-1">
              Every metric cites vendor_id + vendor_as_of
            </div>
          </div>
          <div className="border-l-2 border-purple-500/50 pl-4">
            <div className="text-2xl font-bold font-mono text-white">≥ 0.65 Confidence</div>
            <div className="text-xs text-slate-400 mt-1">
              Enforced threshold for all inferred ontology edges
            </div>
          </div>
          <div className="border-l-2 border-amber-500/50 pl-4">
            <div className="text-2xl font-bold font-mono text-white">LAST_6M / 1Y</div>
            <div className="text-xs text-slate-400 mt-1">
              Strict temporal window bounds (no arbitrary drift)
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
