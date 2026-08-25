from __future__ import annotations

import configparser
import shlex
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from agent_sessions.events import config

ROOT = Path(__file__).parents[2]
EXAMPLES = ROOT / "examples" / "agent-session-events"


class CasePreservingConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def _unit(name: str) -> configparser.ConfigParser:
    parser = CasePreservingConfigParser(interpolation=None)
    with (EXAMPLES / name).open(encoding="utf-8") as handle:
        parser.read_file(handle)
    return parser


def _exec_start(unit: configparser.ConfigParser) -> list[str]:
    return shlex.split(unit["Service"]["ExecStart"])


@dataclass
class CaddyBlock:
    header: tuple[str, ...]
    directives: list[tuple[str, ...]] = field(default_factory=list)
    children: list["CaddyBlock"] = field(default_factory=list)


def _caddy_tree(path: Path) -> CaddyBlock:
    root = CaddyBlock(())
    stack = [root]
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        tokens = tuple(shlex.split(raw_line, comments=True))
        if not tokens:
            continue
        if tokens == ("}",):
            if len(stack) == 1:
                raise AssertionError("unmatched Caddy closing brace")
            stack.pop()
        elif tokens[-1] == "{":
            block = CaddyBlock(tokens[:-1])
            stack[-1].children.append(block)
            stack.append(block)
        else:
            stack[-1].directives.append(tokens)
    if len(stack) != 1:
        raise AssertionError("unclosed Caddy block")
    return root


def test_example_toml_is_strict_valid_and_contains_only_placeholders() -> None:
    path = EXAMPLES / "events.toml"
    raw = tomllib.loads(path.read_text(encoding="utf-8"))

    loaded = config.load(path)

    assert loaded.database == Path("/var/lib/agent-session-events/events.sqlite3")
    assert [(item.identity.id, item.identity.owner, item.identity.name) for item in loaded.repositories] == [
        (9_000_000_000_000_000_000, "EXAMPLE_OWNER", "EXAMPLE_REPOSITORY")
    ]
    assert loaded.boards[0].repository_ids == (9_000_000_000_000_000_000,)
    assert not {
        key
        for key in raw
        if any(word in key.lower() for word in ("token", "secret", "private", "credential"))
    }


def test_webhook_service_runs_the_loopback_receiver_with_one_worker() -> None:
    unit = _unit("agent-session-events-webhook.service")
    command = _exec_start(unit)

    assert unit["Service"]["Type"] == "simple"
    assert command == [
        "/usr/local/bin/agent-session-events",
        "serve",
        "--config",
        "/etc/agent-session-events/events.toml",
    ]
    assert "--workers" not in command
    assert unit["Service"]["EnvironmentFile"] == "/etc/agent-session-events/webhook.env"


def test_pollers_are_one_shot_and_timers_own_their_cadence() -> None:
    projects = _unit("agent-session-projects.service")
    reactions = _unit("agent-session-reactions@.service")
    projects_timer = _unit("agent-session-projects.timer")
    reactions_timer = _unit("agent-session-reactions@.timer")

    assert projects["Service"]["Type"] == "oneshot"
    assert reactions["Service"]["Type"] == "oneshot"
    assert _exec_start(projects)[1:] == [
        "poll-projects",
        "--config",
        "/etc/agent-session-events/events.toml",
    ]
    assert _exec_start(reactions)[1:] == [
        "poll-reactions",
        "--config",
        "/etc/agent-session-events/events.toml",
    ]
    assert "Restart" not in projects["Service"]
    assert "Restart" not in reactions["Service"]
    assert projects_timer["Timer"]["Unit"] == "agent-session-projects.service"
    assert reactions_timer["Timer"]["Unit"] == "agent-session-reactions@%i.service"
    assert "OnCalendar" in projects_timer["Timer"]
    assert "OnCalendar" in reactions_timer["Timer"]


def test_services_load_only_their_scoped_environment_file() -> None:
    expected = {
        "agent-session-events-webhook.service": "/etc/agent-session-events/webhook.env",
        "agent-session-projects.service": "/etc/agent-session-events/projects.env",
        "agent-session-reactions@.service": "/etc/agent-session-events/reactions-%i.env",
        "agent-session-driver@.service": "/etc/agent-session-driver/%i.env",
    }

    for name, environment_file in expected.items():
        service = _unit(name)["Service"]
        assert service["EnvironmentFile"] == environment_file
        assert all(key == "EnvironmentFile" for key in service if key.startswith("EnvironmentFile"))


