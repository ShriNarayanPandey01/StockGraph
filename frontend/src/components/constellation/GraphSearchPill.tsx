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
    <div className="absolute bottom-6 sm:bottom-8 left-1/2 -translate-x-1/2 w-full max-w-lg px-4 z-30 pointer-events-auto">
      <div className="glass-panel rounded-full px-5 py-3 shadow-[0_0_40px_rgba(0,0,0,0.85)] flex items-center justify-between gap-3 border border-white/20 bg-black/85 backdrop-blur-xl">
        <div className="flex items-center gap-2.5 flex-1 min-w-0">
          <Search className="w-4 h-4 text-slate-400 shrink-0" />
          <span className="text-slate-300 text-xs font-mono font-medium hidden sm:inline whitespace-nowrap">
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
          <span className="text-[11px] font-mono px-2.5 py-0.5 rounded-full bg-white/10 text-slate-200 border border-white/20">
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
