# Upgrade and recovery

Template SemVer and upstream dependency versions are independent. Current template: `1.0.0`; monorepo immutable tag when released: `llamaindex-durable-agents-v1.0.0`; compatibility channel: `release-v1`. Nothing has been tagged or published yet.

1. Back up the **entire dedicated PostgreSQL database**, including DBOS schema, workflow store/state/journal/events and `demo_*` tables. Keep credentials and executor prefix separately secured. Practice restoring to a disposable instance; full backup/restore disaster recovery is an **unverified gate** here.
2. Drain all runs, including approval waits, before changing workflow/event code, provider settings or DBOS application version. Alternatively keep a compatible old workflow registered and deploy new work under a deliberate new durable name and version. Do not silently reuse `invoice-approval-v1`/`approval-v1` for incompatible code.
3. Preserve `DBOS_EXECUTOR_PREFIX` and the dedicated database during ordinary same-code process replacements. Stop the old API before starting the replacement; allow crash lease expiry. Automatic Railway rolling handover is not proven.
4. Pin new versions, regenerate `uv.lock`/`bun.lock`, review upstream migrations and experimental lease changes, increment `VERSION` and `CHANGELOG.md` for distributed changes. Re-run clean image build, SQL replay, pending-approval replacement and draft audits.
5. PostgreSQL major upgrades require a documented logical restore or supported physical migration; never point a different major image at an old data directory. Preserve the mount path. Changing `POSTGRES_PASSWORD` after initialization alone does not rotate the existing database user's password.
6. Roll back application code only against a schema compatible with it and after draining new-version work. Avoid automatic downgrade migrations. Restore a backup to a separate volume first if schema rollback is required.

Exactly-once billing is not supported: a hosted proposal request interrupted before durable step persistence can be repeated after recovery. SQL ledger replay is safe because a request primary key and transactional payload check guard the actual demo effect. Extend external side effects only with a downstream idempotency contract and tested reconciliation.
