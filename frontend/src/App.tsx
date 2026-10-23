import React, { useState, useEffect } from 'react';
import { GRAPH_ENTITIES } from './data/mockGraphData';
import { TopAnnouncement } from './components/layout/TopAnnouncement';
import { Header } from './components/layout/Header';
import { HeroSection } from './components/hero/HeroSection';
import { ConstellationSection } from './components/constellation/ConstellationSection';
import { TechnicalPillars } from './components/pillars/TechnicalPillars';
import { DualStoreArchitecture } from './components/architecture/DualStoreArchitecture';
import { ApiSandbox } from './components/api/ApiSandbox';
import { Footer } from './components/layout/Footer';
import { DetailedViewModal } from './components/modal/DetailedViewModal';
import { CommandPaletteModal } from './components/modal/CommandPaletteModal';

export const App: React.FC = () => {
  const [activeEntityId, setActiveEntityId] = useState<string | null>(null);
  const [isDetailedModalOpen, setIsDetailedModalOpen] = useState(false);
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(true);

  const activeEntity = activeEntityId ? (GRAPH_ENTITIES[activeEntityId] || null) : null;

  // Sync dark mode class on document element
  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.classList.add('dark');
      document.documentElement.classList.remove('light');
    } else {
      document.documentElement.classList.add('light');
      document.documentElement.classList.remove('dark');
    }
  }, [isDarkMode]);

  // Global Keyboard shortcuts: Cmd+K / Ctrl+K and Escape
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setIsCommandPaletteOpen((prev) => !prev);
      }
      if (e.key === 'Escape') {
        setIsCommandPaletteOpen(false);
        setIsDetailedModalOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleSelectEntity = (id: string | null) => {
    if (!id) {
      setActiveEntityId(null);
      return;
    }
    if (GRAPH_ENTITIES[id]) {
      setActiveEntityId(id);
    }
  };

  const handleExploreClick = () => {
    const el = document.getElementById('interactive-graph');
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  const handleJumpSection = (selector: string) => {
    const el = document.querySelector(selector);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-ink-0 text-slate-100 transition-colors duration-200">
      {/* Top Announcement Bar */}
      <TopAnnouncement
        isDarkMode={isDarkMode}
        onToggleTheme={() => setIsDarkMode(!isDarkMode)}
        onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
      />

      {/* Main Navigation Header */}
      <Header onExploreClick={handleExploreClick} />

      {/* Main Landing Page Content */}
      <main className="flex-1">
        {/* 1. Hero Section with Three.js Rocket Launch Simulation */}
        <HeroSection
          onSelectTicker={(ticker) => {
            handleSelectEntity(ticker);
            handleExploreClick();
          }}
          onExploreClick={handleExploreClick}
        />

        {/* 2. Interactive Constellation Graph Section */}
        <ConstellationSection
          entities={GRAPH_ENTITIES}
          activeEntity={activeEntity}
          onSelectEntity={handleSelectEntity}
          onOpenDetailedView={() => setIsDetailedModalOpen(true)}
        />

        {/* 3. Four Core Technical Pillars */}
        <TechnicalPillars />

        {/* 4. Dual-Store Architecture with Interactive SQL Hypertable Sandbox */}
        <DualStoreArchitecture />

        {/* 5. REST & MCP Tool Server Sandbox */}
        <ApiSandbox />
      </main>

      {/* Footer */}
      <Footer />

      {/* Modals & Overlays */}
      {activeEntity && (
        <DetailedViewModal
          isOpen={isDetailedModalOpen}
          onClose={() => setIsDetailedModalOpen(false)}
          entity={activeEntity}
        />
      )}

      <CommandPaletteModal
        isOpen={isCommandPaletteOpen}
        onClose={() => setIsCommandPaletteOpen(false)}
        entities={GRAPH_ENTITIES}
        onSelectEntity={(id) => {
          handleSelectEntity(id);
          handleExploreClick();
        }}
        onJumpSection={handleJumpSection}
      />
    </div>
  );
};

export default App;