def test_services_use_distinct_identities_and_only_share_the_database_group() -> None:
    identities = {
        "agent-session-events-webhook.service": (
            "agent-session-events-webhook",
            "agent-session-events-webhook",
        ),
        "agent-session-projects.service": (
            "agent-session-events-projects",
            "agent-session-events-projects",
        ),
        "agent-session-reactions@.service": (
            "agent-session-events-reactions",
            "agent-session-events-reactions",
        ),
        "agent-session-driver@.service": (
            "agent-session-driver",
            "agent-session-driver",
        ),
    }

    assert len({user for user, _ in identities.values()}) == len(identities)
    for name, identity in identities.items():
        service = _unit(name)["Service"]
        assert (service["User"], service["Group"]) == identity
        assert service["SupplementaryGroups"] == "agent-session-events-db"
        assert service["UMask"] == "0007"
        assert "/var/lib/agent-session-events" in shlex.split(
            service["ReadWritePaths"]
        )


def test_permission_manifest_limits_the_shared_group_to_database_paths() -> None:
    raw = tomllib.loads(
        (EXAMPLES / "permissions.toml").read_text(encoding="utf-8")
    )
    entries = {item["role"]: item for item in raw["paths"]}

    assert entries["database-directory"] == {
        "role": "database-directory",
        "path": "/var/lib/agent-session-events",
        "owner": "agent-session-driver",
        "group": "agent-session-events-db",
        "mode": "2770",
    }
    assert entries["database-file"] == {
        "role": "database-file",
        "path": "/var/lib/agent-session-events/events.sqlite3",
        "owner": "agent-session-driver",
        "group": "agent-session-events-db",
        "mode": "0660",
    }
    credential_owners = {
        "webhook-environment": "agent-session-events-webhook",
        "webhook-secret": "agent-session-events-webhook",
        "projects-environment": "agent-session-events-projects",
        "reactions-environment": "agent-session-events-reactions",
        "reactions-app-key": "agent-session-events-reactions",
        "driver-environment": "agent-session-driver",
    }
    for role, owner in credential_owners.items():
        item = entries[role]
        assert item["owner"] == owner
        assert item["group"] == owner
        assert int(item["mode"], 8) == 0o600
        assert int(item["mode"], 8) & 0o070 == 0
        assert item["group"] != "agent-session-events-db"


def test_driver_service_adds_events_config_to_existing_instance_configuration() -> None:
    unit = _unit("agent-session-driver@.service")
    command = _exec_start(unit)

    assert unit["Service"]["Type"] == "oneshot"
    assert command == [
        "/usr/local/bin/agent-session-driver",
        "--repo-path",
        "/srv/agent-session-repositories/%i",
        "--state-dir",
        "/var/lib/agent-session-driver/%i",
        "--workspaces-dir",
        "/var/lib/agent-session-driver/%i/workspaces",
        "--events-config",
        "/etc/agent-session-events/events.toml",
    ]
    assert unit["Service"]["EnvironmentFile"] == "/etc/agent-session-driver/%i.env"
    assert set(shlex.split(unit["Service"]["ReadWritePaths"])) == {
        "/var/lib/agent-session-events",
        "/srv/agent-session-repositories/%i",
        "/var/lib/agent-session-driver/%i",
        "/var/lib/agent-session-driver/%i/workspaces",
    }


def test_caddy_exposes_only_the_github_webhook_route() -> None:
    root = _caddy_tree(EXAMPLES / "Caddyfile")

    assert len(root.children) == 1
    site = root.children[0]
    assert site.header == ("https://events.invalid",)
    assert ("@github_webhook", "path", "/github/webhook") in site.directives
    assert [block.header for block in site.children] == [
        ("handle", "@github_webhook"),
        ("handle",),
    ]
    assert site.children[0].directives == [
        ("reverse_proxy", "127.0.0.1:8080")
    ]
    assert site.children[1].directives == [("respond", "404")]
    routed_paths = {
        token
        for directive in site.directives
        for token in directive
        if token.startswith("/")
    }
    assert routed_paths == {"/github/webhook"}


def test_examples_contain_no_secret_literals_or_deployment_invocations() -> None:
    forbidden_commands = {
        "caddy reload",
        "docker",
        "kubectl",
        "sudo",
        "systemctl",
        "terraform",
    }
    forbidden_secret_markers = {
        "-----BEGIN PRIVATE KEY-----",
        "github_pat_",
        "ghp_",
        "gho_",
        "ghs_",
    }

    for path in EXAMPLES.iterdir():
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        assert not any(command in lowered for command in forbidden_commands)
        assert not any(marker.lower() in lowered for marker in forbidden_secret_markers)
