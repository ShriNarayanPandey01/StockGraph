import React, { useState } from 'react';
import { GraphEntity } from '../../types/graph';
import { ConstellationCanvas } from './ConstellationCanvas';
import { GraphSearchPill } from './GraphSearchPill';

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
    <section
      id="interactive-graph"
      className="relative w-full h-screen min-h-[760px] overflow-hidden bg-black flex flex-col justify-between border-b border-white/10"
    >
      {/* Central Tagline Only — No paragraphs, no buttons, no eyebrow text */}
      <div className="absolute top-[44%] left-1/2 -translate-x-1/2 -translate-y-1/2 text-center pointer-events-none z-20 px-6 w-full max-w-4xl">
        <h1 className="text-4xl sm:text-6xl lg:text-7xl font-bold tracking-tight text-white leading-[1.08] drop-shadow-[0_10px_35px_rgba(0,0,0,0.9)]">
          The Stock Intelligence Engine That Connects The{' '}
          <span className="bg-gradient-to-b from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
            Invisible Dots.
          </span>
        </h1>
      </div>

      {/* Interactive Canvas (Nodes Surrounding the Central Tagline) */}
      <ConstellationCanvas
        activeEntity={activeEntity}
        onSelectEntity={(id) => {
          onSelectEntity(id);
          setSearchQuery(id);
        }}
        onOpenDetailedView={onOpenDetailedView}
      />

      {/* Floating Search Pill at the Bottom, Centered */}
      <GraphSearchPill
        searchQuery={searchQuery}
        activeType={activeEntity?.type}
        onSearchChange={handleSearchChange}
        onClear={handleClearSearch}
      />
    </section>
  );
};
