export interface DualStoreFeature {
  title: string;
  description: string;
}

export const FALKORDB_FEATURES: DualStoreFeature[] = [
  {
    title: 'Canonical Node Catalog',
    description: 'Stock, Commodity, MacroFactor, Sector nodes indexed by deterministic IDs and profiles.'
  },
  {
    title: 'Inferred Causal Edges',
    description: 'EXPOSED_TO, SENSITIVE_TO_MACRO, SUPPLIES_TO with confidence score ≥ 0.65.'
  },
  {
    title: 'News Routing & Correlation',
    description: 'DIRECTLY_IMPACTS, SHOCKS, CORRELATED_WITH multi-hop causal paths.'
  },
  {
    title: 'Guidance RAG with vecf32',
    description: 'Vector similarity embeddings on concall guidance with bi-temporal validity bounds.'
  }
];

export const TIMESCALEDB_FEATURES: DualStoreFeature[] = [
  {
    title: '2 Daily Checkpoints',
    description: 'OPEN (~9:30 AM IST) for opening price and CLOSE (~7:00 PM Bhavcopy) for deliveries.'
  },
  {
    title: 'Official Bhavcopy Delivery',
    description: 'Primary exchange source of truth for volume delivery % and institutional turnover.'
  },
  {
    title: 'SQL-Only Quant Anomalies',
    description: '20-day delivery z-scores (abs(z) >= 1.8) and PE ratio percentiles computed directly in SQL.'
  },
  {
    title: 'Immutable Provenance Staging',
    description: 'Raw payloads stored in vendor_quotes_raw with vintage timestamps before normalization.'
  }
];

export const SAMPLE_SQL_ROWS = [
  {
    trade_date: '2026-10-23',
    session_type: 'CLOSE',
    ticker: 'TATASTEEL',
    close_price: 154.20,
    delivery_pct: 68.4,
    delivery_20d_zscore: 2.14,
    pe_ratio: 14.8,
    vendor_id: 'NSE_BHAVCOPY',
    vendor_as_of: '2026-10-23T19:00:00Z'
  },
  {
    trade_date: '2026-10-23',
    session_type: 'OPEN',
    ticker: 'TATASTEEL',
    close_price: 151.80,
    delivery_pct: 0.0,
    delivery_20d_zscore: 0.0,
    pe_ratio: 14.5,
    vendor_id: 'UPSTOX_FEED',
    vendor_as_of: '2026-10-23T09:30:00Z'
  },
  {
    trade_date: '2026-10-22',
    session_type: 'CLOSE',
    ticker: 'RELIANCE',
    close_price: 2780.50,
    delivery_pct: 54.2,
    delivery_20d_zscore: 1.89,
    pe_ratio: 24.1,
    vendor_id: 'NSE_BHAVCOPY',
    vendor_as_of: '2026-10-22T19:00:00Z'
  },
  {
    trade_date: '2026-10-22',
    session_type: 'CLOSE',
    ticker: 'HDFCBANK',
    close_price: 1720.10,
    delivery_pct: 62.7,
    delivery_20d_zscore: -0.42,
    pe_ratio: 19.3,
    vendor_id: 'NSE_BHAVCOPY',
    vendor_as_of: '2026-10-22T19:00:00Z'
  }
];

