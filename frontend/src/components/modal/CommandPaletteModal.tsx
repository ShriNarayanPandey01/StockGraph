import React, { useState, useEffect } from 'react';
import { Terminal, ArrowRight } from 'lucide-react';
import { GraphEntity } from '../../types/graph';

interface CommandPaletteModalProps {
  isOpen: boolean;
  onClose: () => void;
  entities: Record<string, GraphEntity>;
  onSelectEntity: (id: string) => void;
  onJumpSection: (selector: string) => void;
}

export const CommandPaletteModal: React.FC<CommandPaletteModalProps> = ({
  isOpen,
  onClose,
  entities,
  onSelectEntity,
  onJumpSection,
}) => {
  const [filter, setFilter] = useState('');

  useEffect(() => {
    if (isOpen) {
      setFilter('');
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const entityList = Object.values(entities);
  const filteredEntities = entityList.filter(
    (e) =>
      e.id.toLowerCase().includes(filter.toLowerCase()) ||
      e.title.toLowerCase().includes(filter.toLowerCase()) ||
      e.sector.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div
      className="fixed inset-0 z-50 bg-black/75 backdrop-blur-md flex items-start justify-center pt-24 px-4 transition-all duration-200"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl bg-ink-1 rounded-2xl border border-white/20 shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Input Box */}
        <div className="p-3 border-b border-white/10 flex items-center gap-3 bg-ink-0/60">
          <Terminal className="text-slate-400 w-4 h-4" />
          <input
            type="text"
            placeholder="Type a ticker, commodity, or section name..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            autoFocus
            className="bg-transparent text-sm text-white w-full focus:outline-none font-mono"
          />
          <kbd className="text-[10px] font-mono bg-white/10 text-slate-300 px-1.5 py-0.5 rounded">
            ESC
          </kbd>
        </div>

        {/* Results List */}
        <div className="p-2 space-y-1 max-h-72 overflow-y-auto text-xs font-mono">
          <div className="text-[10px] text-slate-500 uppercase px-3 py-1 font-semibold">
            Entities & Tickers
          </div>
          {filteredEntities.map((item) => (
            <button
              key={item.id}
              onClick={() => {
                onSelectEntity(item.id);
                onClose();
              }}
              className="w-full text-left px-3 py-2 rounded-lg hover:bg-sky-500/20 text-slate-200 hover:text-sky-300 flex items-center justify-between transition group"
            >
              <div className="flex items-center gap-2">
                <span className="font-bold text-white group-hover:text-sky-300">
                  {item.id}
                </span>
                <span className="text-slate-400">· {item.title}</span>
                <span className="text-[10px] text-slate-500">({item.sector})</span>
              </div>
              <span className="text-[10px] text-slate-500 group-hover:text-sky-400 flex items-center gap-1">
                <span>Jump</span>
                <ArrowRight className="w-3 h-3" />
              </span>
            </button>
          ))}

          {filteredEntities.length === 0 && (
            <div className="text-center py-6 text-slate-500 text-xs">
              No matching entities found.
            </div>
          )}

          <div className="text-[10px] text-slate-500 uppercase px-3 py-1 font-semibold mt-2 border-t border-white/5">
            Quick Navigation
          </div>
          <button
            onClick={() => {
              onJumpSection('#interactive-graph');
              onClose();
            }}
            className="w-full text-left px-3 py-2 rounded-lg hover:bg-white/10 text-slate-300 flex items-center justify-between"
          >
            <span>The StockGraph Constellation</span>
            <span className="text-[10px] text-slate-500">Explorer</span>
          </button>
          <button
            onClick={() => {
              onJumpSection('#pillars');
              onClose();
            }}
            className="w-full text-left px-3 py-2 rounded-lg hover:bg-white/10 text-slate-300 flex items-center justify-between"
          >
            <span>Four Architectural Pillars</span>
            <span className="text-[10px] text-slate-500">Architecture</span>
          </button>
          <button
            onClick={() => {
              onJumpSection('#architecture');
              onClose();
            }}
            className="w-full text-left px-3 py-2 rounded-lg hover:bg-white/10 text-slate-300 flex items-center justify-between"
          >
            <span>Numbers in SQL. Relationships in FalkorDB.</span>
            <span className="text-[10px] text-slate-500">Dual-Store</span>
          </button>
          <button
            onClick={() => {
              onJumpSection('#api-section');
              onClose();
            }}
            className="w-full text-left px-3 py-2 rounded-lg hover:bg-white/10 text-slate-300 flex items-center justify-between"
          >
            <span>Documentation & REST Endpoints</span>
            <span className="text-[10px] text-slate-500">API Sandbox</span>
          </button>
        </div>
      </div>
    </div>
  );
};
