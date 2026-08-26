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
    parser = CasePreservingConfigParser(interpolation=None, strict=False)
    with (EXAMPLES / name).open(encoding="utf-8") as handle:
        parser.read_file(handle)
    return parser


def _exec_start(unit: configparser.ConfigParser) -> list[str]:
    return shlex.split(unit["Service"]["ExecStart"])


def _environment_files(name: str) -> list[str]:
    return [
        line.partition("=")[2]
        for line in (EXAMPLES / name).read_text(encoding="utf-8").splitlines()
        if line.startswith("EnvironmentFile=")
    ]


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
    assert raw["polling"] == {
        "projects_interval_seconds": 60,
        "reactions_interval_seconds": 60,
    }
    assert not {
        key
        for key in raw
        if any(word in key.lower() for word in ("token", "secret", "private", "credential"))
    }


def test_event_service_runs_the_loopback_receiver_and_pollers() -> None:
    unit = _unit("agent-session-events.service")
    command = _exec_start(unit)

    assert unit["Service"]["Type"] == "simple"
    assert (unit["Service"]["User"], unit["Service"]["Group"]) == (
        "agent-session-events",
        "agent-session-events",
    )
    assert unit["Service"]["SupplementaryGroups"] == (
        "agent-session-events-db agent-session-readers"
    )
    assert command == [
        "/usr/local/bin/agent-session-events",
        "serve",
        "--config",
        "/etc/agent-session-events/events.toml",
    ]
    assert "--workers" not in command
    assert _environment_files("agent-session-events.service") == [
        "/etc/agent-session/read.env"
    ]
    assert unit["Service"]["Environment"] == (
        "AGENT_SESSION_WEBHOOK_SECRET_FILE=/etc/agent-session-events/webhook.secret"
    )


def test_examples_have_no_separate_poller_units_or_timers() -> None:
    obsolete = {
        "agent-session-events-webhook.service",
        "agent-session-projects.service",
        "agent-session-projects.timer",
        "agent-session-reactions@.service",
        "agent-session-reactions@.timer",
    }
    assert not obsolete & {path.name for path in EXAMPLES.iterdir()}


def test_permission_manifest_defines_shared_read_and_private_write_boundaries() -> None:
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
    assert entries["read-environment-directory"] == {
        "role": "read-environment-directory",
        "path": "/etc/agent-session",
        "owner": "root",
        "group": "root",
        "mode": "0755",
    }
    assert entries["read-environment"] == {
        "role": "read-environment",
        "path": "/etc/agent-session/read.env",
        "owner": "root",
        "group": "agent-session-readers",
        "mode": "0640",
    }
    for role, owner in {
        "webhook-secret": "agent-session-events",
        "driver-environment": "agent-session-driver",
    }.items():
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
    assert unit["Service"]["SupplementaryGroups"] == (
        "agent-session-events-db agent-session-readers"
    )
    assert _environment_files("agent-session-driver@.service") == [
        "/etc/agent-session/read.env",
        "/etc/agent-session-driver/%i.env",
    ]
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
