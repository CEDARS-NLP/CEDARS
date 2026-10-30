# Project database provisioning

Project creation uses the existing PostgreSQL cluster and backend process. It does
not create AWS infrastructure or launch another ECS task. Terraform injects the
externally managed runtime and provisioning secret ARNs; it does not store their
values.

## Configuration prerequisites

- `CEDARS_DATABASE_URL`: global database URL for the non-superuser runtime login.
- `CEDARS_PROJECT_PROVISIONING_DATABASE_URL`: connection to the same PostgreSQL
  writer endpoint using a separate login. It must have `CREATEDB` and membership
  in the runtime role so it can create a tenant database owned by that role. The
  URL is injected into the backend only; it is not inferred from the runtime URL
  or returned through the API.
- `CEDARS_PROJECT_DATABASE_SECRET_PREFIX`: defaults to
  `user-cedars/project-databases`.
- `CEDARS_PROJECT_PROVISIONING_TIMEOUT_SECONDS`: defaults to 120 seconds. Configure
  upstream HTTP timeouts to allow this bounded operation.
- `CEDARS_AWS_REGION`: Secrets Manager region, or the normal AWS region configuration.

Create the runtime and provisioning DSN secrets in AWS Secrets Manager outside
Terraform, using secret names that begin with `user-`. Pass their ARNs as the
`runtime_database_url_secret_arn` and `provisioning_database_url_secret_arn`
Terraform variables. Secret values are intentionally not Terraform-managed, so
they do not enter Terraform state. The ECS execution role needs
`secretsmanager:GetSecretValue` on those exact ARNs to inject them. The backend,
worker, and migration task role needs `secretsmanager:GetSecretValue` on the
tenant-secret prefix; project provisioning additionally needs
`secretsmanager:CreateSecret` restricted by `secretsmanager:Name` to that prefix.
Add the same actions to any externally managed task role and any required KMS
permissions if a customer-managed key is used.

Provision the PostgreSQL roles through the approved database administration
process, not Terraform variables or migration SQL. The intended privilege shape
is equivalent to:

```sql
CREATE ROLE cedars_runtime LOGIN PASSWORD '<runtime-secret-value>';
CREATE ROLE cedars_project_provisioner LOGIN CREATEDB PASSWORD '<provisioner-secret-value>';
GRANT cedars_runtime TO cedars_project_provisioner;
GRANT CONNECT ON DATABASE cedars TO cedars_runtime;
GRANT CREATE ON SCHEMA public TO cedars_runtime;
```

The provisioner role is not a superuser and is not the runtime login. The runtime
login owns tenant databases and performs their Alembic DDL. Keep the existing
Aurora master credential for controlled administration only. The runtime login
can access every tenant database; this is application routing isolation, not
per-tenant credential isolation.

For an existing deployment whose application currently connects as the Aurora
master, this is a credential cutover, not just a secret replacement. Before
rolling out the new task definitions, rehearse a maintenance-window ownership and
grant transition for the global database and every registered tenant database.
The runtime login must be able to read/write the existing application tables and
own objects that future migrations alter. Do not switch ECS to the new runtime
secret until that transition is verified; do not run ownership changes from this
application migration.

`CEDARS_SECRETS_MANAGER_ENDPOINT_URL` is an optional SDK endpoint override. Leave
it unset in AWS. The parity stack points it at LocalStack and bootstraps distinct
local-only PostgreSQL roles from `stack/postgres-init.sql`.

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

### Local startup failures

If the Compose `migrate` service fails with `operator does not exist: json = unknown`
and a statement such as `SELECT '{}'::json = '{}'`, baseline validation is comparing
PostgreSQL JSON server defaults. The migration runner compares those defaults as
`jsonb` so PostgreSQL can check equality. Rebuild the backend image after updating
the runner, then retry startup:

```sh
docker compose --file docker-compose.v2.yml up --build
```

An existing volume may then report `Refusing baseline adoption; schema differs
from frozen baseline`. Missing columns such as `projects.Investigator`,
`projects.database_secret_ref`, and `project_members.membership_revision` identify
an older shared-database schema, not a JSON-default mismatch. Rebuilding images
does not upgrade that schema or split its clinical data into tenant databases.
Do not stamp the new baseline over it or delete the volume to bypass validation.
Back up the database and retain the compatible application release until a
reviewed data-conversion procedure is available. If the data is disposable, use
a separate Compose project with fresh volumes for the new release; resetting
the existing volumes permanently deletes their contents.

## Verification limits

Tests exercise separate SQLite databases, frozen-baseline upgrades and roundtrips,
PostgreSQL offline DDL, failure redaction, tenant identity seeding, and partial
migration retries. Actual CREATE DATABASE privileges, PostgreSQL DDL execution,
Secrets Manager access, and production network reachability require PostgreSQL
integration and approved deployment verification. Unit tests do not establish
those permissions.