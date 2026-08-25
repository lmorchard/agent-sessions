# Event invalidation queue operations

The event queue lets one-shot drivers reconcile recent GitHub changes before a scheduled full scan.
Each hint causes new GitHub reads. Full scans recover missed or delayed events. Thus, GitHub remains
authoritative.

This guide describes how to prepare a deployment. It does not perform a deployment. The files in
[`examples/agent-session-events/`](../examples/agent-session-events/) are configuration templates.
They contain placeholders. Les must review and run all service-manager, Caddy, GitHub App, and
infrastructure changes.

## How the pieces fit

The queue uses several processes. Only the webhook receiver operates continuously. Systemd timers
start the pollers and the repository driver. These processes do one pass and then exit. Only the
repository driver selects work and invokes an agent.

```text
GitHub webhook ----> webhook receiver --+
                                          |
Projects timer ----> Projects poller -----+--> SQLite queue
                                          |         |
Reactions timer ---> reaction poller -----+         v
                                              repository driver ---> one agent phase
                                                     ^
                                                     |
                                           scheduled full scan
```

| Component | Runtime | Why it exists | Required? |
|---|---|---|---|
| repository driver | The existing timer starts one process for each repository. The process exits after one pass. | It claims hints and reads current GitHub data. It selects at most one issue and runs one agent phase. It also does scheduled full scans. | It is required for queue operation. Add `--events-config` to the existing driver invocation. This PR does not add a driver timer. |
| webhook receiver | One Uvicorn worker operates continuously on loopback. | It compares GitHub signatures and turns repository webhook deliveries into hints. | It is optional. It shortens response time for issue, pull-request, review, check, and status updates. |
| Projects poller | Its timer starts one pass. | It detects project membership, Status, and Priority changes. Repository webhooks do not report these changes. | It is optional for routing without a Projects V2 board. |
| reaction poller | Its timer starts one pass. | It reads active approval watches. Reactions have no useful repository webhook and do not reliably change the issue timestamp. | It is optional for workflows that never use comment reactions to unpark work. |
| Caddy or another edge proxy | It operates continuously. | It publishes only the webhook route. It keeps the receiver health routes private. | A public webhook endpoint requires an edge proxy. |

Queue entries are hints in every deployment shape. If you omit a producer, changes from that source
wait until a full scan. If the queue is unavailable, a configured driver uses a full scan. Thus,
GitHub remains authoritative.

## Choose a deployment shape

Choose the smallest shape that covers the changes you want to detect quickly:

| Shape | Run these components | Trade-off |
|---|---|---|
| legacy | This shape uses existing repository drivers without `--events-config`. | It has no queue or new services. Drivers retain their prior full-scan behavior. |
| webhook-driven | This shape uses the database, migration, queue-aware drivers, and webhook receiver. It also uses an edge proxy for a public endpoint. | Repository webhook events create prompt driver hints. Board-only and reaction-only changes wait for a full scan. |
| private polling | This shape uses the database, migration, queue-aware drivers, and required pollers. | It requires no public endpoint. Repository webhook changes wait for a full scan. |
| full | This shape uses all queue components and an edge proxy for a public endpoint. | It covers every event source in this PR. The examples use this shape. |

All queue-aware shapes use one local SQLite database. Put every queue process on the same host. Do
not put the database on network storage.

## Setup at a glance

The detailed sections define the credentials, permissions, and commands. Use this setup order:

1. Install a build that contains `agent-session-driver` and `agent-session-events`.
2. Choose a deployment shape.
3. Create the service identities for that shape.
4. Create the driver identity and the shared database group.
5. Copy `events.toml`.
6. Replace all placeholders in `events.toml`.
7. Add all managed repositories and boards to `events.toml`.
8. Create one private environment or secret file for each enabled component.
9. Keep the credentials for each component separate.
10. If you use webhooks, configure the GitHub App permissions and subscriptions.
11. If you use webhooks, configure the secret and public webhook URL.
12. Review and copy the applicable systemd units and Caddy configuration.
13. Keep the existing timer for each repository driver.
14. If you enable a poller, add its timer.
15. Stop every enabled queue process.
16. Run `migrate` as the driver identity.
17. Run `doctor` separately as each enabled identity.
18. For each `doctor` operation, load only the environment for that identity.
19. Inspect `queue-status`.
20. If you enable the receiver, start it.
21. Run each enabled poller once.
22. Enable the applicable poller timers.
23. Start the existing repository driver timers last.

