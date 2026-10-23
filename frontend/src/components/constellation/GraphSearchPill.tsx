import React from 'react';
import { X, Search } from 'lucide-react';

interface GraphSearchPillProps {
  searchQuery: string;
  activeType?: string;
  onSearchChange: (value: string) => void;
  onClear: () => void;
}

export const GraphSearchPill: React.FC<GraphSearchPillProps> = ({
  searchQuery,
  activeType,
  onSearchChange,
  onClear,
}) => {
  return (
    <div className="absolute top-6 inset-x-0 mx-auto w-full max-w-md px-4 z-20 pointer-events-auto">
      <div className="glass-panel rounded-full px-4 py-2.5 shadow-2xl flex items-center justify-between gap-3 border border-white/15 bg-ink-1/90">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <Search className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          <span className="text-slate-400 text-xs font-mono hidden sm:inline">
            I want to learn about:
          </span>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="bg-transparent text-sm font-semibold text-white focus:outline-none w-full placeholder-slate-500 truncate font-mono"
            placeholder="e.g. TATASTEEL, RELIANCE, CRUDE..."
          />
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-sky-500/20 text-sky-300 border border-sky-500/30">
            {activeType || 'All Nodes'}
          </span>
          {searchQuery && (
            <button
              onClick={onClear}
              className="h-6 w-6 rounded-full hover:bg-white/10 flex items-center justify-center text-slate-400 hover:text-white transition"
              title="Clear selection & return to full constellation"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

