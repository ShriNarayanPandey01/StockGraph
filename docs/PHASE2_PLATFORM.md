# Platform accounts, permissions, plans and broker connections

This document supersedes the unrestricted-access policy in the original Phase 1
blueprint. Data owns SQL/source ingestion, Graph owns FalkorDB/LLM work, and
Platform owns accounts, application permissions and its separate ordinary
PostgreSQL database. `services/agents/` contains the opt-in LangGraph worker for
the developer pilot. Payments are disabled and no future provider has been
selected. Order execution and remote HTTP MCP services remain deferred.

## Accounts and developer access

Public signup creates an immediately usable Free account with the User role.
Signup and login have separate abuse limits, and signup returns the same response
for existing addresses. Passwords use Argon2id. Login creates an opaque bearer
session with a 12-hour default lifetime; only its digest is stored. Existing
operator-issued tokens remain supported. Authenticated users can change their
password by providing the current password. Signup does not prove ownership of
an email address. Forgotten-password recovery is unavailable until a new
provider-backed feature is built.

The developer account is configured by `PLATFORM_ADMIN_NAME`,
`PLATFORM_ADMIN_EMAIL` and `PLATFORM_ADMIN_PASSWORD`. Initialization is idempotent
and coordinated across replicas. Only this environment-managed identity is a
developer; public payloads cannot select that role. Changing its environment
credentials revokes its previous sessions. Local setup may use
`admin@marketgraph.local` with a generated password stored only in ignored `.env`.
Never commit or print that password. The developer uses the same login endpoint.

The developer has every supported application permission and access to users'
application records. Developer operations bypass role, ownership, plan and
per-user quota checks, including the independent-review restriction: developer
self-approval is permitted and audited. The developer can grant/remove the
Professional and Reviewer roles, verify/revoke professional status, assign Free
or Pro with an optional expiry, disable/restore users, revoke sessions, and edit
versioned canonical graph descriptions and developer-created graph links.
Canonical entity validation, citation integrity, immutable version history and
transaction checks still apply. Global provider/model budgets remain operating
configuration.

Using the developer bearer session on existing authenticated Platform routes
also grants access to other users' supported records and workflows. Ownership
checks and plan limits are bypassed for the developer; record lifecycle rules,
immutable evidence versions, leases and audit history remain enforced.

Ordinary roles are combinable: User, Professional and Reviewer. The developer
verifies professionals and assigns reviewers. Non-developer professional
publication requires a verified author and an independent authorized reviewer.
Author/reviewer duties do not grant general premium-intelligence access.

## Free and Pro

| Capability | Free | Pro | Developer |
|---|---|---|---|
| Active stocks | 10 | No product limit | Unrestricted |
| Research | One active stock per request | Broader research | Unrestricted |
| Connections and financial context | Active stocks, ordinary evidence | Full permitted context | Unrestricted |
| Watchlist monitoring | Active stocks only | Available | Unrestricted |
| Broad discovery / market-wide monitoring | Restricted | Available | Unrestricted |
| Professional intelligence | Restricted | Available | Unrestricted |
| New opportunity alerts | 10 per IST calendar month | No product limit | Unrestricted |
| Connect own Upstox token | Available | Available | Available |

The developer assigns Free or Pro manually; Pro can have an optional expiry.
Billing remains disabled and Stripe or another provider may be evaluated later.
`GET /api/v1/me`, `/api/v1/access-policy` and `/api/v1/me/usage` expose the
effective permissions, plan, limits and usage. `GET/PUT /api/v1/me/active-stocks`
controls the selected stocks. Catalog search does not activate a stock. Inactive
watchlist entries are preserved; monitors evaluate only their eligible active
subset and pause when it is empty.

Stock selection and alert allocation are transactional. Only newly created
deduplicated alerts consume quota; retries and acknowledgements do not. Months
reset in `Asia/Kolkata`. Research can complete when the alert allowance is used
up, returning a count of suppressed new alerts rather than deferring them into
another month. Plan changes do not reset usage.

Permissions are checked at submission, scheduling, claim, tool/context access and
completion. Professional evidence is filtered before graph pagination and agent
delivery; caches distinguish evidence access. Revocation/downgrade affects new
work and subsequent reads, including historical results containing premium
evidence. Legacy results with uncertain provenance are restricted conservatively.
The developer retains access to all history.