Normal operation needs no manual queue command. Use `queue-status` to inspect the backlog and
clocks. Use `doctor` after a configuration or credential change. If the retained delivery history
uses too much disk space, run `prune`. This PR does not provide a pruning timer.

## Topology and boundaries

The example puts the receiver, pollers, drivers, and local SQLite database on one host. It assigns
one Unix identity to each credential boundary:

| Process | Unix user and primary group |
|---|---|
| webhook receiver | `agent-session-events-webhook` |
| Projects poller | `agent-session-events-projects` |
| reaction poller | `agent-session-events-reactions` |
| repository driver and migration owner | `agent-session-driver` |

Add only these four identities to the supplementary group `agent-session-events-db`. This group
gives access only to queue storage. It gives no access to the credential paths. Every example unit
declares `SupplementaryGroups=agent-session-events-db`. The systemd `ReadWritePaths` value does not
bypass Unix ownership or mode restrictions.

The receiver listens on loopback. Caddy publishes only `POST /github/webhook`. Keep `/healthz` and
`/readyz` private.

Each process receives only its required credential:

| Process | Credential source | Purpose |
|---|---|---|
| `serve` | `webhook.env` points to an owner-only webhook secret file. | The process compares delivery signatures. |
| `poll-projects` | `projects.env` supplies the credential for board reads. | The process reads the configured Projects V2 boards. |
| `poll-reactions` | `reactions-<instance>.env` supplies an installation read credential. | The process reads watched issue comments and reactions. |
| repository driver | The existing environment supplies credentials for each repository. | The environment preserves the repository, workspace, backend, model, and scoped access. |

The shared TOML contains no credentials, driver workspace, backend, model, or budget configuration.
The driver service names its repository checkout, state directory, workspace directory, and event
configuration. With `ProtectSystem=strict`, add all writable paths to `ReadWritePaths`. These paths
include the database, repository checkout, state, and workspace paths. The example uses
`/srv/agent-session-repositories/<repository-instance>` and
`/var/lib/agent-session-driver/<repository-instance>`. Replace these paths with the approved host
layout.

## Configuration, identities, and file permissions

Copy the structure of [`events.toml`](../examples/agent-session-events/events.toml). Replace each
`EXAMPLE_*` value and sentinel numeric ID. Get the numeric database ID for each repository from
`GET /repos/{owner}/{name}`. Do not derive this ID from the repository name. If installation-level
webhooks must map to the repository, add `installation_id` to its entry.

Get the installation ID from the GitHub App installation. The installation ID is different from
the repository ID.

Use [`permissions.toml`](../examples/agent-session-events/permissions.toml) as the path manifest for
review. Use the approved account procedure to create the four service users. Create one private
primary group for each user. Create the database group. Do not add a service user to the private
group of another service.

Prepare the paths with these exact boundaries:

- Set the owner of `/var/lib/agent-session-events` to
  `agent-session-driver:agent-session-events-db`.
- Set the mode of `/var/lib/agent-session-events` to `2770`. The set-group-ID bit gives new database,
  WAL, and shared-memory files the `agent-session-events-db` group.
- Run the migration as `agent-session-driver`. Activate `agent-session-events-db` and use umask
  `0007`.
- In a `2770` database directory, the migration creates or resets the database with mode `0660`.
- Configure each queue unit with `UMask=0007`.
- Make sure that the database, `-wal`, and `-shm` files have mode `0660`.
- Make sure that their group is `agent-session-events-db`. Their owner is the service user that
  created them.
