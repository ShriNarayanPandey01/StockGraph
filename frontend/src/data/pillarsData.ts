export interface TechnicalPillar {
  number: string;
  badge: string;
  storeTag: string;
  title: string;
  description: string;
  codeSnippets: string[];
  accentColor: 'sky' | 'amber' | 'purple' | 'emerald';
}

export const TECHNICAL_PILLARS: TechnicalPillar[] = [
  {
    number: '01',
    badge: '01 / FIRST-ORDER FACTS',
    storeTag: 'TimescaleDB Primary',
    title: 'Official Exchange Bhavcopy & Reg-30 Ground Truth',
    description: 'Never rely on scraped or approximate trading volume. StockGraph uses official NSE Bhavcopy (sec_bhavdata_full.csv) as the immutable source of truth for Delivery % and institutional turnover, computing 20-day delivery z-scores mathematically in SQL.',
    codeSnippets: [
      '2 Checkpoints/Day (OPEN/CLOSE)',
      'Bulk/Block CSV Deals',
      'SEBI SAST Insiders'
    ],
    accentColor: 'sky'
  },
  {
    number: '02',
    badge: '02 / SECOND-ORDER TRANSMISSION',
    storeTag: 'DynamicOntologyBuilder',
    title: 'Dynamic LLM Ontology with Context Injection',
    description: 'Static hand-coded graphs rot overnight. When an LLM evaluates stock relationships, StockGraph injects a rich StockContextCard (business model, raw materials, revenue segments, and concall guidance). The LLM determines margin sensitivity with enforced confidence floors (≥ 0.65).',
    codeSnippets: [
      '[:EXPOSED_TO]',
      '[:SENSITIVE_TO_MACRO]',
      '[:RELATED_TO] Commodities'
    ],
    accentColor: 'amber'
  },
  {
    number: '03',
    badge: '03 / MULTI-DAY NARRATIVE CHAINS',
    storeTag: 'NewsCorrelator (L1-L4)',
    title: 'Four-Layer Deduplication & Cross-News Correlation',
    description: 'Unfolding market stories arrive across multiple days from different providers. StockGraph executes L1 URL deduplication, L2 headline normalization, L3 vector deduplication (cosine ≥ 0.92), and L4 causal chaining ([:CORRELATED_WITH]) to reconstruct full market narrative arcs.',
    codeSnippets: [
      'Deterministic SHA-1 IDs',
      '14-Day Trailing Window',
      'CAUSAL_CHAIN Edges'
    ],
    accentColor: 'purple'
  },
  {
    number: '04',
    badge: '04 / BI-TEMPORAL DOSSIER RAG',
    storeTag: 'Fixed Windows Only',
    title: 'Strict Temporal Filtering & Superseding Nodes',
    description: 'Standard RAG suffers from "temporal collapse" (retrieving old Q1 guidance alongside Q3). StockGraph queries are strictly bounded to window=LAST_6M | LAST_1Y. Outdated quarterly ratios rotate with [:SUPERSEDES] links, ensuring your agent views the exact state of reality.',
    codeSnippets: [
      'valid_from_ts / valid_to_ts',
      'is_latest: Boolean',
      'Cacheable 2-Key Storage'
    ],
    accentColor: 'emerald'
  }
];

