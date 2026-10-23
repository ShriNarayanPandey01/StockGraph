export type ApiSnippetKey = 'curl' | 'mcp' | 'python' | 'response';

export interface ApiSnippet {
  id: ApiSnippetKey;
  label: string;
  title: string;
  code: string;
}

export interface MetricRow {
  trade_date: string;
  session_type: 'OPEN' | 'CLOSE';
  ticker: string;
  close_price: number;
  delivery_pct: number;
  delivery_20d_zscore: number;
  pe_ratio: number;
  vendor_id: string;
  vendor_as_of: string;
}