- Set the owner of `/etc/agent-session-events` and `/etc/agent-session-driver` to `root:root`.
- Set the mode of these directories to `0755`. This mode exposes names but not file contents.
- Set the owner of each credential file to its service user and private primary group.
- Set the mode of each credential environment, secret, value file, and App private key to `0600`.
- Never use `agent-session-events-db` as the group for a credential file.
- Create each repository checkout, driver state directory, and workspace directory before you
  start its driver instance.
- Set the owner of these driver paths to `agent-session-driver:agent-session-driver`.
- Make sure that the explicit driver paths match its `ReadWritePaths` list.
- Keep the SQLite database, `-wal`, and `-shm` files on one local file system.
- Keep tokens, secrets, and private keys out of the shared TOML.

`doctor` accepts an owner-only database path. It also accepts a database path available through the
restricted group of the caller. A shared directory must use set-group-ID mode `2770`. Mode `0770`
fails because new SQLite files can inherit the wrong group. The command examines the ownership and
mode of existing `-wal` and `-shm` files.

`doctor` examines SQLite through a temporary snapshot. It never creates sidecar files next to the
source database. The webhook-secret probe uses stricter rules. The effective user of the receiver
must own the file with mode `0600`. The probe reads the value only to find an empty file. It never
prints the value.

## Credential inputs

Put the variables for only one service in each environment file. Set the owner to the applicable
service user and private primary group. Set the mode to `0600`. The database group must not have
read access. A literal token takes precedence over a command-backed token.

| Service environment and owner | Accepted variables |
|---|---|
| `webhook.env`, owned by `agent-session-events-webhook` | `AGENT_SESSION_WEBHOOK_SECRET_FILE` names the owner-only webhook secret file. Set its owner to `agent-session-events-webhook:agent-session-events-webhook` and its mode to `0600`. |
| `projects.env`, owned by `agent-session-events-projects` | `DRIVER_GH_BOARD_TOKEN` contains the board token. Alternatively, `DRIVER_GH_BOARD_TOKEN_CMD` contains a command that prints the token. |
| `reactions-<credential-instance>.env`, owned by `agent-session-events-reactions` | `AGENT_GH_READ_TOKEN` contains the repository-read token. Alternatively, `AGENT_GH_READ_TOKEN_CMD` contains a command that prints the token. You can also supply the complete `DRIVER_GH_APP_ID`, `DRIVER_GH_APP_INSTALLATION_ID`, and `DRIVER_GH_APP_PRIVATE_KEY_FILE` tuple. The compatibility names `GH_APP_ID`, `GH_APP_INSTALLATION_ID`, and `GH_APP_PRIVATE_KEY_FILE` form another complete tuple. Set the private-key owner to `agent-session-events-reactions:agent-session-events-reactions` and its mode to `0600`. |
| `/etc/agent-session-driver/<repository-instance>.env`, owned by `agent-session-driver` | Keep the existing credential and runtime variables for each repository driver. The event `doctor` reads only its scoped read and board inputs. |

The service splits a `*_CMD` value into arguments. It invokes the command directly without a shell.
Do not use pipes, redirection, or shell expansion. The command must write only the token to standard
output. Give access to the underlying secret store only to that service user. Do not give access
through `agent-session-events-db`.

Set `DRIVER_GH_LOGIN` to the GitHub login of the automation account. Set `DRIVER_BOT_LOGINS` to a
comma-separated list of other machine accounts. Comments from these accounts do not count as human
approval. The software automatically classifies built-in bot names as machines.

The `%i` in `agent-session-reactions@.service` selects a credential environment. It does not select
a repository. One reaction pass reads every repository in the shared TOML. Thus, each selected
token or App installation must read every repository in the configuration.

Name each instance after its credential set or account, such as `primary`. Schedule one instance
for each credential set. A shared configuration cannot use `%i` to divide repositories between
tokens.

Run `doctor` four times. Use one service identity for each operation. Activate the declared
supplementary database group. Use the approved environment mechanism for that service. Do not
combine secrets:

- As `agent-session-events-webhook`, load only `webhook.env`. The webhook-secret probe must pass.
  The repository and board credential probes will skip.
