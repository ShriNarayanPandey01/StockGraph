# LLM provider configuration

StockGraph uses the LiteLLM adapter for chat inference. Provider selection is
deployment-wide and comes from environment variables, so switching providers
does not require a code change. Both `graph-api` and `graph-worker` must receive
the same settings. The checked-in `.env.example` selects Meta's Muse Spark model
through Baseten; this document explains that model/provider split and how to
change it. See [Meta model and AI usage](AI_AND_MODEL_USAGE.md) for the workflows
that call the model and the separate embedding path.

## Baseten Muse Spark Open

The local `.env.example` selects Meta's Muse Spark model,
`meta-models/muse-spark-open-1026`, for chat and ontology inference. Baseten is
the serving provider in this configuration; the project sends requests to
Baseten's OpenAI-compatible endpoint. Set `BASETEN_API_KEY` in the ignored local
`.env` file or the deployment secret store. The default OpenAI-compatible
endpoint is `https://inference.baseten.co/v1` and can be changed with
`BASETEN_API_BASE`.

```dotenv
LLM_ENABLED=true
LLM_PROVIDER=baseten
LLM_CHAT_MODEL=meta-models/muse-spark-open-1026
LLM_ONTOLOGY_MODEL=meta-models/muse-spark-open-1026
BASETEN_API_BASE=https://inference.baseten.co/v1
BASETEN_API_KEY=<Baseten key>
OPENAI_API_KEY=<separate OpenAI key for embeddings>
```

The adapter routes the model through LiteLLM's OpenAI-compatible integration and
sends the Baseten key only to the chat call. `OPENAI_API_KEY` remains reserved
for `text-embedding-3-small` embeddings. Keep the embedding model and dimension
unchanged while existing graph vectors are in use; changing either requires a
planned re-embedding and index migration.

## Switching providers

Set `LLM_PROVIDER`, the corresponding credential, and provider's expected model
identifier. `LLM_CHAT_MODEL` and `LLM_ONTOLOGY_MODEL` can be the same model or
different models supported by the selected provider.

| `LLM_PROVIDER` | Credential | Model identifier | Optional endpoint |
| --- | --- | --- | --- |
| `baseten` | `BASETEN_API_KEY` | Baseten deployment/model ID, such as `meta-models/muse-spark-open-1026` | `BASETEN_API_BASE` |
| `openai` | `OPENAI_API_KEY` | OpenAI model ID, such as `gpt-4o-mini` | LiteLLM default |
| `anthropic` | `ANTHROPIC_API_KEY` | Anthropic model ID, such as `claude-3-5-haiku-latest` | LiteLLM default |
| `openrouter` | `OPENROUTER_API_KEY` | OpenRouter model ID, such as `anthropic/claude-3.5-haiku` | LiteLLM default |
| `openai_compatible` | `LLM_API_KEY` | Model ID accepted by the endpoint | Required `LLM_API_BASE` |
| `litellm` | Optional `LLM_API_KEY` | Full LiteLLM model string, including provider prefix | Optional `LLM_API_BASE` |
| `legacy` | Depends on the model string | Existing LiteLLM model string | Existing LiteLLM behavior |

If `LLM_PROVIDER` is absent, it defaults to `legacy` so existing deployments
keep their previous model-string routing. Provider credentials are selected
independently; a configured Baseten key is never used as the OpenAI embedding
key or as credentials for another chat provider.

For a different OpenAI-compatible endpoint, for example:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_API_BASE=https://llm.example.com/v1
LLM_API_KEY=<endpoint key>
LLM_CHAT_MODEL=my-chat-model
LLM_ONTOLOGY_MODEL=my-chat-model
```

## Gemini embeddings

Gemini embeddings use a separate credential from chat inference. For example:

```dotenv
GEMINI_API_KEY=<Gemini key>
EMBEDDING_MODEL=gemini/gemini-embedding-2
EMBEDDING_DIMENSION=1536
EMBEDDING_PRICE_PER_1K=0
```

The zero price is appropriate only while the account uses the free tier.
Before changing embedding models, regenerate all existing vectors using the new
model; vectors from different models cannot be compared, even at the same
dimension. Recreate both graph services after updating the settings.

Providers outside the named choices can use `LLM_PROVIDER=litellm`, their
LiteLLM-prefixed model name, and optionally the generic key and endpoint.

## Structured output and validation

`LLM_JSON_MODE=auto` selects JSON Schema mode for Anthropic, JSON object mode
for the named OpenAI-compatible providers, and prompt-only mode for open-ended
LiteLLM integrations. Set `json_object`, `json_schema`, or `prompt` explicitly
if a provider has different capabilities.

Muse Spark Open accepts a JSON mode request but does not guarantee valid JSON
or enforce a supplied JSON schema. The adapter therefore appends the Pydantic
output contract after the bounded prompt, checks that the model finished
normally and did not refuse, parses the result, and validates it against the
requested Pydantic model before any graph write. Truncated, malformed, refused,
or schema-invalid responses remain retryable processing failures.

## Spend estimates and limits

`CHAT_PRICE_PER_1K` and `EMBEDDING_PRICE_PER_1K` are operator-supplied USD
estimates per 1,000 input tokens. They are not fetched from provider pricing
and must be updated when switching providers or models. The chat estimate uses
`CHAT_PRICE_PER_1K`; embeddings continue to use their separate estimate.
`LLM_MONTHLY_USD_CAP` limits the shared monthly spend ledger, and
`LLM_MAX_TOKENS_PER_CALL` bounds the full prompt, including the output schema.
Choose estimates conservatively for the selected provider's billing rates.

## Applying configuration changes

The provider and credentials are read when each process starts. After changing
`.env` or deployment environment settings, restart/recreate both `graph-api`
and `graph-worker`. In Docker Compose, run `docker compose up -d --force-recreate
graph-api graph-worker`; for local `uv` processes, stop and start both processes.
Keep `LLM_ENABLED=false` for offline operation.
