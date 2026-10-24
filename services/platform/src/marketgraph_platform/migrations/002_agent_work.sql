CREATE TABLE watchlists (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES platform_users(id),
 name text NOT NULL, tickers jsonb NOT NULL DEFAULT '[]', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX watchlists_owner ON watchlists(user_id,created_at);
CREATE TABLE conversations (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES platform_users(id),
 title text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE research_messages (
 id uuid PRIMARY KEY, conversation_id uuid NOT NULL REFERENCES conversations(id),
 user_id uuid NOT NULL REFERENCES platform_users(id), role text NOT NULL CHECK(role IN ('user','assistant')),
 content text NOT NULL, evidence jsonb NOT NULL DEFAULT '[]', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_conversation ON research_messages(conversation_id,created_at,id);
CREATE TABLE monitors (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES platform_users(id),
 watchlist_id uuid NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
 question text NOT NULL, interval_seconds integer NOT NULL CHECK(interval_seconds>=60),
 active boolean NOT NULL DEFAULT true, next_run_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX monitors_due ON monitors(next_run_at) WHERE active;
CREATE TABLE agent_jobs (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES platform_users(id),
 kind text NOT NULL CHECK(kind IN ('chat','discovery','monitor')),
 input jsonb NOT NULL, result jsonb, request_key text NOT NULL, fingerprint text NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','running','completed','failed','cancelled')),
 attempts integer NOT NULL DEFAULT 0, lease_token uuid, lease_until timestamptz,
 result_fingerprint text, error text, created_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz, UNIQUE(user_id,request_key)
);
CREATE INDEX agent_jobs_queue ON agent_jobs(state,created_at);
CREATE INDEX agent_jobs_owner_queue ON agent_jobs(user_id,state);
CREATE TABLE opportunity_alerts (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES platform_users(id),
 job_id uuid NOT NULL REFERENCES agent_jobs(id), ticker text NOT NULL,
 direction text NOT NULL, summary text NOT NULL, evidence jsonb NOT NULL,
 dedupe_key text NOT NULL, seen_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(user_id,dedupe_key)
);
CREATE INDEX alerts_owner ON opportunity_alerts(user_id,created_at DESC,id DESC);
CREATE TABLE agent_usage (
 user_id uuid NOT NULL REFERENCES platform_users(id), job_id uuid NOT NULL REFERENCES agent_jobs(id),
 metric text NOT NULL, amount bigint NOT NULL CHECK(amount>=0), created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(job_id,metric)
);
CREATE TABLE job_evidence (
 job_id uuid NOT NULL REFERENCES agent_jobs(id), kind text NOT NULL CHECK(kind IN ('news','professional','document','financial')),
 evidence_id text NOT NULL, locator text NOT NULL DEFAULT '', ticker text NOT NULL,
 source jsonb NOT NULL, quote_text text NOT NULL, material_version text NOT NULL,
 lease_token uuid NOT NULL, eligible_until timestamptz NOT NULL,
 fetched_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(job_id,kind,evidence_id,locator)
);
CREATE TABLE agent_access_audit (
 id bigserial PRIMARY KEY, job_id uuid REFERENCES agent_jobs(id), actor text NOT NULL,
 action text NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now()
);
