-- Public accounts; plaintext credentials never belong in application tables.
ALTER TABLE platform_users
 ADD COLUMN email text,
 ADD COLUMN password_hash text,
 ADD COLUMN email_verified boolean NOT NULL DEFAULT false,
 ADD COLUMN is_developer boolean NOT NULL DEFAULT false,
 ADD COLUMN disabled boolean NOT NULL DEFAULT false,
 ADD COLUMN roles jsonb NOT NULL DEFAULT '["USER"]',
 ADD COLUMN plan text NOT NULL DEFAULT 'FREE' CHECK (plan IN ('FREE','PRO')),
 ADD COLUMN plan_expires_at timestamptz,
 ADD COLUMN active_selection_initialized boolean NOT NULL DEFAULT false,
 ADD COLUMN auth_revision bigint NOT NULL DEFAULT 1;
CREATE UNIQUE INDEX platform_user_email ON platform_users(lower(email)) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX platform_single_developer ON platform_users(is_developer) WHERE is_developer;
ALTER TABLE platform_users ADD CONSTRAINT platform_roles_array CHECK (
 jsonb_typeof(roles)='array' AND roles <@ '["USER","PROFESSIONAL","REVIEWER"]'::jsonb AND roles @> '["USER"]'::jsonb
);
UPDATE platform_users SET roles='["USER","PROFESSIONAL"]' WHERE professional_verified;
ALTER TABLE platform_tokens ADD COLUMN expires_at timestamptz;
CREATE TABLE platform_auth_challenges (
 id uuid PRIMARY KEY,
 user_id uuid NOT NULL REFERENCES platform_users(id),
 email text NOT NULL,
 purpose text NOT NULL CHECK(purpose IN ('verify','reset','attach')),
 digest text NOT NULL,
 pending_password_hash text,
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
 expires_at timestamptz NOT NULL,
 consumed_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX platform_auth_challenge_lookup ON platform_auth_challenges(email,purpose,created_at DESC);
CREATE TABLE platform_auth_rate_buckets (
 key text NOT NULL,
 bucket bigint NOT NULL,
 count bigint NOT NULL,
 PRIMARY KEY(key,bucket)
);
CREATE TABLE platform_admin_audit (
 id bigserial PRIMARY KEY,
 actor_id uuid NOT NULL REFERENCES platform_users(id),
 target_user_id uuid REFERENCES platform_users(id),
 action text NOT NULL,
 details jsonb NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT now()
);
