# Event invalidation queue operations

The optional event queue gives repository drivers recent GitHub changes before a scheduled full scan.
Each hint causes new GitHub reads. Full scans recover missed or delayed events. GitHub remains authoritative.

## Why two services remain

The deployment has two services because it has two jobs and credential boundaries. The long-lived
event daemon receives webhooks and polls GitHub for Projects and reaction changes. It writes local
queue hints. It never starts an agent or writes to GitHub.

The repository driver runs one pass for one repository. It reads current GitHub state, claims hints,
and can use its private mutation credentials after an agent records requested writes. Its existing
timer controls this cadence.

```text
GitHub webhooks ----+                     +--> SQLite queue --> repository driver --> one agent phase
Projects poll loop -+--> event daemon ----+
Reaction poll loop -+
```

The event daemon and repository drivers share one system read credential. The driver alone has
repository-write and Project-mutation credentials. This boundary keeps GitHub reads in one protected
file while keeping mutations private to the driver.

This guide describes deployment preparation and operation. It does not perform a deployment. The
files in [`examples/agent-session-events/`](../examples/agent-session-events/) contain placeholders only.

Before you apply changes, review the service-manager, Caddy, GitHub, and infrastructure changes.

## Components and setup

| Component | Runtime | Purpose |
|---|---|---|
| event daemon | One long-lived `agent-session-events serve` process. | It accepts webhook deliveries and runs the Projects and reaction poll loops. |
| repository driver | One timer-owned `agent-session-driver` process for each repository. | It reconciles fresh GitHub state, runs at most one agent phase, and performs full scans. |
| Caddy or another edge proxy | One long-lived proxy process. | It publishes only `POST /github/webhook`. |

Drivers omit `--events-config` in full-scan mode. Queue mode uses the shared event
configuration and event daemon.

For public GitHub webhooks, add an edge proxy.

All queue-aware components use one local SQLite database on one host. If you omit webhooks, Projects
boards, or reaction watches, the daemon continues with the remaining inputs. Changes from an omitted
input wait for a full scan.

Do not put the database on network storage.

1. Install a build that contains `agent-session-driver` and `agent-session-events`.
2. Create the event identity, driver identity, database group, and readers group.
3. Copy the example configuration and service files into the approved host layout.
4. Replace every `EXAMPLE_*` value and sentinel ID in `events.toml`.
5. Create the shared read environment, webhook secret, and private driver environment.
6. Add the shared read environment and private driver environment to each driver instance.
7. If GitHub sends webhooks, register the endpoint, secret, JSON content type, and events with the
   approved procedure.
8. Keep every queue process stopped during migration.
9. Run `migrate`, `doctor`, and `queue-status` before service startup.
10. Start the event daemon before existing repository driver timers.

Use `queue-status` for queue state. Use `doctor` after a configuration or credential change. Use
`prune` after retained queue history uses too much disk.

## Configuration and file permissions

Copy [`events.toml`](../examples/agent-session-events/events.toml). Replace each placeholder. Get a repository ID
from `GET /repos/{owner}/{name}`. Do not derive an ID from a repository name. If installation
deliveries need repository mapping, add `installation_id` to the repository entry.

The `[polling]` table controls the two daemon loops. Both values must be positive seconds:

```toml
[polling]
projects_interval_seconds = 60
reactions_interval_seconds = 60
```

The daemon starts each loop immediately. A loop waits for its pass to finish before it waits for
the next interval. A normal poll error records an error and retries after the interval. It does not
stop webhook ingestion or make the daemon unready.

Use [`permissions.toml`](../examples/agent-session-events/permissions.toml) as the reviewed path manifest. The
example uses these identities and groups:

| Identity or group | Access |
|---|---|
| `agent-session-events` | Runs the event daemon and owns the webhook secret. |
| `agent-session-driver` | Runs repository driver instances and owns each private driver environment. |
| `agent-session-events-db` | Gives both services access only to the local queue database. |
| `agent-session-readers` | Gives both services read access to the shared read environment. |

