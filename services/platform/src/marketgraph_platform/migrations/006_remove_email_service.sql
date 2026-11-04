-- Email ownership is no longer verified by this deployment.
DROP TABLE platform_auth_challenges;
ALTER TABLE platform_users DROP COLUMN email_verified;
