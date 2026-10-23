import React from 'react';
import { Database, Network, GitBranch, Clock, Cpu, Sparkles } from 'lucide-react';

interface LoaderProps {
  label?: string;
  sublabel?: string;
  className?: string;
}

/**
 * 1. TimescaleDB / Bhavcopy Oscilloscope Matrix Loader
 * Specialized for numeric time-series, Bhavcopy CSV ingestion, and delivery z-scores
 */
export const TimescaleStreamLoader: React.FC<LoaderProps> = ({
  label = 'Streaming Official NSE Bhavcopy...',
  sublabel = 'Computing 20D delivery z-score in SQL hypertable',
  className = '',
}) => {
  return (
    <div className={`p-6 rounded-2xl bg-ink-0/90 border border-indigo-500/30 flex flex-col items-center justify-center text-center relative overflow-hidden ${className}`}>
      {/* Background scanning laser line */}
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-indigo-500/10 to-transparent animate-pulse pointer-events-none" />

      {/* Oscilloscope Bar Wave */}
      <div className="flex items-end gap-1.5 h-12 mb-4">
        {[40, 75, 25, 90, 60, 100, 45, 80, 30, 95, 65, 50].map((height, i) => (
          <div
            key={i}
            className="w-1.5 rounded-t bg-gradient-to-t from-indigo-500 to-sky-400"
            style={{
              height: `${height}%`,
              animation: `pulseSlow ${0.8 + (i % 5) * 0.2}s ease-in-out infinite alternate`,
              animationDelay: `${i * 0.08}s`,
            }}
          />
        ))}
      </div>

      {/* Hex/Data status ticker */}
      <div className="flex items-center gap-2 text-indigo-400 text-xs font-mono mb-1">
        <Database className="w-4 h-4 animate-spin" style={{ animationDuration: '3s' }} />
        <span className="font-bold uppercase tracking-wider">{label}</span>
      </div>

      <p className="text-[11px] font-mono text-slate-400 max-w-xs">{sublabel}</p>

      {/* Checkpoint indicators */}
      <div className="mt-4 flex items-center gap-2 text-[10px] font-mono text-slate-400">
        <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 animate-pulse">
          SESSION: CLOSE
        </span>
        <span className="text-slate-600">→</span>
        <span className="px-2 py-0.5 rounded bg-sky-500/20 text-sky-300 border border-sky-500/40">
          z-score: 2.14σ [ANOMALY]
        </span>
      </div>
    </div>
  );
};

/**
 * 2. FalkorDB / Knowledge Graph Vectorizer Loader
 * Specialized for OpenCypher traversal, vecf32 vector indexing, and dynamic ontology edges
 */
export const FalkorGraphLoader: React.FC<LoaderProps> = ({
  label = 'Querying FalkorDB Graph & Vector Index...',
  sublabel = 'CALL db.idx.vector.queryNodes(..., vecf32($emb))',
  className = '',
}) => {
  return (
    <div className={`p-6 rounded-2xl bg-ink-0/90 border border-sky-500/30 flex flex-col items-center justify-center text-center relative overflow-hidden ${className}`}>
      {/* Hexagonal Orbital Pulsing Nodes */}
      <div className="relative w-16 h-16 mb-4 flex items-center justify-center">
        {/* Outer rotating ring */}
        <div className="absolute inset-0 border-2 border-dashed border-sky-400/40 rounded-full animate-spin" style={{ animationDuration: '6s' }} />
        {/* Inner reverse ring */}
        <div className="absolute inset-2 border border-sky-500/60 rounded-full animate-ping" style={{ animationDuration: '2.5s' }} />
        {/* Core Node */}
        <div className="w-8 h-8 rounded-full bg-sky-500/20 border border-sky-400 flex items-center justify-center shadow-lg shadow-sky-500/40">
          <Network className="w-4 h-4 text-sky-300 animate-pulse" />
        </div>
        {/* Orbiting Satellite Dots */}
        <div className="absolute w-2 h-2 rounded-full bg-amber-400 -top-1 left-7 shadow-sm shadow-amber-400" />
        <div className="absolute w-2 h-2 rounded-full bg-purple-400 -bottom-1 left-7 shadow-sm shadow-purple-400" />
      </div>

      <div className="flex items-center gap-2 text-sky-400 text-xs font-mono mb-1">
        <Sparkles className="w-4 h-4 text-sky-400 animate-bounce" />
        <span className="font-bold uppercase tracking-wider">{label}</span>
      </div>

      <p className="text-[11px] font-mono text-slate-400 max-w-sm truncate">{sublabel}</p>

      <div className="mt-3 flex items-center gap-2 text-[10px] font-mono text-slate-400">
        <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
          [:EXPOSED_TO] (conf ≥ 0.88)
        </span>
        <span className="px-2 py-0.5 rounded bg-sky-500/20 text-sky-300 border border-sky-500/30">
          vecf32 (768-dim)
        </span>
      </div>
    </div>
  );
};

