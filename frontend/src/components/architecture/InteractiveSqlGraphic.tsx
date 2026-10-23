import React, { useState } from 'react';
import { Database, Network, GitBranch, CheckCircle2, Play, AlertCircle, RefreshCw } from 'lucide-react';
import { SAMPLE_SQL_ROWS } from '../../data/dualStoreData';
import {
  TimescaleStreamLoader,
  FalkorGraphLoader,
  DualStorePipelineLoader,
} from '../shared/ContentLoaders';

export const InteractiveSqlGraphic: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'sql' | 'graph' | 'flow'>('sql');
  const [filterAnomalies, setFilterAnomalies] = useState(false);
  const [selectedRow, setSelectedRow] = useState<number | null>(0);
  const [isLoading, setIsLoading] = useState(false);

  const handleTabChange = (tab: 'sql' | 'graph' | 'flow') => {
    if (tab === activeTab) return;
    setIsLoading(true);
    setActiveTab(tab);
    setTimeout(() => {
      setIsLoading(false);
    }, 700);
  };

  const handleRunQuery = () => {
    setIsLoading(true);
    setTimeout(() => {
      setIsLoading(false);
    }, 850);
  };

  const displayedRows = filterAnomalies
    ? SAMPLE_SQL_ROWS.filter((r) => Math.abs(r.delivery_20d_zscore) >= 1.8)
    : SAMPLE_SQL_ROWS;

  return (
    <div className="mt-8 rounded-2xl border border-white/10 bg-ink-0/90 overflow-hidden shadow-2xl">
      {/* Top Graphic Toolbar */}
      <div className="bg-ink-1/90 px-4 py-3 border-b border-white/10 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            onClick={() => handleTabChange('sql')}
            className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium flex items-center gap-1.5 transition ${
              activeTab === 'sql'
                ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/30'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <Database className="w-3.5 h-3.5 text-indigo-400" />
            <span>TimescaleDB (Hypertable)</span>
          </button>

          <button
            onClick={() => handleTabChange('graph')}
            className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium flex items-center gap-1.5 transition ${
              activeTab === 'graph'
                ? 'bg-sky-500/20 text-sky-300 border border-sky-500/30'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <Network className="w-3.5 h-3.5 text-sky-400" />
            <span>FalkorDB (Graph + vecf32)</span>
          </button>

          <button
            onClick={() => handleTabChange('flow')}
            className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium flex items-center gap-1.5 transition ${
              activeTab === 'flow'
                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <GitBranch className="w-3.5 h-3.5 text-emerald-400" />
            <span>Dual-Store Pipeline Flow</span>
          </button>
        </div>

        <div className="flex items-center gap-2">
          {activeTab === 'sql' && (
            <button
              onClick={() => {
                setFilterAnomalies(!filterAnomalies);
                handleRunQuery();
              }}
              className={`px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1.5 border transition ${
                filterAnomalies
                  ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                  : 'bg-white/5 text-slate-400 border-white/10 hover:text-white'
              }`}
            >
              <AlertCircle className="w-3 h-3 text-amber-400" />
              <span>{filterAnomalies ? 'Showing Anomaly abs(z) ≥ 1.8' : 'Filter Anomaly Rows'}</span>
            </button>
          )}

          <button
            onClick={handleRunQuery}
            disabled={isLoading}
            className="px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1.5 bg-white/5 hover:bg-white/10 text-slate-300 border border-white/10 transition"
          >
            <RefreshCw className={`w-3 h-3 text-sky-400 ${isLoading ? 'animate-spin' : ''}`} />
            <span>{isLoading ? 'Querying...' : 'Re-run Query'}</span>
          </button>
        </div>
      </div>

      {/* Dynamic Content Loading Animations based on Active Store */}
      {isLoading ? (
        <div className="p-8">
          {activeTab === 'sql' && (
            <TimescaleStreamLoader
              label="Scanning TimescaleDB daily_stock_metrics..."
              sublabel="Filtering session_type = 'CLOSE' with Official NSE Bhavcopy delivery %"
            />
          )}
          {activeTab === 'graph' && (
            <FalkorGraphLoader
              label="Executing OpenCypher Traversal & Vector Search..."
              sublabel="MATCH (s:Stock)-[r:EXPOSED_TO]->(c:Commodity) | vecf32($emb)"
            />
          )}
          {activeTab === 'flow' && (
            <DualStorePipelineLoader
              label="Simulating Cross-Service Outbox Sync..."
              sublabel="Upstox Service (SQL) ⟷ StockGraph Engine (FalkorDB)"
            />
          )}
        </div>
      ) : (
        <>
          {/* Tab 1: SQL Interactive Table */}
          {activeTab === 'sql' && (
            <div className="p-4 sm:p-6 font-mono text-xs">
              <div className="flex items-center justify-between mb-3 text-slate-400">
                <div className="flex items-center gap-2">
                  <span className="text-emerald-400 font-bold">$</span>
                  <span className="text-slate-300">
                    SELECT trade_date, session_type, ticker, close_price, delivery_pct, delivery_20d_zscore FROM daily_stock_metrics
                  </span>
                </div>
                <span className="text-[11px] text-slate-500">Live Query Sandbox</span>
              </div>

              <div className="overflow-x-auto rounded-xl border border-white/10 bg-ink-1">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-white/10 bg-black/40 text-[11px] text-slate-400 uppercase tracking-wider">
                      <th className="p-3">Trade Date</th>
                      <th className="p-3">Session</th>
                      <th className="p-3">Ticker</th>
                      <th className="p-3">Price (₹)</th>
                      <th className="p-3">Delivery %</th>
                      <th className="p-3">20D Z-Score</th>
                      <th className="p-3">P/E</th>
                      <th className="p-3">Source Provenance</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {displayedRows.map((row, idx) => {
                      const isAnomaly = Math.abs(row.delivery_20d_zscore) >= 1.8;
                      const isSelected = selectedRow === idx;
                      return (
                        <tr
                          key={idx}
                          onClick={() => setSelectedRow(idx)}
                          className={`cursor-pointer transition ${
                            isSelected
                              ? 'bg-indigo-500/15 text-white'
                              : 'hover:bg-white/5 text-slate-300'
                          }`}
                        >
                          <td className="p-3">{row.trade_date}</td>
                          <td className="p-3">
                            <span
                              className={`px-1.5 py-0.5 rounded text-[10px] ${
                                row.session_type === 'CLOSE'
                                  ? 'bg-indigo-500/20 text-indigo-300'
                                  : 'bg-slate-700 text-slate-300'
                              }`}
                            >
                              {row.session_type}
                            </span>
                          </td>
                          <td className="p-3 font-bold text-white">{row.ticker}</td>
                          <td className="p-3">₹{row.close_price.toFixed(2)}</td>
                          <td className="p-3">
                            <span className="font-semibold text-sky-400">
                              {row.delivery_pct > 0 ? `${row.delivery_pct}%` : '—'}
                            </span>
                          </td>
                          <td className="p-3">
                            <span
                              className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                                isAnomaly
                                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                                  : 'text-slate-400'
                              }`}
                            >
                              {row.delivery_20d_zscore !== 0
                                ? (row.delivery_20d_zscore > 0 ? `+${row.delivery_20d_zscore}` : row.delivery_20d_zscore)
                                : '0.00'}
                            </span>
                          </td>
                          <td className="p-3">{row.pe_ratio}</td>
                          <td className="p-3 text-[11px] text-slate-500">
                            {row.vendor_id}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {selectedRow !== null && displayedRows[selectedRow] && (
                <div className="mt-4 p-3 rounded-xl bg-ink-2 border border-white/10 flex items-center justify-between text-xs text-slate-300">
                  <div className="flex items-center gap-3">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span>
                      <strong>Provenance Verified:</strong> Staged in <code className="text-indigo-300">vendor_quotes_raw</code> with key <code className="text-slate-200">({displayedRows[selectedRow].vendor_id}, {displayedRows[selectedRow].ticker}, {displayedRows[selectedRow].trade_date})</code>
                    </span>
                  </div>
                  <span className="text-[11px] text-slate-500 font-mono">
                    as_of: {displayedRows[selectedRow].vendor_as_of}
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Tab 2: FalkorDB Graph Traversal Sandbox */}
          {activeTab === 'graph' && (
            <div className="p-4 sm:p-6 font-mono text-xs">
              <div className="flex items-center justify-between mb-3 text-slate-400">
                <div className="flex items-center gap-2">
                  <Play className="w-3.5 h-3.5 text-sky-400" />
                  <span className="text-slate-200">
                    MATCH (s:Stock {`{ticker: 'TATASTEEL'}`})-[r:EXPOSED_TO]-&gt;(c:Commodity) RETURN s, r, c
                  </span>
                </div>
                <span className="text-sky-400">OpenCypher Traversal</span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="p-4 rounded-xl bg-ink-1 border border-sky-500/20">
                  <div className="text-slate-400 text-[11px] uppercase mb-1">Source Node</div>
                  <div className="text-base font-bold text-white">:Stock {"{ticker: 'TATASTEEL'}"}</div>
                  <div className="text-slate-400 text-xs mt-2 space-y-1">
                    <div>sector: &quot;Metals &amp; Mining&quot;</div>
                    <div>exchange: &quot;NSE&quot;</div>
                    <div>isin: &quot;INE081A01020&quot;</div>
                    <div className="text-sky-400">profile_embedding: vecf32([0.14, -0.32, ...])</div>
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-ink-1 border border-amber-500/20">
                  <div className="text-slate-400 text-[11px] uppercase mb-1">Traversed Edge</div>
                  <div className="text-base font-bold text-amber-400">[:EXPOSED_TO]</div>
                  <div className="text-slate-400 text-xs mt-2 space-y-1">
                    <div>confidence: 0.88</div>
                    <div>margin_impact: &quot;NEGATIVE&quot;</div>
                    <div>is_latest: true</div>
                    <div>valid_from_ts: 1729728000</div>
                    <div className="text-emerald-400">status: CONFIRMED_DYNAMIC</div>
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-ink-1 border border-purple-500/20">
                  <div className="text-slate-400 text-[11px] uppercase mb-1">Target Entity</div>
                  <div className="text-base font-bold text-purple-300">:Commodity {"{id: 'COKING_COAL'}"}</div>
                  <div className="text-slate-400 text-xs mt-2 space-y-1">
                    <div>benchmark: &quot;Platts Premium Low Vol&quot;</div>
                    <div>origin: &quot;Australia East Coast&quot;</div>
                    <div>related_ids: [&quot;HRC_STEEL&quot;]</div>
                    <div className="text-purple-400">transmissions: Blast Furnace Cost</div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Tab 3: Dual-Store Pipeline Flow */}
          {activeTab === 'flow' && (
            <div className="p-6 text-xs font-mono">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="p-4 rounded-xl bg-indigo-950/20 border border-indigo-500/30">
                  <div className="flex items-center gap-2 text-indigo-400 font-bold mb-3">
                    <Database className="w-4 h-4" />
                    <span>NUMERIC SERIES PIPELINE (TimescaleDB)</span>
                  </div>
                  <ol className="space-y-2 text-slate-300 list-decimal list-inside">
                    <li>NSE Official Bhavcopy CSV download at 19:00 PM IST</li>
                    <li>Raw payload logged immutably into <code className="text-indigo-300">vendor_quotes_raw</code></li>
                    <li>Normalized into <code className="text-indigo-300">daily_stock_metrics (OPEN, CLOSE)</code></li>
                    <li>20-day delivery z-scores mathematically computed in SQL</li>
                    <li>Every quant metric permanently cites <code className="text-slate-200">vendor_id + vendor_as_of</code></li>
                  </ol>
                </div>

                <div className="p-4 rounded-xl bg-sky-950/20 border border-sky-500/30">
                  <div className="flex items-center gap-2 text-sky-400 font-bold mb-3">
                    <Network className="w-4 h-4" />
                    <span>KNOWLEDGE & VECTOR GRAPH PIPELINE (FalkorDB)</span>
                  </div>
                  <ol className="space-y-2 text-slate-300 list-decimal list-inside">
                    <li>30m Reg-30 announcements & news ingestion</li>
                    <li>L1-L4 Deduplication filter prevents redundant nodes</li>
                    <li>Canonical node catalog checks: zero free-text IDs</li>
                    <li>LLM DynamicOntologyBuilder with injected context cards</li>
                    <li>Bi-temporal rotation with <code className="text-sky-300">[:SUPERSEDES]</code> for latest reality</li>
                  </ol>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};