Set `/var/lib/agent-session-events` to `agent-session-driver:agent-session-events-db` with mode
`2770`. Run migration as `agent-session-driver` with `agent-session-events-db` active and umask
`0007`. The database, `-wal`, and `-shm` files use mode `0660` and group
`agent-session-events-db`.

Set `/etc/agent-session/read.env` to `root:agent-session-readers` with mode `0640`. This file
contains only one of these variables:

```text
AGENT_GH_READ_TOKEN=<read-only-token>
AGENT_GH_READ_TOKEN_CMD=<command-that-prints-one-read-only-token>
```

The daemon runs `AGENT_GH_READ_TOKEN_CMD` only at startup.

Use a long-lived, genuinely read-only PAT. Use this command only to retrieve that PAT. Do not mint
an expiring App token.

For public repositories and a user-owned Projects V2 board, use a classic PAT with
`read:project`. Project reads use GraphQL directly and do not require `read:org`. A fine-grained PAT
cannot read a project owned by another account, even when that account grants repository access.

Use one form, not both. A `*_CMD` value contains direct command arguments. Do not use pipes,
redirection, or shell expansion. The command writes only the token to standard output.

Make sure that the PAT can read every configured repository and Projects V2 board. For private
repositories or boards, grant that access to the token owner.

Set `/etc/agent-session-events/webhook.secret` to `agent-session-events:agent-session-events` with
mode `0600`. The event service receives this path through
`AGENT_SESSION_WEBHOOK_SECRET_FILE` in its unit.

Set each
`/etc/agent-session-driver/<repository-instance>.env` file to
`agent-session-driver:agent-session-driver` with mode `0600`.

The private driver file holds repository, workspace, runtime, and mutation values. It can include
`DRIVER_GH_WRITE_TOKEN` or `DRIVER_GH_WRITE_TOKEN_CMD`, plus `DRIVER_GH_BOARD_TOKEN` or
`DRIVER_GH_BOARD_TOKEN_CMD` for driver Project changes.

Do not put `AGENT_GH_READ_TOKEN` or `AGENT_GH_READ_TOKEN_CMD` in this file.

The `agent-session-events.service` unit loads `/etc/agent-session/read.env` and declares the
webhook-secret path. The `agent-session-driver@.service` unit loads `/etc/agent-session/read.env`
first and `/etc/agent-session-driver/%i.env` second. Both units join `agent-session-events-db` and
`agent-session-readers`. The driver remains `Type=oneshot`.

The example Caddyfile routes only `/github/webhook` to `127.0.0.1:8080`. It does not publish
`/healthz` or `/readyz`.

## GitHub inputs

Set the webhook content type to `application/json` in the GitHub user interface. If you use the
API, set `content_type` to `json`. Do not select `application/x-www-form-urlencoded`.

That format sends JSON in a form field, which this receiver does not decode.

Set the webhook endpoint to the public URL that maps to `POST /github/webhook`. Set the same secret
that the event daemon reads from `AGENT_SESSION_WEBHOOK_SECRET_FILE`. After you save the webhook,
make sure that the ping delivery returns HTTP 202 from the raw-JSON receiver.

Configure the webhook endpoint for these events:

- `issues` and `issue_comment`
- `pull_request`, `pull_request_review`, `pull_request_review_comment`, and `pull_request_review_thread`
- `check_run`, `check_suite`, and `status`
- `ping`, `meta`, `installation`, `installation_repositories`, and `installation_target`

Projects and reactions have no usable webhook input for this queue. The daemon polls configured
Projects V2 boards and active approval watches with the shared read credential.

## Migration, status, and recovery

If the host used the preview topology, stop these retired units through the approved host procedure:

- `agent-session-events-webhook.service`
- `agent-session-projects.service`
- `agent-session-projects.timer`
- `agent-session-reactions@.service`
- `agent-session-reactions@.timer`

Before you start the combined event service, disable those retired units through the approved host
procedure.

Before migration, stop the event daemon and repository drivers through the approved host procedure.
Make sure that no process has the database open. Back up the database, `-wal`, and `-shm` files as
one set.

