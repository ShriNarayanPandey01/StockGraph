import React from 'react';
import { Database, Network, Check } from 'lucide-react';
import { FALKORDB_FEATURES, TIMESCALEDB_FEATURES } from '../../data/dualStoreData';
import { DualStore3DVisualizer } from './DualStore3DVisualizer';
import { InteractiveSqlGraphic } from './InteractiveSqlGraphic';

export const DualStoreArchitecture: React.FC = () => {
  return (
    <section id="architecture" className="py-16 px-6 max-w-7xl mx-auto border-t border-white/5">
      <div className="glass-panel rounded-3xl p-6 sm:p-8 border border-white/10 bg-ink-1/80">
        <div className="text-center max-w-2xl mx-auto mb-8">
          <div className="text-xs font-mono text-sky-400 uppercase tracking-widest">
            Strict Dual-Store Separation
          </div>
          <h2 className="text-2xl sm:text-3xl font-extrabold text-white mt-1">
            Numbers in SQL. Relationships in FalkorDB.
          </h2>
          <p className="text-xs sm:text-sm text-slate-400 mt-2">
            Rule 2 of our architectural invariant: Never store floating-point numeric series in graph node properties.
          </p>
        </div>

        {/* Interactive Three.js 3D Dual-Store Architecture Visualizer */}
        <DualStore3DVisualizer />

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-stretch">
          {/* Left: FalkorDB Graph */}
          <div className="bg-ink-0/90 rounded-2xl p-6 border border-sky-500/30 relative overflow-hidden flex flex-col justify-between">
            <div className="absolute -top-12 -right-12 w-36 h-36 bg-sky-500/10 rounded-full blur-2xl pointer-events-none"></div>
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="text-xs font-mono font-bold text-sky-400 flex items-center gap-1.5">
                  <Network className="w-3.5 h-3.5 text-sky-400" />
                  <span>FALKORDB (GRAPH + VECTOR RAG)</span>
                </span>
                <span className="text-[11px] font-mono text-slate-500">
                  Cypher + vecf32
                </span>
              </div>
              <ul className="space-y-3 text-xs text-slate-300">
                {FALKORDB_FEATURES.map((feat, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-sky-400 shrink-0 mt-0.5" />
                    <span>
                      <strong className="text-white">{feat.title}:</strong> {feat.description}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="mt-6 pt-4 border-t border-white/5 font-mono text-[11px] text-slate-400 bg-black/40 p-3 rounded-lg">
              CALL db.idx.vector.queryNodes(&apos;NewsEvent&apos;, &apos;embedding&apos;, 5, vecf32($emb))
            </div>
          </div>

          {/* Right: TimescaleDB */}
          <div className="bg-ink-0/90 rounded-2xl p-6 border border-indigo-500/30 relative overflow-hidden flex flex-col justify-between">
            <div className="absolute -top-12 -right-12 w-36 h-36 bg-indigo-500/10 rounded-full blur-2xl pointer-events-none"></div>
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="text-xs font-mono font-bold text-indigo-400 flex items-center gap-1.5">
                  <Database className="w-3.5 h-3.5 text-indigo-400" />
                  <span>POSTGRESQL / TIMESCALEDB</span>
                </span>
                <span className="text-[11px] font-mono text-slate-500">
                  Hypertable Series
                </span>
              </div>
              <ul className="space-y-3 text-xs text-slate-300">
                {TIMESCALEDB_FEATURES.map((feat, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
                    <span>
                      <strong className="text-white">{feat.title}:</strong> {feat.description}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="mt-6 pt-4 border-t border-white/5 font-mono text-[11px] text-slate-400 bg-black/40 p-3 rounded-lg">
              SELECT * FROM daily_stock_metrics WHERE session_type = &apos;CLOSE&apos; AND abs(delivery_20d_zscore) &gt;= 1.8
            </div>
          </div>
        </div>

        {/* Interactive SQL vs Graph Explorer */}
        <InteractiveSqlGraphic />
      </div>
    </section>
  );
};
