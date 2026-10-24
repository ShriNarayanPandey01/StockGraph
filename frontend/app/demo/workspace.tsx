"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type FormEvent, type SetStateAction } from "react";
import "./workspace.css";

type Principal = { id: string; name: string; professional_verified: boolean };
type Stock = {
  exchange: "NSE" | "BSE";
  instrument_key: string;
  trading_symbol: string;
  isin: string;
  name: string;
  short_name?: string | null;
  source_as_of: string;
  registered: boolean;
};
type Node = { id: string; kind: string; properties: Record<string, unknown> };
type Edge = {
  id: string; source: string; target: string; relation: string;
  confidence?: number | null; rationale?: string | null;
  provenance?: Record<string, unknown>; properties?: Record<string, unknown>;
};
type News = Record<string, unknown> & { id?: string; headline?: string; event_ts?: number; event_date?: string };
type Context = {
  ticker: string; window: "LAST_6M" | "LAST_1Y"; processing_status: string; nodes: Node[]; edges: Edge[];
  direct_news: News[]; indirect_news: News[]; professional_evidence: Record<string, unknown>[];
  pagination: { next_offset: number | null; as_of_ts: number; has_more?: Record<string, boolean> };
};
type Candle = { trade_date: string; open: number; high: number; low: number; close: number; volume: number; vendor_id: string; vendor_as_of: string };
type Shareholding = { vendor_id: string; vendor_as_of: string; periods: { period: string; promoters?: number | null; fii?: number | null; dii?: number | null; public?: number | null }[] };
type Watchlist = { id: string; name: string; tickers: string[] };
type Alert = { id: string; ticker: string; direction: string; summary: string; evidence: unknown[]; created_at: string; seen_at?: string | null };
type Monitor = { id: string; watchlist_id: string; question: string; interval_seconds: number; active: boolean; next_run_at: string };
type AgentCitation = { kind: string; id: string; locator?: string | null; quote: string };
type Job = { id: string; state: string; result?: { answer?: string; status?: string; evidence?: AgentCitation[] }; error?: string | null };
type Message = { role: string; content: string; evidence?: unknown[]; created_at?: string };
type Contribution = { id: string; revision: number; status: string; author_id?: string; author_name?: string; ticker?: string; content?: Record<string, unknown> };
type ContributionVersion = { id: string; ticker: string; version_number: number; content: Record<string, unknown>; known_at?: string };
type ContributionDetail = Contribution & { versions?: ContributionVersion[] };
type RegistrationJob = { id: string; stock: Stock };
type Panel = "watchlist" | "calendar" | "research" | "discovery" | "alerts" | "professionals" | null;

const money = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
const dateLabel = (value: unknown) => {
  if (value === null || value === undefined || value === "") return "Not provided";
  const date = new Date(typeof value === "number" && value < 1e12 ? value * 1000 : String(value));
  return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
};
const text = (value: unknown, fallback = "Not provided") => typeof value === "string" && value.trim() ? value : fallback;
const sourceUrl = (node?: Node | null) => {
  if (!node) return "";
  const p = node.properties;
  const evidence = Array.isArray(p.evidence) ? p.evidence[0] as Record<string, unknown> | undefined : undefined;
  const citation = p.citation as Record<string, unknown> | undefined;
  const candidate = p.source_url ?? p.url ?? citation?.url ?? evidence?.url;
  if (typeof candidate !== "string") return "";
  try { const url = new URL(candidate); return ["http:", "https:"].includes(url.protocol) ? url.href : ""; } catch { return ""; }
};

async function api<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  if (!token) throw new Error("Connect with your Platform token first.");
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers, cache: "no-store" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  return body as T;
}

