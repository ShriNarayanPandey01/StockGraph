import React, { useState } from 'react';
import { Check, Copy, Terminal } from 'lucide-react';
import { API_SNIPPETS } from '../../data/apiSnippets';
import { ApiSnippetKey } from '../../types/api';

export const ApiSandbox: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ApiSnippetKey>('curl');
  const [copied, setCopied] = useState(false);

  const currentSnippet = API_SNIPPETS[activeTab];

  const handleCopy = () => {
    navigator.clipboard.writeText(currentSnippet.code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section id="api-section" className="py-16 px-6 max-w-7xl mx-auto border-t border-white/5">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-8">
        <div>
          <div className="text-xs font-mono text-sky-400 uppercase tracking-widest">
            Developer & Agent Access
          </div>
          <h2 className="text-3xl font-extrabold text-white mt-1">
            REST API & MCP Tool Server
          </h2>
          <p className="text-xs sm:text-sm text-slate-400 mt-2 max-w-2xl">
            Consume StockGraph directly in your Python quantitative pipelines, or wire the Model Context Protocol (MCP) server directly into Claude Desktop or Cursor IDE.
          </p>
        </div>

        {/* Tab Switcher */}
        <div className="flex items-center gap-1 bg-ink-1 border border-white/10 p-1 rounded-xl text-xs font-mono">
          {(Object.keys(API_SNIPPETS) as ApiSnippetKey[]).map((key) => {
            const item = API_SNIPPETS[key];
            const isActive = activeTab === key;
            return (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`px-3 py-1.5 rounded-lg font-medium transition ${
                  isActive
                    ? 'bg-sky-500/20 text-sky-300 font-semibold border border-sky-500/30'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                {item.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Code Display Window */}
      <div className="rounded-2xl border border-white/15 bg-ink-0 overflow-hidden shadow-2xl font-mono text-xs">
        <div className="bg-ink-1/90 px-4 py-2.5 border-b border-white/10 flex items-center justify-between text-slate-400">
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-full bg-rose-500/80 inline-block"></span>
            <span className="h-3 w-3 rounded-full bg-amber-500/80 inline-block"></span>
            <span className="h-3 w-3 rounded-full bg-emerald-500/80 inline-block"></span>
            <span className="ml-2 text-slate-300 flex items-center gap-1.5">
              <Terminal className="w-3.5 h-3.5 text-sky-400" />
              <span>{currentSnippet.title}</span>
            </span>
          </div>

          <button
            onClick={handleCopy}
            className="hover:text-white transition flex items-center gap-1.5 text-xs text-slate-400"
            title="Copy snippet to clipboard"
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-emerald-400">Copied! ✓</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5 text-slate-400" />
                <span>Copy Snippet</span>
              </>
            )}
          </button>
        </div>

        <pre className="p-6 text-slate-300 overflow-x-auto leading-relaxed max-h-96 selection:bg-sky-500/30">
          {currentSnippet.code}
        </pre>
      </div>
    </section>
  );
};

