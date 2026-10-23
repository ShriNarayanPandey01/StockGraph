import React from 'react';

export const Footer: React.FC = () => {
  return (
    <footer className="border-t border-white/10 bg-ink-0 py-12 px-6">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-start md:items-center justify-between gap-8">
        <div>
          <div className="flex items-center gap-2 font-bold text-base text-white">
            <span>stockGraph</span>
            <span className="text-xs font-mono text-slate-500 font-normal">
              v1.0 (Production Core)
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1 max-w-sm">
            High-performance temporal stock intelligence. Dual-store separation powered by FalkorDB, TimescaleDB, and Upstox adapter.
          </p>
          <div className="mt-4 flex items-center gap-3 text-xs font-mono text-slate-400">
            <a
              href="#api-section"
              className="hover:text-sky-400 transition underline underline-offset-4"
            >
              The whole site, plain markdown mirror
            </a>
            <span>·</span>
            <a href="#api-section" className="hover:text-sky-400 transition">
              OpenAPI JSON (:8000)
            </a>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-8 text-xs font-mono text-slate-400">
          <div>
            <div className="text-white font-bold mb-2">SERVICES</div>
            <ul className="space-y-1.5">
              <li><span className="text-slate-200">StockGraph API</span> (:8000)</li>
              <li><span className="text-slate-200">Upstox Ingestor</span> (:8001)</li>
              <li><span className="text-slate-200">FalkorDB Graph</span> (:6379)</li>
              <li><span className="text-slate-200">TimescaleDB</span> (:5432)</li>
            </ul>
          </div>
          <div>
            <div className="text-white font-bold mb-2">CADENCES</div>
            <ul className="space-y-1.5">
              <li>30m News & Reg-30</li>
              <li>09:30 AM Market Open</li>
              <li>19:00 PM Bhavcopy EOD</li>
              <li>Quarterly Guidance RAG</li>
            </ul>
          </div>
          <div>
            <div className="text-white font-bold mb-2">STANDARDS</div>
            <ul className="space-y-1.5">
              <li>Strict Window Bounds</li>
              <li>No Graph Numbers</li>
              <li>Bhavcopy Primacy</li>
              <li>Zero Free-Text IDs</li>
            </ul>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto mt-12 pt-6 border-t border-white/5 flex flex-col sm:flex-row items-center justify-between gap-4 text-[11px] font-mono text-slate-500">
        <div>© 2026 StockGraph Engine. Designed for Quantitative Trading & Fundamental Equities.</div>
        <div>Engineered against hallucination with dual-store validation.</div>
      </div>
    </footer>
  );
};

