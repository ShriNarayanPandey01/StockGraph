# Meta Model and AI Usage

StockGraph's checked-in environment example selects Meta's Muse Spark model
(`meta-models/muse-spark-open-1026`) for chat inference. Meta introduced Muse
Spark as a model from Meta Superintelligence Labs ([Meta's announcement](https://about.fb.com/news/2026/04/introducing-muse-spark-meta-superintelligence-labs/)).
This project sends chat requests through Baseten's OpenAI-compatible inference
endpoint using LiteLLM. The model is Meta's; Baseten is the configured serving
provider.

The example configuration selects this model but keeps `LLM_ENABLED=false`.
Live model calls require enabling inference and providing the configured
provider credentials. Deployments can change the model and provider through
environment settings without changing application code. See
[LLM provider configuration](LLM_PROVIDER_CONFIGURATION.md) for setup details.

## Where the chat model is used

| Workflow | Model setting | What the model contributes |
| --- | --- | --- |
| Dynamic ontology | `LLM_ONTOLOGY_MODEL` | Suggests stock, commodity, macro, sector and peer relationships from a stock context card and the canonical entity catalog. |
| News processing | `LLM_CHAT_MODEL` | Reviews news eligibility when needed, routes eligible stories to directly or indirectly affected entities, and judges links between related news events. |
| Optional agent pilot | `AGENTS_LLM_CHAT_MODEL` or `LLM_CHAT_MODEL` | Produces cited research, recent-event discovery and monitoring results when the separately enabled pilot runs. |

The sample sets both StockGraph model settings to Muse Spark. The optional
agent worker inherits the configured chat model unless its `AGENTS_` setting
overrides it. The agent pilot is disabled by default.

## What happens to model output

The model returns structured JSON against Pydantic schemas. For graph
inference, StockGraph resolves entity IDs against its canonical registry,
checks relationship types and confidence, and applies the configured
confidence threshold before persistence. Prompts include stock context where
the workflow requires it. A failed or invalid response remains retryable and
is not reported as completed inference.

Meta's chat model does not create the numeric market history or make
BUY/SELL/HOLD recommendations. Data providers supply the numeric values;
StockGraph stores relationships and narrative context. No trading engine or
order execution is implemented.

## Embeddings use a separate model path

The sample environment uses OpenAI `text-embedding-3-small` and a separate
`OPENAI_API_KEY` for embeddings. Those vectors support profile and news
similarity searches in FalkorDB; the Muse Spark chat model does not generate
them. Gemini embeddings are also configurable with their own model setting and
credential. Keep the embedding model and vector dimension stable while the
existing index is in use.

## Runtime controls

- `LLM_ENABLED=false` disables external model calls by default.
- `LLM_MAX_TOKENS_PER_CALL` bounds each StockGraph chat prompt.
- `LLM_MONTHLY_USD_CAP` and the configured per-token estimates guard the
  StockGraph model spend ledger. Estimates are operator inputs, not provider
  invoices.
- The optional agent pilot has its own Platform budget reservations and job
  ceilings; enabling it does not bypass those checks.

For the provider keys, JSON modes, model overrides, embedding configuration and
restart steps, see [LLM provider configuration](LLM_PROVIDER_CONFIGURATION.md).