- As `agent-session-events-projects`, load only `projects.env`. The board and field probes must
  pass. The webhook-secret and repository credential probes will skip.
- As `agent-session-events-reactions`, load only one `reactions-<credential-instance>.env`.
  The repository identity and read probes must pass. The webhook-secret and board probes will skip.
- As `agent-session-driver`, load only the driver environment for the repository instance. The
  database and configured read probes must pass. Absent webhook or board inputs will skip.

Each operation repeats the configuration, ownership, SQLite, schema, and queue-clock probes. Accept
only the expected out-of-scope skips. A failed database-path probe identifies an incorrect owner,
mode, or supplementary-group assignment. It identifies the error before the service starts.

`doctor` reads GitHub and SQLite state but does not change that state. For each readable repository,
it finds one commit. Then it does check-run and combined-status reads. An empty repository skips
these two capability probes. A denied or malformed read fails without GitHub response output.

## GitHub configuration

Subscribe the GitHub App to these events:

- `issues` and `issue_comment`
- `pull_request`, `pull_request_review`, `pull_request_review_comment`, and
  `pull_request_review_thread`
- `check_run`, `check_suite`, and `status`
- `ping`, `meta`, `installation`, `installation_repositories`, and `installation_target`

The App-minted installation token requests this exact read set: Checks, Contents, Discussions,
Issues, Pull requests, and Commit statuses. Grant the App all six permissions. Do not grant the
Actions permission. This queue does not subscribe to workflow events. Changes to App permissions
or subscriptions require a separate deployment review.

Installation, installation-repository, installation-target, ping, and meta deliveries can omit a
top-level repository. The receiver retains these verified deliveries. It creates installation
hints only for repositories that use the applicable installation ID. An explicit affected-repository
list must also name each repository. Ping and meta deliveries retain safe diagnostics but create no
targets. A control-plane payload never makes an unconfigured repository dirty.

User-owned Projects V2 boards use the separate board credential. Add that identity to the
collaborator list of each private project. Grant project read access to the identity. Repository
access does not give project access.

## Fresh installation

Before this sequence, prepare the users, groups, TOML, credential files, webhook secret, database
directory, and approved service files. Set the database-directory mode to `2770`. Keep every queue
service stopped during the exclusive SQLite migration transaction.

1. Stop the receiver, Projects poller, reaction pollers, and repository drivers through the
   approved service procedure for the host. Make sure that no process has the database open.
2. Enter the approved migration runner as `agent-session-driver`. Activate
   `agent-session-events-db`. Set umask `0007`. Then apply each schema migration:

   ```sh
   umask 0007
   agent-session-events migrate --config /etc/agent-session-events/events.toml
   ```

   Expected result: The command lists the applied migration versions or reports `already current`.
   The database owner is `agent-session-driver:agent-session-events-db`, and its mode is `0660`. A
   nonzero exit keeps the services stopped for investigation.
3. Run the four read-only diagnostics with the identities and separate environments in Credential
   inputs. Use this command for each operation:

   ```sh
   agent-session-events doctor --config /etc/agent-session-events/events.toml
   ```

   Expected result: The probes print `pass`, `warn`, or an expected `skip`. No probe prints `fail`.
   A warning about a missing success clock is normal before the first pass. This warning is not a
   success result. Resolve each unexpected skip for the service layer that you plan to start.
4. Inspect the empty or restored queue:

   ```sh
   agent-session-events queue-status --config /etc/agent-session-events/events.toml
   ```

   Expected result: The command prints backlog, leases, backoff, clocks, watches, schema, and recent
   errors. New clocks show `never` or `unknown`.
5. Start the receiver manually with the approved service manager. Run each poller once. Then start
   its timer. Start the repository driver timers last.

   After each layer, run `doctor` again. Then run `queue-status` again. This order isolates an error
   to one layer.

## Upgrade

Stop the receiver, pollers, and drivers before an upgrade. Make sure that no queue process operates.
Use the approved procedure to back up the database, `-wal`, and `-shm` files as one set. Record the
application version with the backup.