Run migration as `agent-session-driver` with the database group active:

```sh
umask 0007
agent-session-events migrate --config /etc/agent-session-events/events.toml
```

Expected result: the command lists applied migration versions or reports `already current`. A
nonzero exit keeps services stopped for diagnosis.

Run the read-only diagnosis with the event identity and both required inputs.

Then run the diagnosis with the driver identity and its private instance input:

```sh
agent-session-events doctor --config /etc/agent-session-events/events.toml
```

Expected result: the command prints `pass`, `warn`, or an expected `skip`. No probe prints `fail`.
A missing success clock warns before the first daemon pass. This warning does not mean success.

Inspect the empty or restored queue:

```sh
agent-session-events queue-status --config /etc/agent-session-events/events.toml
```

Expected result: the command prints backlog, leases, backoff, clocks, watches, schema, and recent
errors. New clocks show `never` or `unknown`.

Start the event daemon through the approved host procedure.

Then start existing repository driver timers.

The daemon owns polling cadence.

Use the one-pass commands only for diagnosis:

```sh
agent-session-events poll-projects --config /etc/agent-session-events/events.toml
agent-session-events poll-reactions --config /etc/agent-session-events/events.toml
```

Each command exits nonzero after a failed pass and preserves its prior observation. These commands
do not replace the daemon polling loops.

`GET /healthz` means that the daemon process is alive. `GET /readyz` also requires accessible,
compatible queue storage and running background tasks. The Caddy example keeps both routes private.

A normal poll error does not make `/readyz` fail. An unexpected poll-task exit does make it fail.
During shutdown, the daemon stops new passes and waits for bounded in-flight GitHub reads.

Human output gives a compact status summary:

```text
backlog=3 oldest-age=42s leases=1 backoff=1 latest-delivery=<timestamp> latest-delivery-age=8s watches=2 schema=<schema-version>
repository=9000000000000000000 last-hint=<timestamp> scan-started=<timestamp> scan-success=<timestamp> scan-success-age=120s scan-lease=none scan-lease-until=never last-error=none
poller=projects:EXAMPLE_OWNER/1 last-success=<timestamp> last-success-age=15s lease=none lease-until=never last-error=none
recent-errors=none
```

Use JSON for monitoring or local tooling:

```sh
agent-session-events queue-status --json --config /etc/agent-session-events/events.toml
```

These representative fields show unknown values as JSON `null`:

```json
{
  "backed_off_count": 1,
  "backlog_count": 3,
  "latest_delivery_at": "<RFC3339 timestamp or null>",
  "latest_delivery_age_seconds": 8,
  "leased_count": 1,
  "recent_errors": [],
  "watch_count": 2
}
```

Before pruning, make sure that `queue-status` shows the expected database and retention configuration:

```sh
agent-session-events prune --config /etc/agent-session-events/events.toml
```

Expected result: the command reports removed delivery and invalidation history rows. Then it performs
a passive WAL checkpoint. This checkpoint does not force active readers to exit.

Before you copy, replace, or inspect database files, stop the event daemon and repository drivers.

| Symptom | Safe response |
|---|---|
| unavailable database | Make sure that the path, owners, modes, and local file system are correct. If the file is missing, restore the complete backup set. |
| busy database | Find the process with a long transaction. If the transaction can finish, wait for it. If the transaction is stuck, stop the process. Do not remove WAL files or lock artifacts. Run `doctor` again. |
| incompatible schema | Keep services stopped. Back up the database set. Run `migrate` from the matching binary. Then run `doctor` again. Never change schema metadata by hand. |
| corrupt database | Keep a database, WAL, and shared-memory copy for diagnosis. If a verified backup is available, restore it. If no verified backup is available, use a reviewed procedure to rebuild from GitHub. |

`doctor` detects these states but does not repair them. Full scans remain authoritative after
recovery. The driver removes a dirty row only after it processes and acknowledges that generation.

## Review boundary

This repository does not install, enable, start, or reload these example units or the Caddyfile.
It does not change GitHub configuration. The examples are review inputs, not deployment commands.