/**
 * 3. News Deduplication & Multi-Day Narrative Cascade Loader
 * Specialized for L1-L4 filter pipeline and Cross-News Causal Chaining
 */
export const NarrativeDeduplicationLoader: React.FC<LoaderProps> = ({
  label = 'Processing L1-L4 News Correlation Pipeline...',
  sublabel = 'L1 URL Hash → L2 Headline → L3 Cosine ≥ 0.92 → L4 Causal Chain',
  className = '',
}) => {
  return (
    <div className={`p-6 rounded-2xl bg-ink-0/90 border border-purple-500/30 flex flex-col items-center justify-center text-center relative overflow-hidden ${className}`}>
      {/* 4-Step Staged Pipeline Bars */}
      <div className="grid grid-cols-4 gap-2 w-full max-w-xs mb-4">
        {[
          { step: 'L1', name: 'URL SETNX', color: 'from-purple-500 to-indigo-500', delay: '0s' },
          { step: 'L2', name: 'Headline', color: 'from-indigo-500 to-purple-400', delay: '0.2s' },
          { step: 'L3', name: 'Cosine 0.92', color: 'from-purple-400 to-fuchsia-500', delay: '0.4s' },
          { step: 'L4', name: 'Causal Chain', color: 'from-fuchsia-500 to-amber-400', delay: '0.6s' },
        ].map((item, idx) => (
          <div key={idx} className="flex flex-col items-center">
            <div className="w-full h-1.5 rounded-full bg-white/10 overflow-hidden mb-1">
              <div
                className={`h-full bg-gradient-to-r ${item.color} rounded-full animate-pulse`}
                style={{ animationDelay: item.delay, animationDuration: '1.2s' }}
              />
            </div>
            <span className="text-[10px] font-mono text-purple-300 font-bold">{item.step}</span>
            <span className="text-[9px] font-mono text-slate-500 truncate">{item.name}</span>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2 text-purple-400 text-xs font-mono mb-1">
        <GitBranch className="w-4 h-4 animate-spin" style={{ animationDuration: '4s' }} />
        <span className="font-bold uppercase tracking-wider">{label}</span>
      </div>

      <p className="text-[11px] font-mono text-slate-400 max-w-xs">{sublabel}</p>

      <div className="mt-3 flex items-center gap-2 text-[10px] font-mono text-slate-400">
        <span className="px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30">
          [:CORRELATED_WITH]
        </span>
        <span className="px-2 py-0.5 rounded bg-white/5 text-slate-300 border border-white/10">
          Trailing 14-Day Window
        </span>
      </div>
    </div>
  );
};

/**
 * 4. Bi-Temporal Window & Superseding Nodes Loader
 * Specialized for fixed windows (LAST_6M / LAST_1Y) and bi-temporal interval queries
 */
export const BiTemporalWindowLoader: React.FC<LoaderProps> = ({
  label = 'Filtering Bi-Temporal Snapshot Horizon...',
  sublabel = 'valid_from_ts <= $end_ts AND valid_to_ts >= $start_ts',
  className = '',
}) => {
  return (
    <div className={`p-6 rounded-2xl bg-ink-0/90 border border-emerald-500/30 flex flex-col items-center justify-center text-center relative overflow-hidden ${className}`}>
      {/* Sliding Aperture Slider Visual */}
      <div className="w-full max-w-xs mb-4">
        <div className="flex justify-between text-[10px] font-mono text-slate-500 mb-1">
          <span>NOW - 180D (LAST_6M)</span>
          <span className="text-emerald-400 font-bold">LATEST REALITY</span>
        </div>
        <div className="relative h-3 rounded-full bg-ink-2 border border-white/10 overflow-hidden">
          {/* Active window slice with animated shimmer */}
          <div
            className="absolute top-0 bottom-0 left-1/4 right-0 bg-gradient-to-r from-emerald-500/30 via-emerald-400/50 to-emerald-500/30 border-l-2 border-r-2 border-emerald-400 animate-pulse"
          />
          {/* Traveling time cursor */}
          <div className="absolute top-0 bottom-0 w-1 bg-white shadow-lg shadow-emerald-400 animate-ping" style={{ left: '60%' }} />
        </div>
        <div className="flex justify-between text-[9px] font-mono text-slate-400 mt-1">
          <span>valid_from_ts</span>
          <span className="text-emerald-300">[:SUPERSEDES] active</span>
          <span>valid_to_ts: 9999999999</span>
        </div>
      </div>

      <div className="flex items-center gap-2 text-emerald-400 text-xs font-mono mb-1">
        <Clock className="w-4 h-4 animate-spin" style={{ animationDuration: '5s' }} />
        <span className="font-bold uppercase tracking-wider">{label}</span>
      </div>

      <p className="text-[11px] font-mono text-slate-400 max-w-xs">{sublabel}</p>

      <div className="mt-3 flex items-center gap-2 text-[10px] font-mono">
        <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
          is_latest: true
        </span>
        <span className="px-2 py-0.5 rounded bg-white/5 text-slate-400 border border-white/10">
          Cacheable 2-Key Storage
        </span>
      </div>
    </div>
  );
};

/**
 * 5. Dual-Store Data Pipeline Conduit Loader
 * Specialized for cross-service operations between Upstox TimescaleDB and StockGraph FalkorDB
 */
export const DualStorePipelineLoader: React.FC<LoaderProps> = ({
  label = 'Synchronizing Dual-Store Outbox Conduits...',
  sublabel = 'TimescaleDB (Numbers) ⟷ FalkorDB (Topology) Wire Contract v1',
  className = '',
}) => {
  return (
    <div className={`p-6 rounded-2xl bg-ink-0/90 border border-white/15 flex flex-col items-center justify-center text-center relative overflow-hidden ${className}`}>
      <div className="flex items-center gap-6 mb-4">
        {/* Left: SQL Cylinder */}
        <div className="flex flex-col items-center">
          <div className="w-10 h-10 rounded-xl bg-indigo-500/20 border border-indigo-500/50 flex items-center justify-center text-indigo-400 animate-pulse">
            <Database className="w-5 h-5" />
          </div>
          <span className="text-[10px] font-mono text-indigo-300 mt-1 font-bold">SQL Store</span>
        </div>

        {/* Conduit Particles */}
        <div className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-ping" />
          <span className="w-8 h-0.5 bg-gradient-to-r from-indigo-500 via-white to-sky-400" />
          <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-ping" style={{ animationDelay: '0.3s' }} />
        </div>

        {/* Right: FalkorDB Graph */}
        <div className="flex flex-col items-center">
          <div className="w-10 h-10 rounded-xl bg-sky-500/20 border border-sky-500/50 flex items-center justify-center text-sky-400 animate-pulse" style={{ animationDelay: '0.4s' }}>
            <Network className="w-5 h-5" />
          </div>
          <span className="text-[10px] font-mono text-sky-300 mt-1 font-bold">FalkorDB</span>
        </div>
      </div>

      <div className="flex items-center gap-2 text-white text-xs font-mono mb-1">
        <Cpu className="w-4 h-4 text-sky-400 animate-spin" style={{ animationDuration: '4s' }} />
        <span className="font-bold uppercase tracking-wider">{label}</span>
      </div>

      <p className="text-[11px] font-mono text-slate-400 max-w-sm">{sublabel}</p>
    </div>
  );
};

