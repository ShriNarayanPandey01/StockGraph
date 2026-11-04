-- Agent accounting and evaluation state are owned by Platform.
ALTER TABLE job_evidence DROP CONSTRAINT job_evidence_kind_check;
ALTER TABLE job_evidence ADD CONSTRAINT job_evidence_kind_check
 CHECK(kind IN ('news','professional','document','financial','graph'));
ALTER TABLE job_evidence DROP CONSTRAINT job_evidence_pkey;
ALTER TABLE job_evidence ADD PRIMARY KEY(job_id,kind,evidence_id,locator,ticker);
ALTER TABLE agent_jobs ADD COLUMN contract_version integer NOT NULL DEFAULT 1 CHECK(contract_version IN (1,2));
ALTER TABLE opportunity_alerts ADD COLUMN opportunity jsonb;
ALTER TABLE opportunity_alerts ADD COLUMN catalyst_event_id text;
ALTER TABLE opportunity_alerts ADD COLUMN opportunity_revision text;
CREATE INDEX opportunity_alerts_catalyst ON opportunity_alerts(user_id,ticker,catalyst_event_id);

CREATE TABLE agent_model_reservations (
 id uuid PRIMARY KEY,
 job_id uuid NOT NULL REFERENCES agent_jobs(id),
 request_key uuid NOT NULL,
 model text NOT NULL,
 input_tokens integer NOT NULL CHECK(input_tokens > 0),
 output_tokens integer NOT NULL CHECK(output_tokens > 0),
 input_rate numeric(18,9) NOT NULL CHECK(input_rate > 0),
 output_rate numeric(18,9) NOT NULL CHECK(output_rate > 0),
 used_input_tokens integer CHECK(used_input_tokens >= 0),
 used_output_tokens integer CHECK(used_output_tokens >= 0),
 reserved_usd numeric(18,9) NOT NULL CHECK(reserved_usd > 0),
 charged_usd numeric(18,9) NOT NULL CHECK(charged_usd >= 0),
 settled boolean NOT NULL DEFAULT false,
 month date NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(job_id, request_key)
);
CREATE INDEX agent_model_reservations_month ON agent_model_reservations(month);

CREATE TABLE agent_candidate_snapshots (
 job_id uuid PRIMARY KEY REFERENCES agent_jobs(id),
 as_of_ts bigint NOT NULL,
 items jsonb NOT NULL,
 truncated boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE agent_monitor_evaluations (
 id uuid PRIMARY KEY,
 monitor_id uuid NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
 job_id uuid NOT NULL UNIQUE REFERENCES agent_jobs(id),
 evaluated_at timestamptz NOT NULL DEFAULT now(),
 outcome jsonb NOT NULL
);
CREATE INDEX agent_monitor_evaluations_monitor ON agent_monitor_evaluations(monitor_id,evaluated_at DESC);

CREATE TABLE agent_worker_heartbeats (
 worker_id uuid PRIMARY KEY,
 enabled boolean NOT NULL,
 last_seen timestamptz NOT NULL DEFAULT now()
);
