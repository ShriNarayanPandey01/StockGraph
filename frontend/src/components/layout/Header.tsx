import React from 'react';
import { Network, ArrowRight } from 'lucide-react';

interface HeaderProps {
  onExploreClick: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onExploreClick }) => {
  return (
    <header className="sticky top-0 z-40 border-b border-white/10 bg-ink-0/85 backdrop-blur-md px-6 py-4 transition-colors">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        {/* Brand / Logo */}
        <div className="flex items-center gap-6">
          <a href="#" className="flex items-center gap-2.5 group">
            <div className="h-8 w-8 rounded-lg bg-gradient-to-tr from-sky-500 via-indigo-500 to-purple-500 p-0.5 shadow-lg shadow-sky-500/20 group-hover:shadow-sky-500/40 transition">
              <div className="h-full w-full bg-ink-1 rounded-[6px] flex items-center justify-center">
                <Network className="w-4 h-4 text-sky-400 group-hover:rotate-12 transition-transform duration-300" />
              </div>
            </div>
            <div>
              <div className="font-bold text-base tracking-tight text-white flex items-center gap-2">
                stockGraph
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20">
                  Phase 1 Live
                </span>
              </div>
              <p className="text-[11px] font-mono text-slate-400">
                Temporal GraphRAG for Indian Equities
              </p>
            </div>
          </a>
        </div>

        {/* Navigation links */}
        <nav className="hidden lg:flex items-center gap-7 text-sm font-medium text-slate-300">
          <a
            href="#interactive-graph"
            className="hover:text-white transition flex items-center gap-1.5"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-sky-400"></span>
            Constellation Graph
          </a>
          <a href="#pillars" className="hover:text-white transition">
            4 Core Pillars
          </a>
          <a href="#architecture" className="hover:text-white transition">
            Dual-Store Arch
          </a>
          <a href="#api-section" className="hover:text-white transition">
            API & MCP Server
          </a>
        </nav>

        {/* CTA Button */}
        <div className="flex items-center gap-3">
          <button
            onClick={onExploreClick}
            className="bg-white hover:bg-slate-200 text-black font-semibold text-xs px-4 py-2 rounded-none transition active:scale-95 flex items-center gap-2 tracking-tight shadow-sm"
          >
            <span>Explore Graph</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </header>
  );
};

