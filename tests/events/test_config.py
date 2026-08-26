from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_sessions.events import config
from agent_sessions.events.models import PollingPolicy


def write_config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


VALID = '''
database = "/var/lib/agent-session/events.sqlite3"
busy_timeout_ms = 3000
claim_limit = 25
claim_lease_seconds = 300
retry_base_seconds = 30
retry_max_seconds = 1800
max_body_bytes = 1048576
delivery_retention_days = 14
invalidation_retention_days = 30

[scan]
quiet_period_seconds = 300
interval_seconds = 900
maximum_age_seconds = 3600

[polling]
projects_interval_seconds = 60
reactions_interval_seconds = 60

[[repositories]]
id = 123456
owner = "lmorchard"
name = "agent-sessions"
installation_id = 7890

[[boards]]
owner = "lmorchard"
number = 9
repository_ids = [123456]
'''

REPOSITORY_TABLE = '''[[repositories]]
id = 123456
owner = "lmorchard"
name = "agent-sessions"
installation_id = 7890

'''
BOARD_TABLE = '''[[boards]]
owner = "lmorchard"
number = 9
repository_ids = [123456]
'''


def test_loads_the_shared_events_configuration(tmp_path: Path) -> None:
    loaded = config.load(write_config(tmp_path / "events.toml", VALID))
    assert loaded.database == Path("/var/lib/agent-session/events.sqlite3")
    assert loaded.repositories[0].identity.id == 123456
    assert loaded.boards[0].key == "lmorchard/9"
    assert loaded.scan.maximum_age.total_seconds() == 3600
    assert loaded.polling == PollingPolicy(
        projects_interval=timedelta(seconds=60),
        reactions_interval=timedelta(seconds=60),
    )


@pytest.mark.parametrize(("owner", "name"), [("owner_name", "agent.sessions"), ("owner name", "repo@name"), ("@owner", "repo:branch")])
def test_accepts_every_nonempty_component_the_lifecycle_parser_accepts(tmp_path: Path, owner: str, name: str) -> None:
    text = VALID.replace('owner = "lmorchard"', f'owner = "{owner}"', 1).replace('name = "agent-sessions"', f'name = "{name}"')
    loaded = config.load(write_config(tmp_path / "events.toml", text))
    assert loaded.repositories[0].identity.owner == owner
    assert loaded.repositories[0].identity.name == name


@pytest.mark.parametrize("component", ["", ".", "..", "owner/name"])
def test_rejects_components_the_lifecycle_parser_rejects(tmp_path: Path, component: str) -> None:
    text = VALID.replace('owner = "lmorchard"', f'owner = "{component}"', 1)
    with pytest.raises(ValueError, match="owner"):
        config.load(write_config(tmp_path / "events.toml", text))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("unknown = true\n", "unknown"),
        ("database = \"relative.sqlite\"", "absolute"),
        ("claim_limit = 0", "positive"),
        ("maximum_age_seconds = 10", "maximum_age_seconds"),
    ],
)
def test_rejects_invalid_values(tmp_path: Path, change: str, message: str) -> None:
    text = VALID
    if change.startswith("unknown"):
        text += change
    elif change.startswith("maximum"):
        text = text.replace("maximum_age_seconds = 3600", change)
    elif change.startswith("owner"):
        text = text.replace('owner = "lmorchard"', change, 1)
    else:
        key = change.split(" = ")[0]
        text = text.replace(next(line for line in VALID.splitlines() if line.startswith(key + " =")), change)
    with pytest.raises(ValueError, match=message):
        config.load(write_config(tmp_path / "events.toml", text))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (VALID.replace('database = "/var/lib/agent-session/events.sqlite3"', "database = 42"), "database"),
        (
            VALID.replace("[scan]", "repositories = {}\n\n[scan]").replace(
                REPOSITORY_TABLE, ""
            ),
            "repositories",
        ),
        (
            VALID.replace("[scan]", "boards = {}\n\n[scan]").replace(
                BOARD_TABLE, ""
            ),
            "boards",
        ),
    ],
)
def test_rejects_wrong_top_level_types_as_value_errors(
    tmp_path: Path, text: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        config.load(write_config(tmp_path / "events.toml", text))


def test_rejects_duplicate_repositories_and_unknown_board_repository(tmp_path: Path) -> None:
    duplicate = VALID + '''
[[repositories]]
id = 123456
owner = "other"
name = "repo"
'''
    with pytest.raises(ValueError, match="duplicate"):
        config.load(write_config(tmp_path / "duplicate.toml", duplicate))

    missing = VALID.replace("repository_ids = [123456]", "repository_ids = [999]")
    with pytest.raises(ValueError, match="unknown repository"):
        config.load(write_config(tmp_path / "missing.toml", missing))


@pytest.mark.parametrize("duplicate_owner", ("lmorchard", "LMORCHARD"))
def test_rejects_case_insensitive_duplicate_board_identities(
    tmp_path: Path, duplicate_owner: str
) -> None:
    duplicate = VALID + BOARD_TABLE.replace("lmorchard", duplicate_owner)

    with pytest.raises(ValueError, match="duplicate board"):
        config.load(write_config(tmp_path / "duplicate-board.toml", duplicate))


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("table", "missing configuration key: polling"),
        ("projects", "missing polling key: projects_interval_seconds"),
        ("reactions", "missing polling key: reactions_interval_seconds"),
        ("zero", "projects_interval_seconds"),
        ("boolean", "reactions_interval_seconds"),
        ("unknown", "unknown polling key"),
    ],
)
def test_requires_strict_positive_polling_configuration(
    tmp_path: Path, case: str, message: str
) -> None:
    if case == "table":
        text = VALID.replace(
            "\n[polling]\nprojects_interval_seconds = 60\nreactions_interval_seconds = 60\n",
            "\n",
        )
    elif case == "projects":
        text = VALID.replace("projects_interval_seconds = 60\n", "")
    elif case == "reactions":
        text = VALID.replace("reactions_interval_seconds = 60\n", "")
    elif case == "unknown":
        text = VALID.replace("reactions_interval_seconds = 60", "reactions_interval_seconds = 60\nunknown = 1")
    else:
        key = "projects" if case == "zero" else "reactions"
        value = "0" if case == "zero" else "false"
        text = VALID.replace(f"{key}_interval_seconds = 60", f"{key}_interval_seconds = {value}")
    with pytest.raises(ValueError, match=message):
        config.load(write_config(tmp_path / "events.toml", text))