Use the commands from the fresh installation procedure. Run `migrate`. Then run `doctor`. Then run
`queue-status`.

If `doctor` reports no failures, restart the receiver. Restart each one-shot poller. Restart each
poller timer. Restart the drivers last.

The migration uses an exclusive transaction. Never run the migration while a receiver, poller, or
driver operates. The current migration adds durable full-scan errors. It keeps the last successful
scan clock until a later successful scan clears the error.

## Readiness and degraded drivers

`GET /healthz` shows only that the loopback receiver process is alive. A ready response from
`GET /readyz` means that the code can access the database. The database schema must also match the
operating code. The Caddy example does not publish either endpoint.

Receivers and pollers require durable queue storage. An unavailable, busy, corrupt, or incompatible
database makes receiver readiness fail. It also makes a one-shot poller exit nonzero. The poller
does not replace its last complete observation.

Drivers degrade differently. If an optional events configuration is absent, the driver follows its
legacy full-scan path. If a configured database becomes unavailable or incompatible, the driver
logs degraded mode. Then it does the same full scan. This fallback preserves correctness but makes
selection slower.

## Timers and exit codes

The Projects and reaction commands perform one pass and exit. Their systemd services use
`Type=oneshot`. Their timers alone control the schedule.

A zero exit means that the pass completed. It can also mean that another live source lease owned
that pass. A nonzero exit means that the source failed. The prior snapshot or reaction observation
remains authoritative.

The repository driver also performs one pass. Its existing timer controls the schedule for each
repository. The event configuration does not control the repository, workspace, backend, model, or
budget schedule. The webhook receiver is the only long-lived queue process. It uses exactly one
Uvicorn worker.

## Reading queue status

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

An active lease names its owner and expiry time. It usually means that another one-shot process owns
the work. An expired lease is recoverable.

Backoff means that a target has a temporary error and waits for its next attempt. A new generation
clears that backoff. `recent-errors` combines target, poller, and full-scan errors for diagnosis.
Each repository entry also shows its latest scan error. A successful scan clears that repository
error. Read the matching structured event in journald.

Treat `never`, `unknown`, and JSON `null` as missing evidence. These values do not identify a
successful webhook, poll, or full scan.

## Pruning and WAL checkpoints

Before pruning, make sure that `queue-status` shows the expected database and retention
configuration:

```sh
agent-session-events prune --config /etc/agent-session-events/events.toml
```

Expected result: The command reports how many delivery and invalidation history rows it removed.
Then it does a passive WAL checkpoint. This checkpoint does not force active readers to exit.

Optional `--deliveries-days` and `--invalidations-days` overrides must be positive integers. Zero
and negative values are usage errors. These values do not select the configuration values, and they
do not prune future data.

Pruning removes only expired raw webhook deliveries and immutable invalidation history. It does not
remove dirty targets, project snapshots, approval watches, poller state, or repository scan state.
A full scan never removes dirty rows in bulk. GitHub does not provide an atomic snapshot.

## Recovery

Before you copy, replace, or inspect database files, stop all queue processes.

| Symptom | Safe response |
|---|---|
| unavailable database | Make sure that the path, directory owner, file owner, and local file system are correct. If the file is missing, restore the complete backup set. |
| busy database | Find the process that holds a long transaction. Wait for that process, or stop it. Do not remove WAL files or lock artifacts. Run `doctor` again. |
| incompatible schema | Keep the services stopped. Back up the database set. Run `migrate` from the matching binary. Then run `doctor` again. Never change schema metadata by hand. |
| corrupt database | Keep a copy of the database, WAL, and shared-memory files for diagnosis. Restore a verified backup, or rebuild from GitHub with a reviewed procedure. |

`doctor` detects these states but does not repair them automatically. GitHub full scans remain
authoritative after recovery. Age-based pruning and full scans do not remove dirty rows. The driver
removes each dirty row after it processes and acknowledges the applicable generation.

## Review boundary

This PR did not install, enable, start, or reload the example units or Caddyfile. It did not change
GitHub App configuration. These files are inputs for review by Les. They are not deployment
instructions.
