-- 010_make_withdrawal_backup_email_nullable.sql
-- BR-A13 (FR-27 ORCID): ORCID accounts can have accounts.email=NULL. Withdrawal backups copy
-- that account-owned snapshot during hard purge, so the backup email must also allow NULL.

ALTER TABLE account_withdrawal_backups ALTER COLUMN email DROP NOT NULL;
