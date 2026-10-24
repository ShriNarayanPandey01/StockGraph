-- Application data uses ordinary PostgreSQL tables, never hypertables.
CREATE TABLE platform_users (
 id uuid PRIMARY KEY, name text NOT NULL, professional_verified boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now(), verification_revision bigint NOT NULL DEFAULT 1
);
CREATE TABLE platform_tokens (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES platform_users(id),
 digest text NOT NULL UNIQUE, revoked_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE platform_contributions (
 id uuid PRIMARY KEY, author_id uuid NOT NULL REFERENCES platform_users(id),
 status text NOT NULL CHECK(status IN ('DRAFT','SUBMITTED','PUBLISHED','REJECTED','RETRACTED')),
 revision bigint NOT NULL DEFAULT 1, current_version_id uuid NOT NULL,
 published_version_id uuid, retracted_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE platform_contribution_versions (
 id uuid PRIMARY KEY, contribution_id uuid NOT NULL REFERENCES platform_contributions(id),
 version_number int NOT NULL, ticker text NOT NULL, content jsonb NOT NULL,
 event_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 known_at timestamptz NOT NULL DEFAULT now(), future_access text NOT NULL DEFAULT 'PRO' CHECK(future_access='PRO'),
 UNIQUE(contribution_id,version_number)
);
CREATE TABLE platform_contribution_requests (
 user_id uuid NOT NULL REFERENCES platform_users(id), request_key text NOT NULL,
 fingerprint text NOT NULL, contribution_id uuid NOT NULL REFERENCES platform_contributions(id),
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,request_key)
);
ALTER TABLE platform_contributions ADD CONSTRAINT current_version_fk FOREIGN KEY(current_version_id)
 REFERENCES platform_contribution_versions(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE platform_contributions ADD CONSTRAINT published_version_fk FOREIGN KEY(published_version_id)
 REFERENCES platform_contribution_versions(id) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE platform_submissions (
 version_id uuid PRIMARY KEY REFERENCES platform_contribution_versions(id),
 submitted_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE platform_reviews (
 id uuid PRIMARY KEY, version_id uuid NOT NULL UNIQUE REFERENCES platform_contribution_versions(id),
 reviewer_id uuid NOT NULL REFERENCES platform_users(id), decision text NOT NULL CHECK(decision IN ('APPROVE','REJECT')),
 reason text NOT NULL, reviewed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE platform_publications (
 version_id uuid PRIMARY KEY REFERENCES platform_contribution_versions(id), published_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE platform_retractions (
 id uuid PRIMARY KEY, contribution_id uuid NOT NULL REFERENCES platform_contributions(id),
 actor_id uuid NOT NULL REFERENCES platform_users(id), version_id uuid NOT NULL REFERENCES platform_contribution_versions(id),
 reason text NOT NULL, retracted_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE platform_outbox (
 event_id uuid PRIMARY KEY, event jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 published_at timestamptz, lease_id uuid, lease_until timestamptz,
 attempts int NOT NULL DEFAULT 0, next_attempt_at timestamptz NOT NULL DEFAULT now(), error text
);
CREATE INDEX platform_outbox_pending ON platform_outbox(next_attempt_at,created_at) WHERE published_at IS NULL;
CREATE INDEX platform_evidence_ticker ON platform_contribution_versions(ticker,expires_at);
CREATE TABLE platform_usage (
 user_id uuid NOT NULL REFERENCES platform_users(id), feature text NOT NULL,
 month date NOT NULL, units bigint NOT NULL DEFAULT 0, PRIMARY KEY(user_id,feature,month)
);
CREATE TABLE platform_request_buckets (
 user_id uuid NOT NULL REFERENCES platform_users(id), bucket bigint NOT NULL, count bigint NOT NULL,
 PRIMARY KEY(user_id,bucket)
);
-- Freezing is append-only: a correction inserts another immutable version.
CREATE FUNCTION platform_prevent_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Platform history is immutable; append a new version';
END;
$$;
CREATE TRIGGER contribution_version_immutable BEFORE UPDATE OR DELETE ON platform_contribution_versions
 FOR EACH ROW EXECUTE FUNCTION platform_prevent_history_mutation();
CREATE TRIGGER contribution_review_immutable BEFORE UPDATE OR DELETE ON platform_reviews
 FOR EACH ROW EXECUTE FUNCTION platform_prevent_history_mutation();
CREATE TRIGGER contribution_submission_immutable BEFORE UPDATE OR DELETE ON platform_submissions
 FOR EACH ROW EXECUTE FUNCTION platform_prevent_history_mutation();
CREATE TRIGGER contribution_publication_immutable BEFORE UPDATE OR DELETE ON platform_publications
 FOR EACH ROW EXECUTE FUNCTION platform_prevent_history_mutation();
CREATE TRIGGER contribution_retraction_immutable BEFORE UPDATE OR DELETE ON platform_retractions
 FOR EACH ROW EXECUTE FUNCTION platform_prevent_history_mutation();
