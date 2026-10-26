# Platform accounts, permissions, plans and broker connections

This document supersedes the unrestricted-access policy in the original Phase 1
blueprint. Data owns SQL/source ingestion, Graph owns FalkorDB/LLM work, and
Platform owns accounts, application permissions and its separate ordinary
PostgreSQL database. `services/agents/` is a fourth workspace package containing
only a future-agent scaffold. Payments are disabled and no future provider has
been selected. Frontend work, order execution and remote HTTP MCP services remain deferred.

## Accounts and developer access

Public signup creates a Free account with the User role. Email verification,
password recovery and credential attachment use one-time emailed codes with a
15-minute expiry and five attempts. SMTP must be configured for mail-dependent
operations. Signup, login and resend operations have separate abuse limits;
recovery responses do not disclose whether an account exists. Passwords use
Argon2id. Login creates an opaque bearer session with a 12-hour default lifetime;
only its digest is stored. Existing operator-issued tokens remain supported.

The developer account is configured by `PLATFORM_ADMIN_NAME`,
`PLATFORM_ADMIN_EMAIL` and `PLATFORM_ADMIN_PASSWORD`. Initialization is idempotent
and coordinated across replicas. Only this environment-managed identity is a
developer; public payloads cannot select that role. Changing its environment
credentials revokes its previous sessions. Local setup may use
`admin@marketgraph.local` with a generated password stored only in ignored `.env`.
Never commit or print that password. The developer can log in without SMTP.

The developer has every supported application permission and access to users'
application records. Developer operations bypass role, ownership, plan and
per-user quota checks, including the independent-review restriction: developer
self-approval is permitted and audited. Canonical entity validation, citation
integrity, immutable version history and transaction checks still apply. Global
provider/model budgets remain operating configuration.

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
key in `.env`, never in source control. SMTP settings are `PLATFORM_SMTP_HOST`,
`PLATFORM_SMTP_PORT`, `PLATFORM_SMTP_USERNAME`, `PLATFORM_SMTP_PASSWORD`,
`PLATFORM_SMTP_FROM`, `PLATFORM_SMTP_STARTTLS`, `PLATFORM_SMTP_SSL` and
`PLATFORM_SMTP_TIMEOUT_SECONDS`. Port 587 with STARTTLS is the default; implicit
TLS can be configured with SSL instead. Do not enable both transport modes.
Developer/SMTP/broker-vault secrets are passed only to `platform-api`, not its
worker. Existing `UPSTOX_ANALYTICS_TOKEN` / `UPSTOX_AUTHTOKEN` compatibility remains.

### Brevo SMTP: authorize the sending server's IP

When Brevo's blocking of unknown IP addresses is enabled for SMTP keys, add the
**public outbound IP address of every server running `platform-api`** under
Brevo **Security > Authorized IPs** before sending email. This is the API server's
internet-facing egress address, rather than the website user's IP, a Docker
container's private address, or `127.0.0.1`. Local development and deployed API
servers can use different outbound IPs; authorize each environment's addresses.
Update the list if an address changes, including after an ISP change or a
deployment that changes the server's egress addresses.

To check the local container's current public outbound IP without sending email:

```powershell
docker compose exec -T platform-api python -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org', timeout=10).read().decode())"
```

Removing the sending server's IP from the authorized list while blocking is
enabled prevents SMTP email delivery, including verification and recovery codes.
Brevo can report `525 5.7.1 Unauthorized IP address`; valid SMTP credentials alone
do not resolve this error. See [Brevo's API and SMTP IP authorization guide](https://help.brevo.com/hc/en-us/articles/5740111683858-Authorize-and-block-IP-addresses-for-API-and-SMTP-security).

Back up Platform data before numbered migrations and coordinate application
rollout so internal clients and servers receive matching keys. Never rewrite an
applied migration, recreate database containers to apply application changes, or
delete volumes. Existing non-developer accounts become Free, retain verified
professional authoring rights and require explicit active-stock initialization.
Reviewer grants are explicit. Existing records remain stored; ineligible work
pauses/cancels, and current-month alerts count toward the Free allowance.

`services/agents/` is excluded from ordinary Compose startup. To run its optional
health-only scaffold, use `docker compose --profile agents-template up -d --build
agents-template`; see [the template guide](../services/agents/README.md). Port 8005
reports execution disabled and zero registered agents. No handlers, model calls,
job-consumption loop, scheduler, database or broker access are implemented there.
Existing external agents retain the leased Platform REST contract.

Offline validation uses `uv run --all-packages pytest -q` and `uv run --all-packages
ruff check services scripts tests`. Mock SMTP/provider operations; no real orders
or removed integration-testing infrastructure are used.
