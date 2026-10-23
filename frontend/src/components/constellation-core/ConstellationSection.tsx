import React, { useState } from 'react';
import { GraphEntity } from '../../types/graph';
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
    <section id="interactive-graph" className="relative w-full h-screen min-h-[720px] overflow-hidden bg-[#07090e] border-y border-white/10 flex flex-col justify-between">
      {/* Top Section Header */}
      <div className="relative z-20 px-6 pt-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 pointer-events-none">
        <div className="pointer-events-auto bg-ink-0/60 backdrop-blur-md p-3.5 rounded-2xl border border-white/10 max-w-md shadow-2xl">
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
      </div>

      {/* Floating Center Search Pill */}
      <GraphSearchPill
        searchQuery={searchQuery}
        activeType={activeEntity?.type}
        onSearchChange={handleSearchChange}
        onClear={handleClearSearch}
      />

      {/* Interactive Full-Screen Canvas */}
      <ConstellationCanvas
        activeEntity={activeEntity}
        onSelectEntity={(id) => {
          onSelectEntity(id);
          setSearchQuery(id);
        }}
        onOpenDetailedView={onOpenDetailedView}
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