function initialContributionForm() {
  const now = new Date();
  const expiry = new Date(now.getTime() + 30 * 86400000);
  const localTime = (value: Date) => new Date(value.getTime() - value.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  return { title: "", body: "", direction: "NEUTRAL", horizon: "30 days", event_at: localTime(now), expires_at: localTime(expiry), disclosures: "", url: "", evidence_title: "", locator: "" };
}

export default function Explorer() {
  const [tokenDraft, setTokenDraft] = useState("");
  const [token, setToken] = useState("");
  const [user, setUser] = useState<Principal | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState("explore");
  const [panel, setPanel] = useState<Panel>(null);
  const [search, setSearch] = useState("");
  const [stockResults, setStockResults] = useState<Stock[]>([]);
  const [stockCursor, setStockCursor] = useState<string | null>(null);
  const [loadingStocks, setLoadingStocks] = useState(false);
  const stockSearchRequest = useRef(0);
  const [selected, setSelected] = useState<Stock | null>(null);
  const [windowRange, setWindowRange] = useState<"LAST_6M" | "LAST_1Y">("LAST_6M");
  const [profile, setProfile] = useState<Record<string, unknown> | null>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [shareholding, setShareholding] = useState<Shareholding | null>(null);
  const [context, setContext] = useState<Context | null>(null);
  const [selectedNode, setSelectedNode] = useState<string>("");
  const [selectedEdgeId, setSelectedEdgeId] = useState("");
  const [filter, setFilter] = useState("all");
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [watchlistName, setWatchlistName] = useState("My watchlist");
  const [question, setQuestion] = useState("");
  const [agentStatus, setAgentStatus] = useState("");
  const [agentAnswer, setAgentAnswer] = useState("");
  const [agentEvidence, setAgentEvidence] = useState<AgentCitation[]>([]);
  const [currentJobId, setCurrentJobId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState("");
  const [contributions, setContributions] = useState<Contribution[]>([]);
  const [published, setPublished] = useState<Record<string, unknown>[]>([]);
  const [reviewQueue, setReviewQueue] = useState<Contribution[]>([]);
  const [draftId, setDraftId] = useState("");
  const [draftRevision, setDraftRevision] = useState(0);
  const [draftStatus, setDraftStatus] = useState("");
  const [draftTicker, setDraftTicker] = useState("");
  const [draftVersions, setDraftVersions] = useState<ContributionVersion[]>([]);
  const [registrationJob, setRegistrationJob] = useState<RegistrationJob | null>(null);
  const [contribution, setContribution] = useState(initialContributionForm);

  const activeList = watchlists[0] ?? null;
  const graphNodes = context?.nodes ?? [];
  const stockNode = graphNodes.find((node) => node.kind === "Stock") ?? null;
  const surrounding = graphNodes.filter((node) => node.id !== stockNode?.id);
  const visibleNodes = useMemo(() => surrounding.filter((node) => {
    if (filter === "all") return true;
    if (filter === "stock") return node.kind === "Stock";
    if (filter === "sector") return ["Sector", "Commodity", "MacroFactor"].includes(node.kind);
    return ["NewsEvent", "ProfessionalEvidence", "QuarterlySnapshot", "GuidanceChunk"].includes(node.kind);
  }).slice(0, 11), [surrounding, filter]);
  const nodePositions = useMemo(() => {
    const positions = new Map<string, { x: number; y: number }>();
    if (stockNode) positions.set(stockNode.id, { x: 50, y: 49 });
    visibleNodes.forEach((node, index) => {
      const angle = (-Math.PI / 2) + (2 * Math.PI * index / Math.max(visibleNodes.length, 1));
      positions.set(node.id, { x: 50 + Math.cos(angle) * 35, y: 50 + Math.sin(angle) * 33 });
    });
    return positions;
  }, [visibleNodes, stockNode]);
  const activeNode = graphNodes.find((node) => node.id === selectedNode) ?? stockNode;
  const relatedEdges = context?.edges.filter((edge) => edge.source === activeNode?.id || edge.target === activeNode?.id) ?? [];
  const selectedEdge = relatedEdges.find((edge) => edge.id === selectedEdgeId) ?? relatedEdges[0] ?? null;
  const selectedEdgeSourceUrl = selectedEdge
    ? sourceUrl({ id: selectedEdge.id, kind: "Relationship", properties: { ...selectedEdge.provenance, ...selectedEdge.properties } })
    : "";
  const timeline = useMemo(() => [...(context?.direct_news ?? []), ...(context?.indirect_news ?? [])]
    .sort((a, b) => Number(b.event_ts ?? 0) - Number(a.event_ts ?? 0)), [context]);
  const price = candles.length ? candles[candles.length - 1] : null;
  const change = candles.length > 1 ? candles[candles.length - 1].close - candles[candles.length - 2].close : null;

  const loadWatchData = useCallback(async (auth: string) => {
    const [lists, alertFeed, rules] = await Promise.all([
      api<{ items: Watchlist[] }>("/api/v1/watchlists", auth),
      api<{ items: Alert[] }>("/api/v1/alerts?limit=50", auth),
      api<{ items: Monitor[] }>("/api/v1/monitor-rules", auth),
    ]);
    setWatchlists(lists.items);
    setAlerts(alertFeed.items);
    setMonitors(rules.items);
  }, []);

  const searchStocks = useCallback(async (auth: string, query: string) => {
    const request = ++stockSearchRequest.current;
    setLoadingStocks(true);
    try {
      const result = await api<{ items: Stock[]; next_cursor?: string | null }>(`/api/v1/market/stocks?${new URLSearchParams({ query, limit: "30" })}`, auth);
      if (request !== stockSearchRequest.current) return;
      setStockResults(result.items);
      setStockCursor(result.next_cursor ?? null);
    } catch (reason) {
      if (request === stockSearchRequest.current) setError(reason instanceof Error ? reason.message : "Stock search failed.");
    } finally {
      if (request === stockSearchRequest.current) setLoadingStocks(false);
    }
  }, []);

  const loadMoreStocks = async () => {
    if (!token || !stockCursor) return;
    const request = stockSearchRequest.current;
    const cursor = stockCursor;
    setLoadingStocks(true);
    setError("");
    try {
      const result = await api<{ items: Stock[]; next_cursor?: string | null }>(`/api/v1/market/stocks?${new URLSearchParams({ query: search, limit: "30", cursor })}`, token);
      if (request !== stockSearchRequest.current) return;
      setStockResults((rows) => [...new Map([...rows, ...result.items].map((stock) => [`${stock.exchange}:${stock.trading_symbol}`, stock])).values()]);
      setStockCursor(result.next_cursor ?? null);
    } catch (reason) { if (request === stockSearchRequest.current) setError(reason instanceof Error ? reason.message : "Could not load more stocks."); }
    finally { if (request === stockSearchRequest.current) setLoadingStocks(false); }
  };

  const loadContext = useCallback(async (auth: string, stock: Stock, window: "LAST_6M" | "LAST_1Y" = windowRange) => {
    const params = new URLSearchParams({ window, offset: "0", limit: "50" });
    const value = await api<Context>(`/api/v1/stocks/${encodeURIComponent(stock.trading_symbol)}/connections?${params}`, auth);
    setContext(value);
    setSelectedNode("");
    setSelectedEdgeId("");
  }, [windowRange]);

  const loadStock = useCallback(async (stock: Stock, auth = token) => {
    setSelected(stock);
    setProfile(null);
    setCandles([]);
    setShareholding(null);
    setContext(null);
    setSelectedNode("");
    setSelectedEdgeId("");
    setPublished([]);
    setError("");
    setNotice("");
    setBusy(true);
    const today = new Date();
    const start = new Date(today.getTime() - 365 * 86400000).toISOString().slice(0, 10);
    const end = new Date(today.getTime() - 86400000).toISOString().slice(0, 10);
    const marketPath = `/api/v1/market/stocks/${encodeURIComponent(stock.trading_symbol)}`;
    const tasks: Promise<void>[] = [
      api<Record<string, unknown>>(`${marketPath}?exchange=${stock.exchange}`, auth).then(setProfile).catch((reason) => setError(reason instanceof Error ? reason.message : "Company profile unavailable.")),
      api<{ candles: Candle[] }>(`${marketPath}/candles?exchange=${stock.exchange}&from=${start}&to=${end}`, auth).then((result) => setCandles(result.candles)).catch(() => setCandles([])),
      api<Shareholding>(`${marketPath}/shareholding?exchange=${stock.exchange}`, auth).then(setShareholding).catch(() => setShareholding(null)),
    ];
    if (stock.registered) tasks.push(loadContext(auth, stock).catch((reason) => setError(reason instanceof Error ? reason.message : "Graph context unavailable.")));
    await Promise.all(tasks);
    setBusy(false);
  }, [loadContext, token]);

  useEffect(() => {
    if (!token) return;
    const timer = window.setTimeout(() => void searchStocks(token, search), search ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [search, token, searchStocks]);

  useEffect(() => {
    if (!token) return;
    void loadWatchData(token).catch((reason) => setError(reason instanceof Error ? reason.message : "Workspace data unavailable."));
  }, [token, loadWatchData]);

  const connect = async (event: FormEvent) => {
    event.preventDefault();
    const candidate = tokenDraft.trim();
    if (!candidate) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api<{ user: Principal; access: unknown }>("/api/v1/me", candidate);
      setToken(candidate); setUser(result.user); setTokenDraft("");
      const initial = await api<{ items: Stock[]; next_cursor?: string | null }>("/api/v1/market/stocks?limit=30", candidate);
      setStockResults(initial.items);
      setStockCursor(initial.next_cursor ?? null);
      setNotice(`Connected as ${result.user.name}. All implemented Phase 1 features are enabled.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not connect to the Platform API.");
    } finally { setBusy(false); }
  };

  const disconnect = () => {
    setToken(""); setUser(null); setSelected(null); setProfile(null); setCandles([]); setContext(null);
    setWatchlists([]); setAlerts([]); setMonitors([]); setContributions([]); setPublished([]); setReviewQueue([]);
    setMessages([]); setConversationId(""); setCurrentJobId(""); setAgentAnswer(""); setAgentEvidence([]);
    setRegistrationJob(null); setPanel(null); setNotice("Disconnected. Your token was cleared from this page.");
  };

  const loadMore = async () => {
    if (!selected || !context?.pagination.next_offset) return;
    setBusy(true); setError("");
    try {
      const params = new URLSearchParams({ window: context.window, offset: String(context.pagination.next_offset), limit: "50", as_of_ts: String(context.pagination.as_of_ts) });
      const next = await api<Context>(`/api/v1/stocks/${encodeURIComponent(selected.trading_symbol)}/connections?${params}`, token);
      setContext((previous) => previous ? {
        ...next,
        nodes: [...new Map([...previous.nodes, ...next.nodes].map((node) => [node.id, node])).values()],
        edges: [...new Map([...previous.edges, ...next.edges].map((edge) => [edge.id, edge])).values()],
        direct_news: [...new Map([...previous.direct_news, ...next.direct_news].map((item) => [String(item.id), item])).values()],
        indirect_news: [...new Map([...previous.indirect_news, ...next.indirect_news].map((item) => [String(item.id), item])).values()],
        professional_evidence: [...previous.professional_evidence, ...next.professional_evidence],
      } : next);
      setNotice("Loaded the next graph page using the same snapshot timestamp.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load the next page."); }
    finally { setBusy(false); }
  };

  const chooseStock = (stock: Stock) => {
    setSearch(""); setPage("explore"); void loadStock(stock);
  };

  const chooseTicker = async (ticker: string) => {
    const known = stockResults.find((stock) => stock.trading_symbol === ticker);
    if (known) { chooseStock(known); return; }
    try {
      const result = await api<{ items: Stock[] }>(`/api/v1/market/stocks?${new URLSearchParams({ query: ticker, limit: "10" })}`, token);
      const match = result.items.find((stock) => stock.trading_symbol === ticker);
      if (match) chooseStock(match);
      else setError(`Could not resolve ${ticker} in the stock catalog.`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Stock lookup failed."); }
  };

  const ensureWatchlist = async () => {
    if (activeList) return activeList;
    const created = await api<Watchlist>("/api/v1/watchlists", token, { method: "POST", body: JSON.stringify({ name: watchlistName, tickers: selected ? [selected.trading_symbol] : [] }) });
    const updated = [...watchlists, created]; setWatchlists(updated); return created;
  };

  const addSelectedToWatchlist = async () => {
    if (!selected?.registered || !token) return;
    try {
      const list = await ensureWatchlist();
      const tickers = [...new Set([...list.tickers, selected.trading_symbol])];
      const updated = await api<Watchlist>(`/api/v1/watchlists/${list.id}`, token, { method: "PUT", body: JSON.stringify({ name: list.name, tickers }) });
      setWatchlists((all) => all.map((row) => row.id === updated.id ? updated : row));
      setNotice(`${selected.trading_symbol} added to ${updated.name}.`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not update watchlist."); }
  };

  const removeFromWatchlist = async (list: Watchlist, ticker: string) => {
    try {
      const updated = await api<Watchlist>(`/api/v1/watchlists/${list.id}`, token, { method: "PUT", body: JSON.stringify({ name: list.name, tickers: list.tickers.filter((item) => item !== ticker) }) });
      setWatchlists((all) => all.map((row) => row.id === updated.id ? updated : row));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not update watchlist."); }
  };

  const registerSelected = async () => {
    if (!selected || selected.registered || !token) return;
    setBusy(true); setError(""); setNotice("Submitting stock registration to the Graph and Data services…");
    try {
      const job = await api<{ job_id?: string; status?: string }>("/api/v1/market/stock-registrations", token, {
        method: "POST", body: JSON.stringify({ query: selected.trading_symbol, exchange: selected.exchange, strengths: [], business_exclusions: [] }),
      });
      if (!job.job_id) throw new Error("Registration was accepted without a job identifier. Contact the service operator.");
      setRegistrationJob({ id: job.job_id, stock: selected });
      setNotice(`Registration accepted${job.job_id ? ` · job ${job.job_id}` : ""}. Graph context will appear after processing completes.`);
      if (job.job_id) {
        for (let attempt = 0; attempt < 20; attempt += 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 2000));
          const status = await api<{ data_state?: string; graph_state?: string }>(`/api/v1/market/stock-registrations/${job.job_id}`, token);
          if (status.graph_state === "completed") {
            const registered = { ...selected, registered: true };
            setSelected(registered);
            setStockResults((rows) => rows.map((row) => row.exchange === registered.exchange && row.trading_symbol === registered.trading_symbol ? registered : row));
            setRegistrationJob(null);
            await loadContext(token, registered);
            setNotice("Registration and graph processing completed.");
            return;
          }
          if (status.data_state === "failed" || status.graph_state === "failed") {
            setRegistrationJob(null);
            setError("Stock registration processing failed. Check the service logs before retrying.");
            return;
          }
          setNotice(`Registration processing · data ${status.data_state ?? "pending"} · graph ${status.graph_state ?? "pending"}`);
        }
        if (registrationJob?.id === job.job_id) setNotice(`Registration is still running for ${selected.trading_symbol}. Check its status again here.`);
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Stock registration failed."); }
    finally { setBusy(false); }
  };

  const resumeRegistrationCheck = async () => {
    if (!registrationJob) return;
    setBusy(true); setError("");
    try {
      const status = await api<{ data_state?: string; graph_state?: string }>(`/api/v1/market/stock-registrations/${registrationJob.id}`, token);
      if (status.data_state === "failed" || status.graph_state === "failed") {
        setRegistrationJob(null);
        setError("Stock registration processing failed. You can retry after checking the service logs.");
      } else if (status.graph_state === "completed") {
        const registered = { ...registrationJob.stock, registered: true };
        setStockResults((rows) => rows.map((row) => row.exchange === registered.exchange && row.trading_symbol === registered.trading_symbol ? registered : row));
        if (selected?.exchange === registered.exchange && selected.trading_symbol === registered.trading_symbol) {
          setSelected(registered);
          await loadContext(token, registered);
        }
        setRegistrationJob(null);
        setNotice(`Graph registration completed for ${registered.trading_symbol}.`);
      } else {
        setNotice(`Registration is still running · data ${status.data_state ?? "pending"} · graph ${status.graph_state ?? "pending"}.`);
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Registration status is unavailable. Try again."); }
    finally { setBusy(false); }
  };

  const runResearch = async (kind: "chat" | "discovery") => {
    if (!selected?.registered || !question.trim() || !token) return;
    setBusy(true); setError(""); setAgentAnswer(""); setAgentEvidence([]); setAgentStatus("Submitting job…");
    try {
      let result: Job;
      if (kind === "chat") {
        const conversation = await api<{ id: string }>("/api/v1/conversations", token, { method: "POST", body: JSON.stringify({ title: question.trim().slice(0, 160) }) });
        setConversationId(conversation.id);
        result = await api<Job>(`/api/v1/conversations/${conversation.id}/messages`, token, {
          method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify({ question: question.trim(), tickers: [selected.trading_symbol], window: windowRange }),
        });
      } else {
        result = await api<Job>("/api/v1/discovery/scans", token, {
          method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify({ question: question.trim(), tickers: [selected.trading_symbol], window: windowRange }),
        });
      }
      setCurrentJobId(result.id);
      await pollJob(result.id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not submit research job."); setAgentStatus(""); }
    finally { setBusy(false); }
  };

  const pollJob = async (id: string) => {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const job = await api<Job>(`/api/v1/agent-jobs/${id}`, token);
      setAgentStatus(job.state === "pending" ? "Queued for the external research agent…" : `Agent job ${job.state}.`);
      if (job.state === "completed") {
        setAgentAnswer(job.result?.answer ?? "The job completed without a text answer.");
        setAgentEvidence(job.result?.evidence ?? []);
        setAgentStatus(job.result?.status === "insufficient_evidence" ? "Completed · insufficient evidence" : "Completed · evidence-backed response");
        return;
      }
      if (["failed", "cancelled"].includes(job.state)) { setAgentStatus(`Job ${job.state}${job.error ? `: ${job.error}` : "."}`); return; }
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
    setAgentStatus("Still queued or running. This page can check the job again later.");
  };

  const loadPanelData = async (target: Panel) => {
    setPanel(target); setError(""); setNotice("");
    if (target === "professionals") {
      try {
        const publishedRequest = selected?.registered
          ? api<{ items: Record<string, unknown>[] }>(`/api/v1/stocks/${selected.trading_symbol}/professional-evidence`, token)
          : Promise.resolve({ items: [] as Record<string, unknown>[] });
        const [items, mine, reviews] = await Promise.all([
          publishedRequest,
          api<{ items: Contribution[] }>("/api/v1/contributions", token),
          api<{ items: Contribution[] }>("/api/v1/review-queue", token),
        ]);
        setPublished(items.items); setContributions(mine.items); setReviewQueue(reviews.items);
        if (selected && !selected.registered) setNotice(`Register ${selected.trading_symbol} in the graph to load its published evidence.`);
        else if (!selected) setNotice("Select a stock to load its published professional evidence.");
      } catch (reason) { setError(reason instanceof Error ? reason.message : "Professional evidence is unavailable."); }
    }
    if (target === "research" && conversationId) {
      try { const result = await api<{ items: Message[] }>(`/api/v1/conversations/${conversationId}/messages`, token); setMessages(result.items); }
      catch { /* A new conversation has no messages yet. */ }
    }
  };

  const saveDraft = async (event: FormEvent) => {
    event.preventDefault();
    if (!token || (!draftId && !selected?.registered)) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const payload = { ticker: draftTicker || selected?.trading_symbol, title: contribution.title, body: contribution.body,
        direction: contribution.direction, horizon: contribution.horizon, event_at: new Date(contribution.event_at).toISOString(),
        expires_at: new Date(contribution.expires_at).toISOString(), disclosures: contribution.disclosures,
        evidence: [{ url: contribution.url, title: contribution.evidence_title, locator: contribution.locator }] };
      if (!payload.ticker) throw new Error("Choose a registered stock before saving professional research.");
      const saved = draftId
        ? await api<ContributionDetail>(`/api/v1/contributions/${draftId}/versions`, token, { method: "POST", body: JSON.stringify({ ...payload, expected_revision: draftRevision }) })
        : await api<ContributionDetail>("/api/v1/contributions", token, { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify(payload) });
      setDraftId(saved.id); setDraftRevision(saved.revision); setDraftStatus(saved.status); setDraftTicker(payload.ticker); setDraftVersions(saved.versions ?? []);
      setNotice(draftId ? "A new private version was saved." : "Professional research saved as a private draft.");
      setContributions((items) => [saved, ...items.filter((item) => item.id !== saved.id)]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Draft could not be saved."); }
    finally { setBusy(false); }
  };

  const submitDraft = async () => {
    if (!draftId || !draftRevision || draftStatus !== "DRAFT") return;
    try {
      const result = await api<ContributionDetail>(`/api/v1/contributions/${draftId}/submit`, token, { method: "POST", body: JSON.stringify({ expected_revision: draftRevision }) });
      setDraftRevision(result.revision); setDraftStatus(result.status); setDraftVersions(result.versions ?? draftVersions); setNotice("Submitted for independent review. The author cannot approve their own research.");
      setContributions((items) => items.map((item) => item.id === result.id ? result : item));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Submission failed."); }
  };

  const editContribution = async (item: Contribution) => {
    try {
      const detail = await api<ContributionDetail>(`/api/v1/contributions/${item.id}`, token);
      const version = detail.versions?.at(-1);
      if (!version) throw new Error("This submission has no editable version.");
      const content = version.content;
      const evidence = Array.isArray(content.evidence) ? content.evidence[0] as Record<string, unknown> | undefined : undefined;
      const localInput = (value: unknown) => {
        const date = new Date(String(value ?? ""));
        return Number.isNaN(date.valueOf()) ? "" : new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      };
      setDraftId(detail.id); setDraftRevision(detail.revision); setDraftStatus(detail.status); setDraftTicker(version.ticker); setDraftVersions(detail.versions ?? []);
      setContribution({ title: String(content.title ?? ""), body: String(content.body ?? ""), direction: String(content.direction ?? "NEUTRAL"), horizon: String(content.horizon ?? ""), event_at: localInput(content.event_at), expires_at: localInput(content.expires_at), disclosures: String(content.disclosures ?? ""), url: String(evidence?.url ?? ""), evidence_title: String(evidence?.title ?? ""), locator: String(evidence?.locator ?? "") });
      setNotice(`Editing ${version.ticker} as a new version. Published versions remain in the history.`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load this submission."); }
  };

  const startNewDraft = () => {
    setDraftId(""); setDraftRevision(0); setDraftStatus(""); setDraftTicker(selected?.trading_symbol ?? ""); setDraftVersions([]); setContribution(initialContributionForm());
  };

  const retractContribution = async (item: Record<string, unknown>) => {
    const id = typeof item.id === "string" ? item.id : "";
    const revision = typeof item.revision === "number" ? item.revision : 0;
    if (!id || !revision) return;
    try {
      await api(`/api/v1/contributions/${id}/retract`, token, { method: "POST", body: JSON.stringify({ expected_revision: revision, reason: "Author retracted this professional evidence." }) });
      setPublished((items) => items.filter((publishedItem) => publishedItem.id !== id));
      setContributions((items) => items.map((contributionItem) => contributionItem.id === id ? { ...contributionItem, status: "RETRACTED", revision: revision + 1 } : contributionItem));
      setNotice("Professional evidence was retracted and removed from the active view.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Retraction failed."); }
  };

  const reviewContribution = async (item: Contribution, decision: "APPROVE" | "REJECT") => {
    try {
      await api(`/api/v1/contributions/${item.id}/review`, token, { method: "POST", body: JSON.stringify({ expected_revision: item.revision, decision, reason: decision === "APPROVE" ? "Evidence reviewed." : "Please add clearer supporting evidence." }) });
      setReviewQueue((rows) => rows.filter((row) => row.id !== item.id));
      setNotice(`Evidence ${decision.toLowerCase()}d.`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Review failed."); }
  };

  const createMonitor = async () => {
    if (!selected?.registered || !token) return;
    try {
      let list = await ensureWatchlist();
      if (!list.tickers.includes(selected.trading_symbol)) {
        list = await api<Watchlist>(`/api/v1/watchlists/${list.id}`, token, { method: "PUT", body: JSON.stringify({ name: list.name, tickers: [...list.tickers, selected.trading_symbol] }) });
        setWatchlists((rows) => rows.map((row) => row.id === list.id ? list : row));
      }
      const monitor = await api<Monitor>("/api/v1/monitor-rules", token, { method: "POST", body: JSON.stringify({ watchlist_id: list.id, question: question.trim() || `Find evidence-backed opportunities related to ${selected.trading_symbol}.`, interval_seconds: 3600 }) });
      setMonitors((items) => [monitor, ...items]); setNotice("Opportunity monitor created. The external agent evaluates scheduled jobs.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not create monitor."); }
  };

  const stopMonitor = async (id: string) => {
    try { await api(`/api/v1/monitor-rules/${id}`, token, { method: "DELETE" }); setMonitors((rows) => rows.filter((row) => row.id !== id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not stop monitor."); }
  };

  const acknowledgeAlert = async (id: string) => {
    try {
      await api(`/api/v1/alerts/${id}/acknowledge`, token, { method: "POST" });
      setAlerts((rows) => rows.map((row) => row.id === id ? { ...row, seen_at: new Date().toISOString() } : row));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not acknowledge alert."); }
  };

  const navTo = (target: string) => {
    setPage(target);
    if (target === "explore") setPanel(null);
    else void loadPanelData(target as Panel);
  };

  return (
    <>
      <link rel="stylesheet" href="/reference/demo/explore.css" />
      <div id="track-wireframe">
        <a className="skip" href="#explore-main">Skip to workspace</a>
        <header className="top">
          <a className="logo" href="/">TRACK<span>.</span></a>
          <span className="brand-caption mono">STOCKS / CONTEXT / CONNECTIONS</span>
          <nav className="nav" aria-label="Primary">
            {[['explore','01','Explore'],['watchlist','02','Watchlist'],['calendar','03','Calendar'],['research','04','Research'],['professionals','05','Evidence']].map(([key, number, label]) => <button key={key} type="button" className={page === key ? "on" : ""} onClick={() => navTo(key)}><span>{number}</span>{label}</button>)}
          </nav>
          <div className="top-utilities"><span className="demo">PHASE 1 · FREE</span><button className="theme-toggle" type="button" aria-label="Switch theme" onClick={() => document.documentElement.classList.toggle("dark")}>◐</button><a className="overview-link" href="/">Overview ↗</a></div>
          <div className="ruler" aria-hidden="true" />
        </header>
        <div className="auth-strip">
          {user ? <><span className="auth-state"><i /> Connected as <strong>{user.name}</strong>{user.professional_verified ? " · verified professional" : ""}</span><button type="button" className="text-button" onClick={disconnect}>Disconnect</button></> : <form onSubmit={connect} className="auth-form"><label htmlFor="platform-token">Platform access token</label><input id="platform-token" type="password" autoComplete="off" value={tokenDraft} onChange={(event) => setTokenDraft(event.target.value)} placeholder="Paste an operator-issued token"/><button type="submit" disabled={busy || !tokenDraft}>Connect</button><span>Token remains in page memory only</span></form>}
        </div>
        <div className="layout">
          <aside className="sidebar">
            <div className="eyebrow">WORKSPACE</div>
            <div className="side-nav">
              <button className={page === "explore" ? "on" : ""} onClick={() => navTo("explore")}>◉ &nbsp; Knowledge graph</button>
              <button className={page === "calendar" ? "on" : ""} onClick={() => navTo("calendar")}>▦ &nbsp; Event calendar</button>
              <button className={page === "alerts" ? "on" : ""} onClick={() => void loadPanelData("alerts")}>◇ &nbsp; Opportunity alerts <span className="count">{alerts.filter((alert) => !alert.seen_at).length || ""}</span></button>
              <button onClick={() => void loadPanelData("research")}>⌕ &nbsp; Research chat</button>
              <button onClick={() => void loadPanelData("discovery")}>⌖ &nbsp; Discovery scan</button>
              <button onClick={() => void loadPanelData("professionals")}>✳ &nbsp; Professional insights</button>
            </div>
            <div className="eyebrow">YOUR WATCHLIST</div>
            <div className="watchlist">
              {activeList?.tickers?.length ? activeList.tickers.map((ticker) => {
                const match = stockResults.find((row) => row.trading_symbol === ticker);
                return <div className="watch-item" key={ticker}><button type="button" className={`watch ${selected?.trading_symbol === ticker ? "on" : ""}`} onClick={() => void chooseTicker(ticker)} disabled={busy}><span><strong>{ticker}</strong><small>{match?.name ?? activeList.name}</small></span><span className="watch-arrow">↗</span></button><button type="button" className="watch-remove" aria-label={`Remove ${ticker} from watchlist`} onClick={() => void removeFromWatchlist(activeList, ticker)}>×</button></div>;
              }) : <p className="empty-note">No saved stocks yet. Select a stock and add it here.</p>}
            </div>
            <button type="button" className="small-outline" onClick={() => void addSelectedToWatchlist()} disabled={!selected?.registered || !user || busy}>+ Add selected stock</button>
            <div className="side-note"><strong>All Phase 1 features are free.</strong><br/>Research context is evidence, not a price prediction.</div>
          </aside>
          <main className="main" id="explore-main">
            <div className="intro">
              <div><div className="eyebrow">[01] EXPLORE THE MARKET / INDIA</div><h1>Every move has context<span className="accent-dot">.</span></h1></div>
              <label className="stock-search"><span className="sr">Search exchange stocks</span><input className="search" value={search} onChange={(event) => { stockSearchRequest.current += 1; setSearch(event.target.value); }} placeholder="Search stocks…" aria-label="Search registered stocks"/><span className="search-hint">NSE / BSE · Search the live catalog</span>
                {token && search && <div className="search-results">{stockResults.length ? stockResults.slice(0, 8).map((stock) => <button key={`${stock.exchange}:${stock.trading_symbol}`} onClick={() => chooseStock(stock)} type="button" disabled={busy}><strong>{stock.trading_symbol}</strong><span>{stock.name} · {stock.exchange}{stock.registered ? " · Graph ready" : " · Register graph"}</span></button>) : <span className="empty-note">No matching stocks.</span>}{stockCursor && <button type="button" onClick={() => void loadMoreStocks()} disabled={loadingStocks}>{loadingStocks ? "Loading stocks?" : "Load more stocks"}</button>}</div>}
              </label>
            </div>
            {selected ? <div className="headline"><div className="stock-name">{text(profile?.name, selected.name)}<small id="track-market">{selected.trading_symbol} · {selected.exchange} · {selected.registered ? "Graph registered" : "Not in graph yet"}</small></div><div className="price">{price ? money.format(price.close) : "—"}<small>{price ? `Daily close · ${price.vendor_id} · ${dateLabel(price.vendor_as_of)}` : "No completed daily candle available"}</small></div></div> : <div className="headline"><div className="stock-name">Select a stock<small>Search the live NSE/BSE catalog to begin.</small></div><div className="price">—<small>Market data appears with its source and timestamp</small></div></div>}
            {selected && <div className="stock-actions"><span>{profile ? text((profile.profile as Record<string, unknown> | undefined)?.sector, "Sector unavailable") : "Loading company data…"}{change !== null && <b className={change >= 0 ? "positive" : "negative"}> {change >= 0 ? "+" : ""}{money.format(change)} vs prior daily candle</b>}</span>{selected.registered ? <button className="small-outline" onClick={() => void addSelectedToWatchlist()}>+ Watchlist</button> : <button className="small-outline" disabled={busy || !token} onClick={() => void registerSelected()}>Register in graph</button>}</div>}
            {!token && <div className="notice">Connect an operator-issued Platform token to use the live workspace. See the setup instructions in the frontend README.</div>}
            {registrationJob && <div className="notice" role="status">Registration for {registrationJob.stock.trading_symbol} is in progress. <button type="button" className="text-button" disabled={busy} onClick={() => void resumeRegistrationCheck()}>Check registration status</button></div>}
            {notice && <div className="notice" role="status">{notice}</div>}{error && <div className="error" role="alert">{error}</div>}
            <div className="workspace">
              <section className="canvas" aria-label="Live stock relationship graph">
                <div className="canvas-top"><strong><span className="figure-index">FIG. 01</span> Knowledge graph</strong><div className="graph-controls"><label className="window-control">Window<select value={windowRange} onChange={(event) => { const next = event.target.value as "LAST_6M" | "LAST_1Y"; setWindowRange(next); if (selected?.registered) { setContext(null); setBusy(true); void loadContext(token, selected, next).catch((reason) => setError(reason instanceof Error ? reason.message : "Graph context unavailable.")).finally(() => setBusy(false)); } }}><option value="LAST_6M">Last 6 months</option><option value="LAST_1Y">Last 1 year</option></select></label><div className="chips" aria-label="Relationship filters">{[["all","All"],["event","Events"],["sector","Drivers"],["stock","Stocks"]].map(([key,label]) => <button key={key} type="button" className={filter === key ? "on" : ""} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>)}</div></div></div>
                <div className="graph">
                  {stockNode && <svg className="edges" aria-hidden="true" preserveAspectRatio="none" viewBox="0 0 100 100">{context?.edges.map((edge) => { const a = nodePositions.get(edge.source); const b = nodePositions.get(edge.target); if (!a || !b) return null; return <line key={edge.id} className={`edge ${edge.id === selectedEdge?.id ? "active" : ""}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />; })}</svg>}
                  {stockNode && <button type="button" className={`node core ${selectedNode === stockNode.id ? "active" : ""}`} style={{ left: "50%", top: "49%" }} onClick={() => { setSelectedNode(stockNode.id); setSelectedEdgeId(""); }}><small>SELECTED STOCK</small><strong>{selected?.trading_symbol}</strong><span>{relatedEdges.length} visible relationships</span></button>}
                  {visibleNodes.map((node) => { const pos = nodePositions.get(node.id); if (!pos) return null; const label = node.properties.name ?? node.properties.headline ?? node.properties.title ?? node.properties.ticker ?? node.id.split(":").at(-1); return <button key={node.id} type="button" className={`node ${selectedNode === node.id ? "active" : ""}`} data-group={node.kind} style={{ left: `${pos.x}%`, top: `${pos.y}%` }} onClick={() => { setSelectedNode(node.id); setSelectedEdgeId(""); }}><small>{node.kind.replace(/([a-z])([A-Z])/g, "$1 $2").toUpperCase()}</small><strong>{text(label, node.id)}</strong></button>; })}
                  {!token && <div className="graph-message">Connect to load live stock connections.</div>}
                  {token && busy && !graphNodes.length && <div className="graph-message">Loading graph and market data…</div>}
                  {token && selected && !busy && !context && selected.registered && <div className="graph-message">Graph context is processing or not available yet.</div>}
                  {token && selected && !selected.registered && <div className="graph-message">This stock has not been added to the knowledge graph yet.</div>}
                  {token && selected && context && !surrounding.length && <div className="graph-message">No connections in this research window.</div>}
                </div>
                <div className="graph-legend"><span><i className="dash"/>Graph relationship</span><span><i className="dash dotted"/>Context evidence</span><span>{context?.processing_status ?? "Waiting for a stock"}{context?.pagination.next_offset !== null && context && <button type="button" className="inline-action" disabled={busy} onClick={() => void loadMore()}> · Load next page ↗</button>}</span></div>
              </section>
              <aside className="evidence" aria-live="polite"><div className="head"><div className="eyebrow">CONNECTION EVIDENCE</div><h2>{activeNode ? text(activeNode.properties.headline ?? activeNode.properties.title ?? activeNode.properties.name, activeNode.kind) : "Select a connection"}</h2><span className="type">{activeNode?.kind ?? "Evidence and relationship details"}{selectedEdge ? ` · ${selectedEdge.relation}` : ""}</span><p>{selectedEdge?.rationale ?? text(activeNode?.properties.summary ?? activeNode?.properties.description, "Choose a graph node to inspect its available evidence, relationship, confidence, and timing.")}</p></div>
                {relatedEdges.length > 0 && <div className="related-edge-list" aria-label="Relationships for selected graph node"><strong>Relationships ({relatedEdges.length})</strong>{relatedEdges.map((edge) => { const otherId = edge.source === activeNode?.id ? edge.target : edge.source; const other = graphNodes.find((node) => node.id === otherId); const label = other?.properties.name ?? other?.properties.headline ?? other?.properties.title ?? otherId; return <button key={edge.id} type="button" className={edge.id === selectedEdge?.id ? "on" : ""} onClick={() => setSelectedEdgeId(edge.id)}><span>{edge.relation}</span><strong>{text(label, otherId)}</strong>{typeof edge.confidence === "number" && <small>{Math.round(edge.confidence * 100)}% confidence</small>}</button>; })}</div>}
                <dl><dt>Relationship</dt><dd>{selectedEdge?.relation ?? "Stock context"}</dd><dt>Confidence</dt><dd>{selectedEdge?.confidence === null || selectedEdge?.confidence === undefined ? "Not provided" : `${Math.round(selectedEdge.confidence * 100)}% · model or source estimate`}</dd><dt>Event time</dt><dd>{dateLabel(selectedEdge?.properties?.event_ts ?? selectedEdge?.properties?.valid_from_ts ?? activeNode?.properties.event_ts ?? activeNode?.properties.event_date ?? activeNode?.properties.valid_from_ts)}</dd><dt>Source</dt><dd>{text(selectedEdge?.provenance?.source ?? activeNode?.properties.source ?? activeNode?.properties.publisher)}</dd></dl>
                {(selectedEdgeSourceUrl || sourceUrl(activeNode)) ? <a className="action" href={selectedEdgeSourceUrl || sourceUrl(activeNode)} target="_blank" rel="noreferrer">Open source ↗</a> : <span className="small-label">No source URL was supplied with this record.</span>}
                {price && <div className="chart-detail"><div className="rule"/><div className="eyebrow">DAILY CANDLES / {price.vendor_id}</div><Sparkline candles={candles}/><div className="small-label">{candles.length} completed sessions · source timestamp {dateLabel(price.vendor_as_of)}</div></div>}
              </aside>
            </div>
            <section className="timeline"><div className="timeline-head"><strong>Recent connected events</strong><span>{context?.window ?? "Fixed graph window: LAST_6M"} · {timeline.length} source events</span></div><div className="time-events live-events">{timeline.length ? timeline.slice(0, 5).map((event, index) => <button key={`${event.id ?? index}`} type="button" onClick={() => { const node = graphNodes.find((item) => item.id === event.id || item.properties.headline === event.headline); if (node) setSelectedNode(node.id); }}><span>{dateLabel(event.event_date ?? event.event_ts)}<br/><b>{text(event.headline, "Market event")}</b></span></button>) : <p className="empty-note">No news events were returned for this stock and time window.</p>}</div></section>
            <div className="lower"><section className="feed"><div className="eyebrow">OPPORTUNITY MONITORS</div>{monitors.length ? monitors.map((monitor) => <div className="feed-row" key={monitor.id}><span>{monitor.question} · next check {dateLabel(monitor.next_run_at)}</span><button onClick={() => void stopMonitor(monitor.id)}>Stop</button></div>) : <p className="empty-note">No monitor rules yet. Create one to queue recurring research for the external agent.</p>}<button className="action" type="button" onClick={() => void loadPanelData("alerts")}>Manage monitors and alerts ↗</button><div className="rule"/><div className="eyebrow">QUARTERLY SHAREHOLDING</div>{shareholding?.periods?.[0] ? <><p className="holding-period">{shareholding.periods[0].period} · {shareholding.vendor_id} · {dateLabel(shareholding.vendor_as_of)}</p><div className="holding-grid">{[["Promoters",shareholding.periods[0].promoters],["FII",shareholding.periods[0].fii],["DII",shareholding.periods[0].dii],["Public",shareholding.periods[0].public]].map(([label,value]) => <span key={String(label)}><b>{label}</b><strong>{typeof value === "number" ? `${value.toFixed(2)}%` : "—"}</strong></span>)}</div></> : <p className="empty-note">No shareholding snapshot is available for this stock.</p>}</section><button className="film" type="button" onClick={() => void loadPanelData("research")}><span className="eyebrow">RESEARCH / AGENT-ASSISTED</span><strong>⌕ &nbsp; Ask about this stock</strong><small>Responses cite evidence from the connected context.</small></button></div>
            <footer className="bottom">LIVE API DATA · Prices show vendor attribution and as-of time. Graph links show context and do not establish price causation.</footer>
          </main>
        </div>
      </div>
      {panel && <div className="modal" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setPanel(null); }}><section className="modal-box" role="dialog" aria-modal="true" aria-labelledby="panel-title"><button className="close" type="button" aria-label="Close" onClick={() => setPanel(null)}>×</button><div className="eyebrow">TRACK / PHASE 1 · FREE ACCESS</div><PanelContent panel={panel} selected={selected} windowRange={windowRange} user={user} watchlists={watchlists} alerts={alerts} monitors={monitors} timeline={timeline} messages={messages} contributions={contributions} published={published} reviewQueue={reviewQueue} question={question} setQuestion={setQuestion} agentStatus={agentStatus} agentAnswer={agentAnswer} agentEvidence={agentEvidence} currentJobId={currentJobId} onCheckJob={() => currentJobId && void pollJob(currentJobId)} busy={busy} onResearch={() => void runResearch(panel === "discovery" ? "discovery" : "chat")} onCreateMonitor={() => void createMonitor()} onAcknowledge={acknowledgeAlert} onStopMonitor={stopMonitor} onSaveDraft={saveDraft} onEditContribution={editContribution} onRetractContribution={retractContribution} onNewDraft={startNewDraft} draftTicker={draftTicker} draftStatus={draftStatus} draftRevision={draftRevision} draftVersions={draftVersions} contribution={contribution} setContribution={setContribution} draftId={draftId} onSubmitDraft={submitDraft} onReview={reviewContribution} onClose={() => setPanel(null)}/></section></div>}
    </>
  );
}

