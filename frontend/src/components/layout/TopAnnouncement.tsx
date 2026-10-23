import React from 'react';
import { Sun, Moon, Terminal } from 'lucide-react';

interface TopAnnouncementProps {
  isDarkMode: boolean;
  onToggleTheme: () => void;
  onOpenCommandPalette: () => void;
}

export const TopAnnouncement: React.FC<TopAnnouncementProps> = ({
  isDarkMode,
  onToggleTheme,
  onOpenCommandPalette,
}) => {
  return (
    <div className="border-b border-white/5 bg-ink-0/80 backdrop-blur px-4 py-1.5 text-xs font-mono text-slate-400 flex items-center justify-between z-30 relative">
      <div className="flex items-center gap-3">
        <span className="inline-flex items-center gap-1.5 text-emerald-400 font-medium">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-ping"></span>
          FALKORDB + TIMESCALEDB DUAL-STORE ACTIVE
        </span>
        <span className="hidden md:inline text-slate-600">|</span>
        <span className="hidden md:inline text-slate-400">
          NSE Official Bhavcopy EOD Synced · 30m Reg-30 Pipeline
        </span>
      </div>

      <div className="flex items-center gap-4">
        <button
          onClick={onToggleTheme}
          className="hover:text-white transition flex items-center gap-1.5 text-slate-400"
          title="Toggle Theme"
        >
          {isDarkMode ? (
            <>
              <Sun className="w-3.5 h-3.5 text-amber-400" />
              <span className="hidden sm:inline">Light Mode</span>
            </>
          ) : (
            <>
              <Moon className="w-3.5 h-3.5 text-sky-400" />
              <span className="hidden sm:inline">Dark Mode</span>
            </>
          )}
        </button>

        <a
          href="#api-section"
          className="hover:text-sky-400 transition hidden sm:inline"
        >
          REST & MCP Specs ↗
        </a>

        <span className="text-slate-600">|</span>

        <button
          onClick={onOpenCommandPalette}
          className="bg-white/5 hover:bg-white/10 text-slate-300 px-2 py-0.5 rounded border border-white/10 flex items-center gap-1 transition"
        >
          <Terminal className="w-3 h-3 text-sky-400" />
          <span>⌘K</span>
          <span className="text-slate-500 text-[11px] hidden sm:inline">Command</span>
        </button>
      </div>
    </div>
  );
};

