import React, { useState } from 'react';
import { GraphEntity, GraphMode } from '../../types/graph';
import { ConstellationCanvas } from './ConstellationCanvas';
import { GraphSearchPill } from './GraphSearchPill';
import { BottomDock } from './BottomDock';
import { Sparkles, Maximize2 } from 'lucide-react';

interface ConstellationSectionProps {
  entities: Record<string, GraphEntity>;
  activeEntity: GraphEntity | null;
  onSelectEntity: (id: string | null) => void;
  onOpenDetailedView: () => void;
}

export const ConstellationSection: React.FC<ConstellationSectionProps> = ({
  entities,
  activeEntity,
  onSelectEntity,
  onOpenDetailedView,
}) => {
  const [graphMode, setGraphMode] = useState<GraphMode>('constellation');
  const [searchQuery, setSearchQuery] = useState(activeEntity?.id || '');

  const handleSearchChange = (val: string) => {
    setSearchQuery(val);
    const upper = val.trim().toUpperCase();
    if (entities[upper]) {
      onSelectEntity(upper);
    }
  };

  const handleClearSearch = () => {
    setSearchQuery('');
    onSelectEntity(null);
  };

  return (
    <section id="interactive-graph" className="relative w-full h-screen min-h-[720px] overflow-hidden bg-[#0b0c0e] border-y border-white/10 flex flex-col justify-between">
      {/* Top Floating Explorer Bar / Section Header */}
      <div className="relative z-20 px-6 pt-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 pointer-events-none">
        <div className="pointer-events-auto bg-ink-0/60 backdrop-blur-md p-3 rounded-2xl border border-white/10 max-w-lg">
          <div className="flex items-center gap-2 text-xs font-mono text-sky-400 uppercase tracking-widest">
            <Sparkles className="w-3.5 h-3.5 text-sky-400 animate-pulse" />
            <span>Full-Screen Celestial Explorer</span>
          </div>
          <h2 className="text-xl sm:text-2xl font-extrabold text-white mt-0.5">
            The StockGraph Constellation
          </h2>
          <p className="text-xs text-slate-400 mt-0.5 leading-snug">
            {activeEntity
              ? `Currently inspecting ${activeEntity.title}. Connected nodes blossom to input commodities, macro vectors, and filings.`
              : 'Hover or click any star to blossom its multi-hop second-order transmission graph.'}
          </p>
        </div>

        {/* View Mode Controls */}
        <div className="pointer-events-auto flex items-center gap-2 bg-ink-1/90 backdrop-blur-md border border-white/10 p-1.5 rounded-xl text-xs font-mono self-start sm:self-auto shadow-2xl">
          <button
            onClick={() => setGraphMode('constellation')}
            className={`px-3 py-1.5 rounded-lg font-medium transition ${
              graphMode === 'constellation'
                ? 'bg-sky-500/20 text-sky-300 border border-sky-500/30'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            Constellation
          </button>
          <button
            onClick={() => setGraphMode('cluster')}
            className={`px-3 py-1.5 rounded-lg font-medium transition ${
              graphMode === 'cluster'
                ? 'bg-sky-500/20 text-sky-300 border border-sky-500/30'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            Radial Cluster
          </button>
          <button
            onClick={() => setGraphMode('linear')}
            className={`px-3 py-1.5 rounded-lg font-medium transition ${
              graphMode === 'linear'
                ? 'bg-sky-500/20 text-sky-300 border border-sky-500/30'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            Linear Flow
          </button>
        </div>
      </div>

      {/* Interactive Full-Screen Canvas */}
      <ConstellationCanvas
        activeEntity={activeEntity}
        onSelectEntity={(id) => {
          onSelectEntity(id);
          setSearchQuery(id);
        }}
        onOpenDetailedView={onOpenDetailedView}
      />

      {/* Floating Search Pill at Top */}
      <GraphSearchPill
        searchQuery={searchQuery}
        activeType={activeEntity?.type}
        onSearchChange={handleSearchChange}
        onClear={handleClearSearch}
      />

      {/* Bottom Floating Control Dock */}
      <BottomDock
        entity={activeEntity}
        onOpenDetailedView={onOpenDetailedView}
      />

      {/* Bottom-left helper hint */}
      <div className="absolute bottom-3 left-6 text-[11px] font-mono text-slate-500 pointer-events-none hidden sm:flex items-center gap-2 z-20">
        <Maximize2 className="w-3 h-3 text-sky-400" />
        <span>Full-Screen Canvas • Hover any celestial node to explore • ⌘K to jump</span>
      </div>
    </section>
  );
};
