-- Transactional application policy and encrypted broker credentials.
CREATE TABLE platform_plan_policies (
 plan text PRIMARY KEY CHECK(plan IN ('FREE','PRO')),
 active_stock_limit integer CHECK(active_stock_limit > 0),
 monthly_alert_limit integer CHECK(monthly_alert_limit > 0),
 features jsonb NOT NULL,
 revision bigint NOT NULL DEFAULT 1
);
INSERT INTO platform_plan_policies VALUES
('FREE',10,10,'{"professional_evidence":false,"research_chat":true,"discovery":false,"opportunity_alerts":true,"stock_connections":true,"monitoring":true,"market_monitoring":false}',1),
('PRO',NULL,NULL,'{"professional_evidence":true,"research_chat":true,"discovery":true,"opportunity_alerts":true,"stock_connections":true,"monitoring":true,"market_monitoring":true}',1);
CREATE TABLE platform_active_stocks (
 user_id uuid NOT NULL REFERENCES platform_users(id),
 ticker text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,ticker)
);
CREATE TABLE platform_broker_connections (
 user_id uuid PRIMARY KEY REFERENCES platform_users(id),
 encrypted_token bytea,
 revision bigint NOT NULL DEFAULT 1,
 status text NOT NULL CHECK(status IN ('connected','reconnect_required','disconnected')),
 validated_at timestamptz, updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE agent_jobs ADD COLUMN required_plan text NOT NULL DEFAULT 'PRO' CHECK(required_plan IN ('FREE','PRO'));
ALTER TABLE agent_jobs ADD COLUMN actor_id uuid REFERENCES platform_users(id);
ALTER TABLE research_messages ADD COLUMN required_plan text NOT NULL DEFAULT 'PRO' CHECK(required_plan IN ('FREE','PRO'));
UPDATE research_messages SET required_plan='FREE' WHERE role='user';
ALTER TABLE opportunity_alerts ADD COLUMN required_plan text NOT NULL DEFAULT 'PRO' CHECK(required_plan IN ('FREE','PRO'));
ALTER TABLE monitors ADD COLUMN scope text NOT NULL DEFAULT 'watchlist' CHECK(scope IN ('watchlist','market'));
ALTER TABLE monitors ALTER COLUMN watchlist_id DROP NOT NULL;
ALTER TABLE monitors ADD CONSTRAINT monitors_scope CHECK(
 (scope='watchlist' AND watchlist_id IS NOT NULL) OR (scope='market' AND watchlist_id IS NULL));
ALTER TABLE monitors ADD COLUMN pause_reason text;
ALTER TABLE monitors ADD COLUMN actor_id uuid REFERENCES platform_users(id);
UPDATE monitors SET pause_reason='Select active stocks to resume';
UPDATE agent_jobs SET state='cancelled',lease_token=NULL,lease_until=NULL,finished_at=now(),
 error='Access policy changed; select active stocks and resubmit'
WHERE state IN ('pending','running');