function Sparkline({ candles }: { candles: Candle[] }) {
  if (candles.length < 2) return <div className="no-chart">Two or more daily candles are required to draw a trend.</div>;
  const values = candles.slice(-60).map((candle) => candle.close);
  const min = Math.min(...values); const max = Math.max(...values); const range = Math.max(max - min, 0.0001);
  const points = values.map((value, index) => `${(index / (values.length - 1)) * 200},${55 - ((value - min) / range) * 50}`).join(" ");
  return <svg className="mini-chart" viewBox="0 0 200 60" role="img" aria-label="Daily closing prices returned by the data service"><polyline points={points} fill="none" stroke="var(--accent)" strokeWidth="2"/></svg>;
}

function PanelContent(props: {
  panel: Panel; selected: Stock | null; windowRange: "LAST_6M" | "LAST_1Y"; user: Principal | null; watchlists: Watchlist[]; alerts: Alert[]; monitors: Monitor[]; timeline: News[]; messages: Message[]; contributions: Contribution[]; published: Record<string, unknown>[]; reviewQueue: Contribution[]; question: string; setQuestion: (value: string) => void; agentStatus: string; agentAnswer: string; agentEvidence: AgentCitation[]; currentJobId: string; onCheckJob: () => void; busy: boolean; onResearch: () => void; onCreateMonitor: () => void; onAcknowledge: (id: string) => void; onStopMonitor: (id: string) => void; onSaveDraft: (event: FormEvent) => void; onEditContribution: (item: Contribution) => void; onRetractContribution: (item: Record<string, unknown>) => void; onNewDraft: () => void; draftTicker: string; draftStatus: string; draftRevision: number; draftVersions: ContributionVersion[]; contribution: ReturnType<typeof initialContributionForm>; setContribution: Dispatch<SetStateAction<ReturnType<typeof initialContributionForm>>>; draftId: string; onSubmitDraft: () => void; onReview: (item: Contribution, decision: "APPROVE" | "REJECT") => void; onClose: () => void;
}) {
  const p = props;
  const title = p.panel === "watchlist" ? "Your watchlists" : p.panel === "calendar" ? "Connected event calendar" : p.panel === "research" ? "Stock research chat" : p.panel === "discovery" ? "Opportunity discovery" : p.panel === "alerts" ? "Opportunity alerts and monitors" : "Professional evidence";
  const update = (key: keyof ReturnType<typeof initialContributionForm>, value: string) => p.setContribution((current) => ({ ...current, [key]: value }));
  return <><h2 id="panel-title">{title}</h2>
    {p.panel === "watchlist" && <>{p.watchlists.map((list) => <div className="panel-card" key={list.id}><strong>{list.name}</strong>{list.tickers.map((ticker) => <span key={ticker}>{ticker}</span>)}</div>)}{!p.watchlists.length && <p>No watchlist saved. Select a stock in Explore and choose “Add selected stock.”</p>}</>}
    {p.panel === "calendar" && <div className="panel-list">{p.timeline.length ? p.timeline.map((event, index) => <article className="panel-card" key={String(event.id ?? index)}><small>{dateLabel(event.event_date ?? event.event_ts)}</small><strong>{text(event.headline, "Market event")}</strong><p>{text(event.summary ?? event.rationale)}</p>{sourceUrl({ id: String(event.id ?? index), kind: "NewsEvent", properties: event }) && <a href={sourceUrl({ id: String(event.id ?? index), kind: "NewsEvent", properties: event })} target="_blank" rel="noreferrer">Source ↗</a>}</article>) : <p>No event records were returned for the selected stock.</p>}</div>}
    {(p.panel === "research" || p.panel === "discovery") && <><p>{p.selected ? `Research scope: ${p.selected.trading_symbol} · ${p.windowRange}` : "Select a stock in Explore before submitting research."} Jobs are delivered to the separately hosted agent.</p><label className="panel-label">Question<textarea value={p.question} onChange={(event) => p.setQuestion(event.target.value)} rows={4} placeholder="Ask a research question grounded in this stock's context…"/></label><button className="action" type="button" disabled={p.busy || !p.selected || !p.question.trim()} onClick={p.onResearch}>{p.panel === "discovery" ? "Run discovery scan" : "Send research question"}</button>{p.agentStatus && <p className="job-state" role="status">{p.agentStatus}</p>}{p.currentJobId && <button className="text-button" type="button" disabled={p.busy} onClick={p.onCheckJob}>Check job status ↻</button>}{p.agentAnswer && <article className="answer"><strong>Agent response</strong><p>{p.agentAnswer}</p><small>Review cited sources and use your own judgment.</small>{p.agentEvidence.length > 0 && <ol className="agent-citations">{p.agentEvidence.map((citation) => <li key={`${citation.kind}:${citation.id}:${citation.locator ?? ""}`}><strong>{citation.kind} · {citation.id}{citation.locator ? ` · ${citation.locator}` : ""}</strong><blockquote>{citation.quote}</blockquote></li>)}</ol>}</article>}{p.messages.map((message, index) => <article className="answer" key={`${message.role}-${index}`}><strong>{message.role}</strong><p>{message.content}</p></article>)}</>}
    {p.panel === "alerts" && <><p>Alerts are created by completed, evidence-checked external-agent jobs. Recurring monitors are user-owned and have no Phase 1 plan quota.</p><h3>Active monitors</h3>{p.monitors.map((monitor) => <div className="panel-card" key={monitor.id}><strong>{monitor.question}</strong><small>Next run: {dateLabel(monitor.next_run_at)}</small><button type="button" className="text-button" onClick={() => p.onStopMonitor(monitor.id)}>Stop monitor</button></div>)}<button type="button" className="action" disabled={!p.selected} onClick={p.onCreateMonitor}>Create hourly opportunity monitor</button><h3>Opportunity alerts</h3>{p.alerts.length ? p.alerts.map((alert) => <article className="panel-card" key={alert.id}><strong>{alert.ticker} · {alert.direction}</strong><p>{alert.summary}</p><small>{dateLabel(alert.created_at)} · {Array.isArray(alert.evidence) ? alert.evidence.length : 0} evidence references</small>{!alert.seen_at && <button className="text-button" onClick={() => p.onAcknowledge(alert.id)}>Mark read</button>}</article>) : <p>No alerts yet. Alerts appear after an agent completes a supported job with validated evidence.</p>}</>}
    {p.panel === "professionals" && <>
      <p>Published professional evidence is visible to all authenticated users. Corrections, expiry, source citations, and conflicting views remain part of the evidence trail.</p>
      {!p.selected?.registered && <p>Select and register a stock to load its graph evidence.</p>}
      <h3>Published for {p.selected?.trading_symbol ?? "selected stock"}</h3>
      {p.published.map((item, index) => {
        const content = item.content as Record<string, unknown> | undefined;
        const itemUrl = sourceUrl({ id: String(item.id ?? index), kind: "ProfessionalEvidence", properties: content ?? {} });
        return <article className="panel-card" key={String(item.version_id ?? index)}>
          <strong>{text(content?.title)}</strong><p>{text(content?.body)}</p>
          <small>{text(item.author_name)} ? {text(content?.direction)} ? valid through {dateLabel(content?.expires_at)} ? weight {typeof item.weight === "number" ? item.weight.toFixed(2) : "not provided"} ? published {dateLabel(item.published_at)}</small>
          {itemUrl && <p><a href={itemUrl} target="_blank" rel="noreferrer">Open cited source</a></p>}
          {item.author_id === p.user?.id && <button className="text-button" type="button" onClick={() => p.onRetractContribution(item)}>Retract this published evidence</button>}
        </article>;
      })}
      {p.selected?.registered && !p.published.length && <p>No published professional evidence for this stock.</p>}
      {p.user?.professional_verified ? <>
        <div className="contribution-toolbar"><div><h3>Professional research draft</h3>{p.draftId && <small>{p.draftTicker} | revision {p.draftRevision} {p.draftStatus ? ` | ${p.draftStatus}` : ""}</small>}</div><button type="button" className="text-button" disabled={!p.selected?.registered} onClick={p.onNewDraft}>New draft</button></div>
        <form className="contribution-form" onSubmit={p.onSaveDraft}>
          <label>Title<input required value={p.contribution.title} onChange={(event) => update("title", event.target.value)}/></label>
          <label>Research<textarea required rows={4} value={p.contribution.body} onChange={(event) => update("body", event.target.value)}/></label>
          <label>Direction<select value={p.contribution.direction} onChange={(event) => update("direction", event.target.value)}><option>BULLISH</option><option>BEARISH</option><option>NEUTRAL</option></select></label>
          <label>Horizon<input required value={p.contribution.horizon} onChange={(event) => update("horizon", event.target.value)}/></label>
          <label>Event time<input required type="datetime-local" value={p.contribution.event_at} onChange={(event) => update("event_at", event.target.value)}/></label>
          <label>Expiry time<input required type="datetime-local" value={p.contribution.expires_at} onChange={(event) => update("expires_at", event.target.value)}/></label>
          <label>Source URL<input type="url" required value={p.contribution.url} onChange={(event) => update("url", event.target.value)}/></label>
          <label>Source title<input required value={p.contribution.evidence_title} onChange={(event) => update("evidence_title", event.target.value)}/></label>
          <label>Locator<input required value={p.contribution.locator} onChange={(event) => update("locator", event.target.value)}/></label>
          <label>Disclosures<input required value={p.contribution.disclosures} onChange={(event) => update("disclosures", event.target.value)}/></label>
          <div className="form-actions"><button className="action" type="submit" disabled={p.busy || (!p.draftId && !p.selected?.registered) || ["SUBMITTED", "RETRACTED"].includes(p.draftStatus)}>{p.draftId ? "Save new version" : "Save private draft"}</button>{p.draftId && p.draftStatus === "DRAFT" && <button className="action secondary" type="button" onClick={p.onSubmitDraft}>Submit for independent review</button>}</div>
        </form>
        {p.draftVersions.length > 0 && <div className="version-history"><h4>Version history</h4>{p.draftVersions.map((version) => <div key={version.id}><strong>Version {version.version_number}</strong><span>{text(version.content.title)} | recorded {dateLabel(version.known_at)}</span></div>)}</div>}
      </> : <p>Professional submission is available to users with verified professional status.</p>}
      <h3>My submissions</h3>
      {p.contributions.map((item) => <div className="panel-card" key={item.id}><strong>{item.status}</strong><small>Revision {item.revision}</small>{!["SUBMITTED", "RETRACTED"].includes(item.status) && <button className="text-button" type="button" onClick={() => p.onEditContribution(item)}>Revise contribution</button>}</div>)}
      <h3>Independent review queue</h3>
      {p.reviewQueue.map((item) => <div className="panel-card" key={item.id}><strong>{text((item.content as Record<string, unknown> | undefined)?.title)}</strong><small>By {text(item.author_name)}</small><button className="text-button" onClick={() => p.onReview(item, "APPROVE")}>Approve</button><button className="text-button" onClick={() => p.onReview(item, "REJECT")}>Request changes</button></div>)}
    </>}
    <div className="modal-footer"><button type="button" className="text-button" onClick={p.onClose}>Close</button></div>
  </>;
}