Developer graph operations are available under `/api/v1/admin/graph`: catalog
reads, versioned catalog edits, full paginated per-stock graph context (including
professional evidence), and paginated create/read/update/delete operations for
developer-created links. Catalog edits go through Data Service SQL versions and
its graph outbox. Manual graph links keep edit history and appear in stock
connection context. Provider, baseline and inferred edges continue through their
own source/versioning flows.

## Optional Upstox connections

Authenticated `PUT`, `GET` and `DELETE
/api/v1/me/broker-connections/upstox` connect/replace a token, inspect status and
disconnect it. Status responses never include the token. Platform encrypts
personal credentials at rest using `PLATFORM_BROKER_ENCRYPTION_KEY`; retain this
key securely across deployments and backups. A submitted token is validated by a
bounded market-data request through the Data Service adapter.

User-initiated on-demand market-data reads prefer the user's saved credential.
When no personal connection exists, the existing `.env` Upstox credential serves
shared market-data requests. An invalid/expired personal token reports a
reconnect state instead of silently falling back. Explicit disconnection restores
shared market-data fallback. SQL/graph reads do not require a broker connection.

Scheduled shared ingestion and canonical registration always use the environment
credential; users' tokens are not borrowed for global ingestion. The shared
credential cannot expose the developer's portfolio, holdings, funds or account
history to users. No order endpoint is added, regardless of token capability.
An Analytics Token remains read-only.

Provider HTTP calls stay inside Data adapters. Platform forwards decrypted tokens
only over authenticated internal requests. Graph services, agents, Redis events,
job payloads, citations, logs and LLM prompts never receive broker credentials.
Credential-specific clients and user/credential-revision cache namespaces prevent
cross-account responses. Provider limits apply to the actual credential used.

## Internal APIs and local MCP

Set the same strong `MARKETGRAPH_INTERNAL_SERVICE_KEY` for Data, Graph, Platform
and their internal clients. Domain requests to Data/Graph require
`X-Internal-Service-Key`; missing server configuration fails closed. Health,
readiness and API-schema endpoints remain available for deployment diagnostics.
End users authenticate to Platform with `Authorization: Bearer <session>`.

Trusted internal requests select `X-MarketGraph-Evidence-Scope: ordinary` or
`professional`; ordinary is the default. The trusted developer context uses
`X-MarketGraph-Developer: true`. These headers are accepted only behind the
internal service credential. Personal market-data requests use the protected
`X-Upstox-Access-Token` and `X-MarketGraph-Credential-Scope` headers; neither is
returned to user agents or callers.

The retained `stockgraph-mcp` command uses local stdio transport. Configure
`MARKETGRAPH_PLATFORM_URL` and `MARKETGRAPH_PLATFORM_TOKEN`; its tools call
authenticated Platform equivalents and inherit the same policies. No service on
ports 8003/8004 is recreated. Trusted operator scripts that call Data/Graph
directly also need the internal service key in their environment.

## Configuration and rollout

Set developer credentials, the internal service key and the broker encryption
key in `.env`, never in source control. Developer and broker-vault secrets are
passed only to `platform-api`, not its worker. Existing
`UPSTOX_ANALYTICS_TOKEN` / `UPSTOX_AUTHTOKEN` compatibility remains.

Back up Platform data before numbered migrations and coordinate application
rollout so internal clients and servers receive matching keys. Never rewrite an
applied migration, recreate database containers to apply application changes, or
delete volumes. Existing non-developer accounts become Free, retain verified
professional authoring rights and require explicit active-stock initialization.
Reviewer grants are explicit. Active records remain stored; ineligible work
pauses/cancels, and current-month alerts count toward the Free allowance.

Migration `006_remove_email_service.sql` drops the challenge table and
`email_verified` column. During this rollout, back up the old schema, stop
account writers, and purge pending accounts with email addresses before applying
the migration. Preserve developer and email-less legacy accounts and admin audit
history; revoke old professional identities through the outbox. Older Platform
archives must be restored with the matching older application schema before
running newer migrations.

`services/agents/` is excluded from ordinary Compose startup. The optional
`agents` profile runs the LangGraph worker after an operator configures its model,
machine key, conservative rates, and budget; see [the agent guide](../services/agents/README.md).
Its pilot claims developer-owned jobs only. The separate `agents-template` health
process reports the registered handlers without consuming jobs. Existing external
agents retain the version 1 leased Platform REST contract.

Offline validation uses `uv run --all-packages pytest -q` and `uv run --all-packages
ruff check services scripts tests`. Mock provider operations; no real orders
or removed integration-testing infrastructure are used.
