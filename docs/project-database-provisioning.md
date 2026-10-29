# Project database provisioning

Project creation uses the existing PostgreSQL cluster and backend process. It does
not create AWS infrastructure or launch another ECS task. No Terraform changes
are included.

## Configuration prerequisites

- `CEDARS_DATABASE_URL`: global database URL for the shared runtime database user.
- `CEDARS_PROJECT_PROVISIONING_DATABASE_URL`: PostgreSQL administrative connection
  to the same writer endpoint. This identity must have CREATEDB and permission to
  create a database owned by the runtime user. It is not inferred from the runtime
  URL and is never returned through the API.
- `CEDARS_PROJECT_DATABASE_SECRET_PREFIX`: defaults to
  `user-cedars/project-databases`.
- `CEDARS_PROJECT_PROVISIONING_TIMEOUT_SECONDS`: defaults to 120 seconds. Configure
  upstream HTTP timeouts to allow this bounded operation.
- `CEDARS_AWS_REGION`: Secrets Manager region, or the normal AWS region configuration.

The existing backend task credentials must already permit Secrets Manager
CreateSecret and GetSecretValue on the chosen prefix. Backend, worker, and
migration credentials need GetSecretValue on tenant secrets and any required KMS
permissions. This code does not add those privileges or alter AWS architecture.
The shared runtime PostgreSQL identity can access every tenant database; this is
application routing isolation, not per-tenant credential isolation.

## Creation and recovery

The global project and creator admin membership commit together in one database
transaction. The project is initially `provisioning`. The request then:

1. Locks the global project row to serialize retries.
2. Creates `cedars_project_<uuid-without-hyphens>` in autocommit mode, owned by
   the runtime user. An existing database is reused, not deleted or reset.
3. Applies the frozen project Alembic baseline and subsequent revisions.
4. Creates a deterministic Secrets Manager entry containing `database_url`.
   An existing entry must match; it is never overwritten with a different route.
5. Seeds current membership identities and attribution actors into `ProjectUsers`.
   The creator is an active admin and investigator with self-attribution. Other
   attribution-only actors are inactive. No password hashes are copied.
6. Commits readiness and schema revision to the global project registry.

HTTP 201 is returned only after readiness. A setup failure returns HTTP 503 with
a sanitized message and project ID. The global rows remain, marked `failed`.
Database, schema, and secret creation cannot participate in the global transaction.
Partial external resources are retained for retry, never automatically deleted.
Blocking Alembic/SDK work may finish after a request timeout; readiness is not
published by those background threads. Migration locks make schema retries safe.

An operator can resume a failed or interrupted setup without SQL patches:

```sh
cd backend
uv run python -m app.projects.provisioning <project-uuid>
```

Do not submit another create request to retry: it creates a different project.
No project deletion, tenant-data copy, or migration HTTP endpoint is included.

## Whole-server migration

Stop API/worker writes and project creation for the maintenance window. Keep them
stopped until the full migration command succeeds. The existing command remains:

```sh
cd backend
uv run alembic upgrade head
```

It invokes `app.common.migrations` in a separate process to avoid nesting
Alembic's process-global environment. The runner upgrades global first, reads
every row in `projects` (including retained soft-deleted projects), and requires
every project to have `database_secret_ref`. Missing references stop preflight
before tenant migrations. Each referenced database is upgraded serially, its
membership projection refreshed, and its schema version recorded. One failure
causes a nonzero result; already successful databases remain upgraded. Fix the
cause and rerun the same whole-server command. Do not start serving on a partial
upgrade. There is no cross-database atomic rollback.

Global and project revision histories are separate implementation targets, not
independent deployment workflows. Both ship with the same server release. New
databases use frozen baselines rather than `metadata.create_all`.

The historical combined revisions remain in `backend/migrations`. Explicit
historical tooling may use `alembic -x legacy=true ...`. Revision authoring and
schema inspection use `global-alembic.ini` or `project-alembic.ini`; deployment
always upgrades all databases. A pre-existing unversioned schema is adopted only
if its full target metadata matches; a partial/incompatible schema is rejected,
not stamped blindly. This does not upgrade or split the old shared clinical
database into tenants. Existing project references and compatible schemas are
deployment prerequisites.

## Verification limits

Tests exercise separate SQLite databases, frozen-baseline upgrades and roundtrips,
PostgreSQL offline DDL, failure redaction, tenant identity seeding, and partial
migration retries. Actual CREATE DATABASE privileges, PostgreSQL DDL execution,
Secrets Manager access, and production network reachability require PostgreSQL
integration and approved deployment verification. Unit tests do not establish
those permissions.