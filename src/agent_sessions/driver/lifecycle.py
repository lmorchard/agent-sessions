"""Lifecycle dataclasses and operations for agent session driver runs."""

from __future__ import annotations

import argparse
import atexit
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path

import requests

from agent_sessions.driver import (
    agent_runner,
    credentials,
    discussion_manager,
    gate,
    gh_query,
    router,
    workspace,
)

PHASE_TIERS = {
    "triage": "low",
    "refine": "low",
    "execute": "high",
    "address_comments": "high",
    "fix_ci": "high",
    "fix_conflict": "high",
    "request_review": "low",
    "grade_gate": "low",
}


@dataclass(frozen=True)
class RunContext:
    repo: str
    repo_path: Path
    skill_dir: Path
    state_dir: Path
    runs_dir: Path
    runs_log: Path
    parked_log: Path
    inflight_file: Path
    hook_settings_file: Path
    creds: credentials.Credentials
    driver_bots: frozenset[str]
    board: str
    backend: str
    model: str
    high_tier_model: str
    low_tier_model: str
    max_issues: int
    max_budget_usd: float
    max_phase_attempts: int
    timeout: int
    retry: str
    issue: str
    classify_only: str
    dry_run: bool
    all_issues: bool
    workspaces_dir: str
    no_workspace_isolation: bool
    setup_hook: str
    clean_workspaces: bool


@dataclass(frozen=True)
class SelectionResult:
    board_items: list[dict]
    open_issues: list[dict]
    open_prs: list[dict]
    candidates: list[tuple[str, str]]
    board_item_ids: dict[str, str]


@dataclass
class InvocationResult:
    issue_num: str
    phase: str
    ts: str
    rundir: Path
    raw_output: Path
    stderr_output: Path
    writes_file: Path
    exit_code: int
    cost: float
    session_id: str
    cost_known: bool
    final_text: str
    writes_result: dict
    run_repo_path: Path


@dataclass(frozen=True)
class RunOutcome:
    issue_num: str
    outcome: str
    reason: str
    prurl: str
    cost: float = 0.0
    exit_code: int = 0


def log(msg: str) -> None:
    from agent_sessions.driver import agent_session_driver

    ts = agent_session_driver.datetime.now(timezone.utc).strftime("%H:%M:%SZ")
    sys.stderr.write(f"{ts}  {msg}\n")


def say(msg: str) -> None:
    sys.stdout.write(f"{msg}\n")


def die(msg: str, code: int = 2) -> None:
    sys.stderr.write(f"error: {msg}\n")
    sys.exit(code)


def hook_template_path() -> Path:
    """The PreToolUse settings template, resolved beside the module that loads it.

    A separate function so a test can replace it, and because *where* these two assets
    live is the thing that broke: they sat in repo-root `driver/` while this module
    looked for them beside itself, so the render silently never ran. They now ship inside
    the package, which is also what makes them present in an installed wheel.
    """
    return Path(__file__).parent / "settings.json"


def hook_script_path() -> Path:
    """The merge-block hook script. See `hook_template_path` for why this is a function."""
    return Path(__file__).parent / "merge-block-hook.sh"


def render_hook_settings(state_dir: Path) -> Path:
    """Write the run's Claude settings file with the merge-block hook wired in.

    Fails closed. The previous version guarded the whole body with
    `if template.is_file():` and wrapped it in `except Exception: pass`, so a missing or
    unreadable asset produced no hook, no message, and a green `make check` -- while
    `invoke_agent` went on passing `--settings <path that was never written>`. This hook
    is one of the layers standing between an unattended run and merging its own PR; when
    it cannot be installed, the run must not start.
    """
    template = hook_template_path()
    script = hook_script_path()

    if not template.is_file():
        die(f"merge-block hook template missing: {template}")
    if not script.is_file():
        die(f"merge-block hook script missing: {script}")
    if not os.access(script, os.X_OK):
        die(f"merge-block hook script is not executable: {script}")

    try:
        data = json.loads(template.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        die(f"merge-block hook template is unreadable: {template}: {exc}")

    hooks = data.setdefault("hooks", {})
    pre = hooks.setdefault("PreToolUse", [{}])
    if not pre:
        pre.append({})
    pre[0]["command"] = str(script.resolve())

    settings_file = state_dir / "settings.json"
    try:
        settings_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        die(f"could not write hook settings to {settings_file}: {exc}")
    return settings_file


def abspath(p: str) -> Path:
    path = Path(p)
    if path.is_absolute():
        return path.resolve()
    return (Path.cwd() / path).resolve()


def is_git_ignored(path: Path | str, repo_path: Path | str) -> bool:
    p = Path(path)
    if not p.exists():
        return True
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "check-ignore", "-q", str(p.resolve())],
            capture_output=True,
        )
        return res.returncode == 0
    except Exception:
        return True


def whoami(env: dict[str, str]) -> str:
    token = env.get("GH_TOKEN") or env.get("GITHUB_TOKEN") or ""
    if token.startswith("ghs_"):
        try:
            res = subprocess.run(
                ["gh", "api", "graphql", "-f", "query={ viewer { login } }", "--jq", ".data.viewer.login"],
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
            out = res.stdout.strip()
            if out and not out.startswith("{") and not out.startswith("["):
                return out
        except Exception:
            pass

    try:
        res = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        out = res.stdout.strip()
        if out and not out.startswith("{") and not out.startswith("["):
            return out
    except Exception:
        pass
    return ""


def load_env_file(env_file: Path | str = ".env") -> set[str]:
    path = Path(env_file)
    keys: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                keys.add(k.strip())
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return keys


def preflight(argv: list[str] | None = None) -> RunContext:
    from agent_sessions.driver import agent_session_driver

    env_file = Path(".env")
    env_file_keys = load_env_file(env_file)

    parser = argparse.ArgumentParser(description="Agent session driver")
    parser.add_argument("--repo", default=os.environ.get("REPO") or os.environ.get("DRIVER_REPO") or "")
    parser.add_argument("--skill-dir", default=os.environ.get("SKILL_DIR") or os.environ.get("DRIVER_SKILL_DIR") or "")
    parser.add_argument("--repo-path", default=os.environ.get("REPO_PATH") or os.environ.get("DRIVER_REPO_PATH") or "")
    parser.add_argument("--issue", default=os.environ.get("ISSUE") or "")
    parser.add_argument("--max-issues", type=int, default=int(os.environ.get("MAX_ISSUES", "1")))
    parser.add_argument(
        "--max-budget-usd",
        type=float,
        default=float(os.environ.get("MAX_BUDGET_USD") or os.environ.get("MAX_BUDGET") or "10.0"),
    )
    parser.add_argument("--max-phase-attempts", type=int, default=int(os.environ.get("MAX_PHASE_ATTEMPTS", "3")))
    parser.add_argument(
        "--timeout", type=int, default=int(os.environ.get("RUN_TIMEOUT") or os.environ.get("TIMEOUT") or "5400")
    )
    parser.add_argument("--state-dir", default=os.environ.get("STATE_DIR") or "")
    parser.add_argument("--board", default=os.environ.get("BOARD") or os.environ.get("DRIVER_BOARD") or "")
    parser.add_argument(
        "--backend", default=os.environ.get("BACKEND") or os.environ.get("DRIVER_BACKEND") or "claude"
    )
    parser.add_argument("--model", default=os.environ.get("MODEL") or "")
    parser.add_argument("--high-tier-model", default=os.environ.get("HIGH_TIER_MODEL") or "")
    parser.add_argument("--low-tier-model", default=os.environ.get("LOW_TIER_MODEL") or "")
    parser.add_argument("--retry", default=os.environ.get("RETRY") or "")
    parser.add_argument("--classify-only", default="")
    parser.add_argument("--resumed-from", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-nested-skill-dir", action="store_true")
    parser.add_argument("--allow-nested-workspaces-dir", action="store_true")
    parser.add_argument("--all-issues", action="store_true")
    parser.add_argument(
        "--workspaces-dir", default=os.environ.get("WORKSPACES_DIR") or os.environ.get("DRIVER_WORKSPACES_DIR") or ""
    )
    parser.add_argument("--no-workspace-isolation", action="store_true")
    parser.add_argument(
        "--setup-hook", default=os.environ.get("SETUP_HOOK") or os.environ.get("DRIVER_SETUP_HOOK") or ""
    )
    parser.add_argument("--clean-workspaces", action="store_true")

    args = parser.parse_args(argv)

    repo = args.repo
    if not repo:
        die("--repo (or REPO in .env) is required")

    parts = repo.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1] or "." in parts or ".." in parts:
        die(f"--repo must be owner/name, with exactly one '/': {repo}")

    if not args.skill_dir:
        die("--skill-dir (or SKILL_DIR in .env) is required")
    if not args.repo_path:
        die("--repo-path (or REPO_PATH in .env) is required")

    skill_dir = abspath(args.skill_dir)
    repo_path = abspath(args.repo_path)

    user_config = credentials.user_config_path()
    mode_problem = credentials.file_mode_error(user_config)
    if mode_problem:
        die(mode_problem)
    user_config_keys = load_env_file(user_config)

    creds = credentials.resolve()
    for keys, path in ((env_file_keys, env_file), (user_config_keys, user_config)):
        exposure = credentials.exposure_error(keys, path, repo_path, git_ignored=is_git_ignored(path, repo_path))
        if exposure:
            die(exposure)
    config_problem = credentials.config_error(creds)
    if config_problem:
        die(config_problem)

    read_login = agent_session_driver.whoami(credentials.agent_env(dict(os.environ), creds))
    write_login = agent_session_driver.whoami(credentials.driver_env(dict(os.environ), creds))
    identity_problem = credentials.identity_error(creds, read_login=read_login, write_login=write_login)
    if identity_problem:
        die(identity_problem)
    say(f"identity: acting as {creds.login} (agent reads, driver writes)")

    os.environ[credentials.READ_TOKEN_VAR] = creds.read_token

    driver_bots = credentials.bot_logins(creds)
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
        remote_warning = credentials.remote_warning(res.stdout)
    except Exception:
        remote_warning = ""
    if remote_warning:
        say(remote_warning)
    credentials.apply_driver_env(creds)
    agent_session_driver.check_and_handle_rate_limit(
        env=credentials.agent_env(dict(os.environ), creds),
        say_fn=say,
    )

    state_dir_str = args.state_dir
    if not state_dir_str:
        xdg = os.environ.get("XDG_STATE_HOME")
        home = os.environ.get("HOME")
        if not xdg and not home:
            die("no --state-dir given and neither XDG_STATE_HOME nor HOME is set; pass --state-dir")
        base = Path(xdg) if xdg else Path(str(home)) / ".local" / "state"
        state_dir_str = str(base / "agent-session" / repo.replace("/", "-"))
    state_dir = abspath(state_dir_str)

    log(f"state dir  {state_dir}")

    if skill_dir and repo_path:
        try:
            skill_dir.relative_to(repo_path)
            nested = True
        except ValueError:
            nested = False
        if nested and not args.allow_nested_skill_dir:
            die(
                f"error: --skill-dir ({skill_dir}) resolves inside --repo-path ({repo_path}); pass --allow-nested-skill-dir to proceed"
            )

    if args.workspaces_dir:
        ws_dir = abspath(args.workspaces_dir)
        try:
            ws_dir.relative_to(repo_path)
            nested_ws = True
        except ValueError:
            nested_ws = False
        if nested_ws and not is_git_ignored(ws_dir, repo_path) and not args.allow_nested_workspaces_dir:
            die(
                f"error: --workspaces-dir ({ws_dir}) resolves inside --repo-path ({repo_path}) and is not git-ignored; pass --allow-nested-workspaces-dir to proceed"
            )

    state_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = state_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    runs_log = state_dir / "runs.jsonl"
    parked_log = state_dir / "parked.jsonl"
    runs_log.touch(exist_ok=True)
    parked_log.touch(exist_ok=True)

    atexit.register(lambda: agent_session_driver.release_lock(repo_path))

    inflight_file = state_dir / "inflight.json"
    if inflight_file.is_file():
        say("WARNING: a previous run died before recording its outcome:")
        try:
            inf = json.loads(inflight_file.read_text(encoding="utf-8"))
            say(f"  issue #{inf.get('issue')}  started {inf.get('started')}  run dir {inf.get('run_dir')}")
            run_dir_p = Path(inf.get("run_dir", ""))
            pid_file = run_dir_p / "child.pid"
            ipid = pid_file.read_text(encoding="utf-8").strip() if pid_file.is_file() else ""
            if ipid:
                try:
                    os.kill(int(ipid), 0)
                    is_alive = True
                except OSError:
                    is_alive = False
                if is_alive:
                    say(f"  ORPHAN STILL RUNNING (pid {ipid}, reparented) -- it is unsupervised and still spending.")
                    say(f"  Let it finish, then:  --classify-only {inf.get('issue')}")
                    say(f"  Or kill it:           kill -TERM {ipid}")
                    if not args.dry_run:
                        die("refusing to start a second run while an orphan is live")
                    say("")
                else:
                    say(f"  recover it with:  --classify-only {inf.get('issue')}")
                    say("")
            else:
                say(f"  recover it with:  --classify-only {inf.get('issue')}")
                say("")
        except Exception:
            pass

    hook_settings_file = render_hook_settings(state_dir)

    return RunContext(
        repo=repo,
        repo_path=repo_path,
        skill_dir=skill_dir,
        state_dir=state_dir,
        runs_dir=runs_dir,
        runs_log=runs_log,
        parked_log=parked_log,
        inflight_file=inflight_file,
        hook_settings_file=hook_settings_file,
        creds=creds,
        driver_bots=driver_bots,
        board=args.board,
        backend=args.backend,
        model=args.model,
        high_tier_model=args.high_tier_model,
        low_tier_model=args.low_tier_model,
        max_issues=args.max_issues,
        max_budget_usd=args.max_budget_usd,
        max_phase_attempts=args.max_phase_attempts,
        timeout=args.timeout,
        retry=args.retry,
        issue=args.issue,
        classify_only=args.classify_only,
        dry_run=args.dry_run,
        all_issues=args.all_issues,
        workspaces_dir=args.workspaces_dir,
        no_workspace_isolation=args.no_workspace_isolation,
        setup_hook=args.setup_hook,
        clean_workspaces=args.clean_workspaces,
    )


def run_classify_only(ctx: RunContext) -> int:
    from agent_sessions.driver import agent_session_driver

    issue_num = ctx.classify_only
    say(f"== classify-only #{issue_num} ==")
    open_prs = gh_query.fetch_prs(ctx.repo, state="all")
    matching_pr = gh_query.pr_for_issue(issue_num, open_prs)

    matching_pr_dict = None
    if matching_pr:
        pr_num = matching_pr.split("\t")[0]
        for pr in open_prs:
            if str(pr.get("number")) == str(pr_num):
                matching_pr_dict = pr
                break

    runs_matching = sorted(ctx.runs_dir.glob(f"{issue_num}-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    rundir = runs_matching[0] if runs_matching else None

    cost = 0.0
    session = ""
    ts = agent_session_driver.datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if rundir and (rundir / "stream.jsonl").is_file():
        say(f"  run dir  {rundir}")
        raw = rundir / "stream.jsonl"
        parsed = agent_runner.parse_result_stream(ctx.backend, raw)
        cost = float(str(parsed.get("total_cost_usd", 0.0) or 0.0))
        session = str(parsed.get("session_id", ""))
        ts = rundir.name.replace(f"{issue_num}-", "")
        say(f"  recovered from stream: cost ${cost}  session {session or 'none'}")
    else:
        say(f"  no run dir found for #{issue_num}; classifying from the PR alone")

    if not matching_pr_dict:
        outcome = "parked"
        reason = f"no open PR found for #{issue_num}"
        prurl = ""
    else:
        pr_num = matching_pr_dict.get("number") or ""
        prurl = matching_pr_dict.get("url", "")
        pr_body = matching_pr_dict.get("body", "")
        head_sha = ""
        changed_files = None
        files_list: list[str] = []
        try:
            res = subprocess.run(
                ["gh", "pr", "view", str(pr_num), "--repo", ctx.repo, "--json", "headRefOid,changedFiles,baseRefName,files"],
                capture_output=True,
                text=True,
                check=True,
            )
            pr_data = json.loads(res.stdout)
            head_sha = pr_data.get("headRefOid", "")
            changed_files = pr_data.get("changedFiles", None)
            files_list = [str(f.get("path")) for f in pr_data.get("files", []) if isinstance(f, dict) and f.get("path") is not None]
        except Exception:
            head_sha = ""
            changed_files = None
            files_list = []

        failed_ci, _ = agent_session_driver.check_pr_ci_status(ctx.repo, pr_num)
        ci_checks = "failed" if failed_ci > 0 else "pass"
        outcome_res = gate.classify(
            pr_body,
            head_sha=head_sha,
            ci_checks=ci_checks,
            changed_files=changed_files,
            pr_files=files_list,
        )
        outcome = outcome_res["outcome"]
        reason = outcome_res["reason"]

    say(f"  outcome  {outcome}")
    say(f"  reason   {reason}")
    if prurl:
        say(f"  pr       {prurl}")

    agent_session_driver.apply_park_state(issue_num, outcome, ts, reason, ctx.repo, ctx.state_dir, ctx.parked_log)
    if ctx.inflight_file.is_file():
        ctx.inflight_file.unlink(missing_ok=True)
    say("\nrecorded to runs.jsonl. Nothing was merged.")
    return 0


def select_queue(ctx: RunContext) -> SelectionResult:
    from agent_sessions.driver import agent_session_driver

    say("== select ==")
    board_items = agent_session_driver.fetch_board_json(ctx.board) if ctx.board and not ctx.all_issues else []

    try:
        cmd = ["gh", "issue", "list", "--repo", ctx.repo, "--state", "open", "--limit", "500", "--json", "number,title,body,labels,url,updatedAt"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        open_issues = json.loads(res.stdout)
    except Exception as e:
        log(f"failed to list open issues: {e}")
        open_issues = []

    board_nums: set[str] = set()
    board_item_ids: dict[str, str] = {}
    for item in board_items:
        st = item.get("status", "")
        prio = item.get("priority", "")
        content = item.get("content", {})
        if isinstance(content, dict) and "number" in content:
            num_str = str(content["number"])
            item_id = str(item.get("id") or "")
            if item_id:
                board_item_ids[num_str] = item_id
            if st == "Ready" or prio in ("P0", "P1"):
                board_nums.add(num_str)

    if not ctx.all_issues:
        filtered_issues = []
        for iss in open_issues:
            num_str = str(iss.get("number"))
            labels = [l.get("name", "") for l in iss.get("labels", []) if isinstance(l, dict)]
            has_priority_label = any(p_lbl in labels for p_lbl in ("P0", "P1", "P2", "P3", "P4", "P5"))
            if num_str in board_nums or has_priority_label:
                filtered_issues.append(iss)
    else:
        filtered_issues = open_issues

    candidates_json = [
        iss
        for iss in filtered_issues
        if agent_session_driver.is_specced(iss)
        and not any(
            isinstance(l, dict) and l.get("name") == agent_session_driver.MERGE_READY_LABEL
            for l in iss.get("labels", [])
        )
    ]
    markerless_json = [iss for iss in filtered_issues if not agent_session_driver.is_specced(iss)]
    all_issues_json = candidates_json + markerless_json
    parked = agent_session_driver.parked_numbers(all_issues_json)

    open_prs = gh_query.fetch_open_prs(ctx.repo)

    parked_nums = parked
    park_reasons = {}
    attempts_map = {}
    human_comments_map = {}
    pr_details_map = {}

    open_issues_map = {str(iss.get("number")): str(iss.get("updatedAt", "")) for iss in open_issues if isinstance(iss, dict)}

    for iss in all_issues_json:
        n = str(iss.get("number"))
        if n in parked_nums and n != ctx.retry:
            park_t = agent_session_driver.get_park_time(n, ctx.state_dir)
            updated_at = open_issues_map.get(n, "")
            has_human, login = agent_session_driver.has_new_human_comment(n, ctx.repo, ctx.driver_bots, park_time=park_t, issue_updated_at=updated_at)
            human_comments_map[n] = (has_human, login)
            if not has_human:
                park_reasons[n] = agent_session_driver.park_reason(n, ctx.state_dir)
        attempts_map[n] = agent_session_driver.get_attempts(n, ctx.repo, issues_json=all_issues_json)

    unresolved_map = gh_query.fetch_unresolved_threads_for_all_prs(ctx.repo)

    for pr in open_prs:
        prnum = str(pr.get("number"))
        unresolved = unresolved_map.get(prnum)
        if unresolved is None:
            unresolved = agent_session_driver.check_pr_unresolved_threads(ctx.repo, prnum, ctx.creds.read_token)

        if "statusCheckRollup" in pr:
            failed_ci, pending_ci = gh_query.parse_pr_ci_status(pr)
        else:
            failed_ci, pending_ci = agent_session_driver.check_pr_ci_status(ctx.repo, prnum)

        if "reviewRequests" in pr or "reviews" in pr or "reviewDecision" in pr:
            req_rev, revd, rev_decision = gh_query.parse_pr_reviews(pr)
        else:
            req_rev, revd, rev_decision = agent_session_driver.check_pr_reviews(ctx.repo, prnum)

        has_human_pr = False
        if "commits" in pr and ("comments" in pr or "reviews" in pr):
            has_human_pr = gh_query.parse_pr_human_comments(pr, ctx.driver_bots)

        pr_details_map[prnum] = {
            "unresolved": unresolved,
            "failed_ci": failed_ci,
            "pending_ci": pending_ci,
            "req_rev": req_rev,
            "revd": revd,
            "rev_decision": rev_decision,
            "merge_state_status": pr.get("mergeStateStatus"),
            "mergeable": pr.get("mergeable"),
            "has_new_human_comment": has_human_pr,
        }

    config = {
        "repo": ctx.repo,
        "all_issues": ctx.all_issues,
        "max_phase_attempts": ctx.max_phase_attempts,
        "retry": ctx.retry,
        "issue": ctx.issue,
    }

    sel_res = router.select(
        open_issues=open_issues,
        open_prs=open_prs,
        board_items=board_items,
        parked_nums=parked_nums,
        park_reasons=park_reasons,
        attempts_map=attempts_map,
        human_comments_map=human_comments_map,
        pr_details_map=pr_details_map,
        config=config,
    )

    for msg in sel_res["messages"]:
        say(msg)

    ts_str = agent_session_driver.datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for m in sel_res["unpark_actions"]:
        agent_session_driver.park_label_remove(m, ctx.repo)

    for m, reason in sel_res["park_actions"]:
        agent_session_driver.apply_park_state(m, "parked", ts_str, f"parked by loop breaker: {reason}", ctx.repo, ctx.state_dir, ctx.parked_log, quiet=True)

    all_candidates = sel_res["candidates"]

    locked_candidates: list[tuple[str, str]] = []
    for cand_item in all_candidates:
        num, cand_phase = cand_item
        if agent_session_driver.acquire_lock(num, cand_phase, ctx.repo_path):
            locked_candidates.append(cand_item)
            break
        else:
            say(f"  SKIP    #{num}  lock contention (another agent holds or held lock)")

    c_count = len(locked_candidates)
    eligible_str = f"{locked_candidates[0][0]}:{locked_candidates[0][1]}" if locked_candidates else ""
    say(f"eligible: {c_count} ({eligible_str})")

    if ctx.clean_workspaces:
        clean_ws_dir: Path | None = Path(ctx.workspaces_dir).resolve() if ctx.workspaces_dir else None
        active = {num for num, _ in locked_candidates}
        removed = workspace.clean_stale_workspaces(ctx.state_dir, ctx.repo_path, active, clean_ws_dir)
        say(f"cleaned {len(removed)} stale workspace(s)")

    return SelectionResult(
        board_items=board_items,
        open_issues=open_issues,
        open_prs=open_prs,
        candidates=locked_candidates,
        board_item_ids=board_item_ids,
    )


def prepare_workspace(ctx: RunContext, issue_num: str) -> Path:
    if not ctx.no_workspace_isolation:
        run_ws_dir: Path | None = Path(ctx.workspaces_dir).resolve() if ctx.workspaces_dir else None
        ws_path = workspace.get_workspace_path(ctx.state_dir, issue_num, run_ws_dir)
        return workspace.ensure_workspace(
            repo_path=ctx.repo_path,
            workspace_path=ws_path,
            branch_name=f"issue-{issue_num}",
            setup_hook=ctx.setup_hook or None,
        )
    return ctx.repo_path


def invoke_agent(
    ctx: RunContext,
    issue_num: str,
    phase: str,
    run_repo_path: Path,
    open_prs: list[dict],
    board_item_ids: dict[str, str],
) -> InvocationResult:
    from agent_sessions.driver import agent_session_driver

    agent_session_driver.increment_attempts(issue_num, ctx.repo)
    url = f"https://github.com/{ctx.repo}/issues/{issue_num}"
    ts = agent_session_driver.datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rundir = ctx.runs_dir / f"{issue_num}-{ts}"
    rundir.mkdir(parents=True, exist_ok=True)
    raw_output = rundir / "stream.jsonl"
    stderr_output = rundir / "stderr.txt"
    writes_file = rundir / "writes.jsonl"

    extra_context = ""
    prline = gh_query.pr_for_issue(issue_num, open_prs)
    if prline:
        prnum = prline.split("\t")[0]
        try:
            res = subprocess.run(
                ["gh", "pr", "view", str(prnum), "--repo", ctx.repo, "--json", "body,comments"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                pr_data = json.loads(res.stdout)
                pr_body = pr_data.get("body", "")
                if "Handoff / Parked State" in pr_body:
                    extra_context += f"Draft PR Body (Handoff State):\n{pr_body}\n\n"
                pr_comments = pr_data.get("comments", [])
                if pr_comments:
                    extra_context += "Recent PR Comments:\n"
                    for c in pr_comments[-3:]:  # last 3 comments
                        extra_context += f"- {c.get('author', {}).get('login', 'unknown')}: {c.get('body', '')}\n"

                unresolved_text = agent_session_driver.get_pr_unresolved_threads_text(ctx.repo, prnum, ctx.creds.read_token)
                if unresolved_text:
                    extra_context += "Unresolved Review Threads:\n"
                    extra_context += unresolved_text

                if phase == "fix_ci":
                    try:
                        res_checks = subprocess.run(
                            ["gh", "pr", "checks", str(prnum), "--repo", ctx.repo, "--failed"],
                            capture_output=True,
                            text=True,
                        )
                        if res_checks.returncode == 0 and res_checks.stdout.strip():
                            extra_context += f"Failed CI Checks:\n{res_checks.stdout.strip()}\n\n"
                    except Exception:
                        pass

        except Exception:
            pass

    try:
        res = subprocess.run(
            ["gh", "issue", "view", str(issue_num), "--repo", ctx.repo, "--json", "title,body,comments,labels"],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            issue_data = json.loads(res.stdout)

            extra_context += f"Issue Title: {issue_data.get('title', '')}\n"

            labels = [str(l.get('name')) for l in issue_data.get('labels', []) if isinstance(l, dict) and l.get('name')]
            if labels:
                extra_context += f"Issue Labels: {', '.join(labels)}\n"

            body = issue_data.get("body", "")
            if body:
                extra_context += f"\nIssue Body:\n{body}\n\n"

            issue_comments = issue_data.get("comments", [])
            if issue_comments:
                extra_context += "Recent Issue Comments:\n"
                for c in issue_comments[-3:]:  # last 3 comments
                    extra_context += f"- {c.get('author', {}).get('login', 'unknown')}: {c.get('body', '')}\n"
    except Exception:
        pass

    if phase in ("triage", "refine"):
        query = """query($owner:String!,$repo:String!,$issue:Int!){
          repository(owner:$owner,name:$repo){
            issue(number:$issue){
              comments(last:50){
                nodes{
                  author { login }
                  body
                  reactions(first:10){
                    nodes{
                      content
                      user{login}
                    }
                  }
                }
              }
            }
          }
        }"""
        parts = ctx.repo.split("/")
        if len(parts) == 2:
            owner, repo_name = parts
            try:
                req_res = requests.post(
                    "https://api.github.com/graphql",
                    json={
                        "query": query,
                        "variables": {
                            "owner": owner,
                            "repo": repo_name,
                            "issue": int(issue_num) if str(issue_num).isdigit() else issue_num
                        }
                    },
                    headers={
                        "Authorization": f"Bearer {ctx.creds.read_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=10,
                )
                req_res.raise_for_status()
                data = req_res.json()

                nodes = (
                    data.get("data", {})
                    .get("repository", {})
                    .get("issue", {})
                    .get("comments", {})
                    .get("nodes", [])
                )

                if nodes:
                    extra_context += "\nIssue Comments with Reactions:\n"
                    for c in nodes[-10:]:  # Limit to 10 most recent
                        author = c.get("author", {}).get("login", "unknown") if c.get("author") else "unknown"
                        body = c.get("body", "")
                        if len(body) > 500:
                            body = body[:500] + "... [truncated]"
                        reactions = c.get("reactions", {}).get("nodes", [])
                        reactions_text = ""
                        if reactions:
                            reactions_list = [f"{r.get('content')} by {r.get('user', {}).get('login', 'unknown')}" for r in reactions]
                            reactions_text = f" (Reactions: {', '.join(reactions_list)})"
                        extra_context += f"  - {author}{reactions_text}: {body}\n"
            except Exception:
                pass

    prompt = agent_session_driver.build_prompt(url, phase, ctx.skill_dir, writes_file, extra_context=extra_context)
    prompt_file = rundir / "prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    say("")
    say(f"== invoke #{issue_num} ==")
    say(f"  issue    {url}")
    say(f"  cwd      {run_repo_path}")
    say(f"  budget   ${ctx.max_budget_usd}   timeout {ctx.timeout}s")
    say(f"  run dir  {rundir}")

    # Post start discussion note
    try:
        ok = discussion_manager.post_start(
            repo=ctx.repo, issue=issue_num, phase=phase, budget=str(ctx.max_budget_usd), rundir=str(rundir)
        )
        if not ok:
            say("  NOTE: could not post start discussion note to Lab Notebook")
    except Exception as e:
        say(f"  NOTE: failed to post start discussion note: {e}")

    # Update board status to "In progress" for execute phase
    if phase == "execute" and ctx.board and issue_num in board_item_ids:
        if agent_session_driver.mark_board_in_progress(ctx.board, board_item_ids[issue_num]):
            say(f"  NOTE: moved issue #{issue_num} to 'In progress' on board {ctx.board}")

    # Write inflight marker
    ctx.inflight_file.write_text(
        json.dumps({"issue": int(issue_num), "started": ts, "run_dir": str(rundir), "url": url}), encoding="utf-8"
    )

    if phase not in PHASE_TIERS:
        die(f"unknown phase: {phase}")
    tier = PHASE_TIERS[phase]

    if phase == "request_review":
        say("  (Executing request_review deterministically)")
        ret = 0
        cost = 0.0
        cost_known = True
        session_id = "deterministic"
        final_text = ""

        try:
            prs_json = open_prs
            prline = gh_query.pr_for_issue(issue_num, prs_json)
            if prline:
                pr_num = prline.split("\t")[0]

                res_owner = subprocess.run(
                    ["gh", "repo", "view", ctx.repo, "--json", "owner"],
                    capture_output=True, text=True, check=True
                )
                try:
                    owner_data = json.loads(res_owner.stdout)
                    owner = owner_data.get("owner", {}).get("login", "lmorchard") if isinstance(owner_data, dict) else "lmorchard"
                except Exception:
                    owner = "lmorchard"

                manifest_entry = {
                    "kind": "pr_edit",
                    "pr": int(pr_num) if str(pr_num).isdigit() else pr_num,
                    "add_reviewer": [owner]
                }
                with open(writes_file, "a") as wf:
                    wf.write(json.dumps(manifest_entry) + "\n")

                final_text = f"Requested review deterministically from {owner} on PR {pr_num}."
                raw_output.write_text(final_text, encoding="utf-8")
            else:
                ret = 1
                final_text = "No open PR found for this issue."
                raw_output.write_text(final_text, encoding="utf-8")

        except Exception as e:
            ret = 1
            final_text = f"Deterministic request_review failed: {e}"
            raw_output.write_text(final_text, encoding="utf-8")

        parsed = {
            "final": final_text,
            "total_cost_usd": cost,
            "session_id": session_id,
            "cost_known": cost_known
        }
    else:
        runner_args = [
            "--backend", ctx.backend,
            "--repo-path", str(run_repo_path),
            "--skill-dir", str(ctx.skill_dir),
            "--prompt-file", str(prompt_file),
            "--raw-output", str(raw_output),
            "--stderr-output", str(stderr_output),
            "--max-budget", str(ctx.max_budget_usd),
            "--timeout", str(ctx.timeout),
            "--settings", str(ctx.hook_settings_file),
            "--tier", tier,
            "--writes-file", str(writes_file),
        ]
        if ctx.model:
            runner_args.extend(["--model", ctx.model])
        if ctx.high_tier_model:
            runner_args.extend(["--high-tier-model", ctx.high_tier_model])
        if ctx.low_tier_model:
            runner_args.extend(["--low-tier-model", ctx.low_tier_model])

        ret = agent_runner.run_agent(runner_args)
        pid_file = rundir / "child.pid"
        if pid_file.is_file():
            pid_file.unlink(missing_ok=True)

        parsed = agent_runner.parse_result_stream(ctx.backend, raw_output)
        final_text = str(parsed.get("final", ""))
        cost = float(str(parsed.get("total_cost_usd", 0.0) or 0.0))
        session_id = str(parsed.get("session_id", ""))
        cost_known = bool(parsed.get("cost_known", False))

    (rundir / "parsed.json").write_text(json.dumps(parsed, indent=2), encoding="utf-8")
    (rundir / "final.txt").write_text(final_text, encoding="utf-8")

    say(f"  exit {ret}   cost ${cost}   session {session_id or 'none'}")

    # Perform the agent's GitHub writes, with the driver's credential.
    writes_result = agent_session_driver.perform_writes(writes_file, ctx.repo, run_repo_path, rundir, ctx.board)
    for line in writes_result["messages"]:
        say(line)

    return InvocationResult(
        issue_num=issue_num,
        phase=phase,
        ts=ts,
        rundir=rundir,
        raw_output=raw_output,
        stderr_output=stderr_output,
        writes_file=writes_file,
        exit_code=ret,
        cost=cost,
        session_id=session_id,
        cost_known=cost_known,
        final_text=final_text,
        writes_result=writes_result,
        run_repo_path=run_repo_path,
    )


def classify_and_record(
    ctx: RunContext,
    inv: InvocationResult,
    open_prs: list[dict] | None = None,
) -> RunOutcome:
    from agent_sessions.driver import agent_session_driver

    prurl = ""
    changed_files = None
    head_sha = ""
    base_ref = ""
    if inv.exit_code == 124:
        outcome = "failed"
        reason = f"timed out after {ctx.timeout}s"
    elif inv.exit_code != 0 and not inv.session_id and inv.cost == 0.0 and not agent_runner.stream_has_events(inv.raw_output):
        outcome = "driver-fault"
        reason = f"{ctx.backend} exited {inv.exit_code} before starting (no readable events, no session, no spend) -- see {inv.stderr_output}"
    elif inv.exit_code != 0 and not agent_runner.has_success_result(ctx.backend, inv.raw_output):
        outcome = "failed"
        reason = f"{ctx.backend} exited {inv.exit_code}" if inv.cost_known else f"{ctx.backend} exited {inv.exit_code}; cost undetermined"
    else:
        if open_prs is None:
            try:
                prs_json = gh_query.fetch_open_prs(ctx.repo)
            except Exception as e:
                log(f"warning: failed to refresh PRs during classification: {e}")
                prs_json = []
        elif inv.writes_result.get("applied"):
            try:
                prs_json = gh_query.fetch_open_prs(ctx.repo)
            except Exception as e:
                log(f"warning: failed to refresh PRs during classification: {e}")
                prs_json = open_prs
        else:
            prs_json = open_prs

        prline = gh_query.pr_for_issue(inv.issue_num, prs_json)
        if not prline:
            if inv.phase in ("triage", "refine"):
                try:
                    res = subprocess.run(
                        ["gh", "issue", "view", inv.issue_num, "--repo", ctx.repo, "--json", "body,labels"],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    issue_state = json.loads(res.stdout)
                    lbls = [
                        label.get("name")
                        for label in issue_state.get("labels", [])
                        if isinstance(label, dict)
                    ]
                    issue_tier = gate.tier_of(issue_state.get("body", ""))
                except Exception:
                    lbls = []
                    issue_tier = "missing"
                if agent_session_driver.PARK_LABEL in lbls or agent_session_driver.INTERACTIVE_LABEL in lbls:
                    outcome = "parked"
                    if "inconclusive" in inv.final_text.lower():
                        reason = f"parked (inconclusive reply) by agent during {inv.phase}: {inv.final_text[:400]}"
                        agent_session_driver.decrement_attempts(inv.issue_num, ctx.repo)
                    else:
                        reason = f"parked by agent during {inv.phase}: {inv.final_text[:400]}"
                elif inv.phase == "refine" and issue_tier == "needs-review":
                    outcome = "parked"
                    reason = f"refine completed; issue still needs human review: {inv.final_text[:400]}"
                else:
                    outcome = "incomplete"
                    reason = f"{inv.phase} completed; issue unparked for re-evaluation: {inv.final_text[:400]}"
            else:
                outcome = "parked"
                if "inconclusive" in inv.final_text.lower():
                    reason = f"parked (inconclusive reply); run's own account: {inv.final_text[:400]}"
                    agent_session_driver.decrement_attempts(inv.issue_num, ctx.repo)
                else:
                    reason = f"no PR opened; run's own account: {inv.final_text[:400]}"
        else:
            prnum, prurl = prline.split("\t")[:2]
            changed_files = None
            base_ref = ""
            files_list = []
            try:
                res = subprocess.run(
                    ["gh", "pr", "view", prnum, "--repo", ctx.repo, "--json", "body,headRefOid,changedFiles,baseRefName,files"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                pr_data = json.loads(res.stdout)
                pr_body = pr_data.get("body", "")
                head_sha = pr_data.get("headRefOid", "")
                changed_files = pr_data.get("changedFiles", None)
                base_ref = pr_data.get("baseRefName", "")
                files_list = [str(f.get("path")) for f in pr_data.get("files", []) if isinstance(f, dict) and f.get("path") is not None]
            except Exception:
                pr_body = ""
                head_sha = ""

            matching_pr_dict = next((p for p in prs_json if isinstance(p, dict) and str(p.get("number")) == str(prnum)), None)
            if matching_pr_dict and "statusCheckRollup" in matching_pr_dict:
                failed_ci, _ = gh_query.parse_pr_ci_status(matching_pr_dict)
            else:
                failed_ci, _ = agent_session_driver.check_pr_ci_status(ctx.repo, prnum)
            ci_checks = "failed" if failed_ci > 0 else "pass"
            outcome_res = gate.classify(
                pr_body,
                head_sha=head_sha,
                ci_checks=ci_checks,
                changed_files=changed_files,
                pr_files=files_list,
            )
            outcome = outcome_res["outcome"]
            reason = outcome_res["reason"]
            (inv.rundir / "gate.yaml").write_text(outcome_res.get("gate", ""), encoding="utf-8")

    write_note = agent_session_driver.writes_summary(inv.writes_result)
    if write_note:
        reason = f"{reason} [{write_note}]"

    if outcome in ("incomplete", "parked", "no-gate") and inv.cost >= (ctx.max_budget_usd * 0.95):
        outcome = "budget-exhausted"
        reason = f"spent ${inv.cost} of ${ctx.max_budget_usd} (>=95%) and never reached the gate"

    say(f"  outcome  {outcome}")
    say(f"  reason   {reason}")
    if prurl:
        say(f"  pr       {prurl}")

    # Record run
    row = {
        "issue": int(inv.issue_num),
        "repo": ctx.repo,
        "phase": inv.phase,
        "started": inv.ts,
        "exit": inv.exit_code,
        "cost_usd": inv.cost,
        "session_id": inv.session_id,
        "outcome": outcome,
        "reason": reason,
        "pr": prurl,
        "changed_files": changed_files if changed_files is not None else 0,
        "base_diff_sha": f"{base_ref}..{head_sha[:8]}" if (base_ref and head_sha) else head_sha[:8],
        "run_dir": str(inv.rundir),
        "writes": {
            "recorded": len(inv.writes_result["entries"]),
            "applied": inv.writes_result["applied"],
            "ok": inv.writes_result["ok"],
        },
        "provenance": {},
    }
    with open(ctx.runs_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")

    agent_session_driver.apply_park_state(inv.issue_num, outcome, inv.ts, reason, ctx.repo, ctx.state_dir, ctx.parked_log)

    # Post finish discussion note
    try:
        ok = discussion_manager.post_finish(
            repo=ctx.repo,
            issue=inv.issue_num,
            phase=inv.phase,
            outcome=outcome,
            cost=str(inv.cost),
            session=inv.session_id or "none",
            prurl=prurl or "none",
            reason=reason,
            rundir=str(inv.rundir),
        )
        if not ok:
            say("  NOTE: could not post finish discussion note to Lab Notebook")
    except Exception as e:
        say(f"  NOTE: failed to post finish discussion note: {e}")

    if ctx.inflight_file.is_file():
        ctx.inflight_file.unlink(missing_ok=True)

    return RunOutcome(
        issue_num=inv.issue_num,
        outcome=outcome,
        reason=reason,
        prurl=prurl,
        cost=inv.cost,
        exit_code=inv.exit_code,
    )


def report_results(
    summary_rows: list[RunOutcome],
    attempted: int,
    total_cost: float,
    state_dir: Path,
) -> None:
    say("\n== report ==")
    say(f"attempted {attempted} issue(s), total cost ${total_cost:.4f}")
    for row in summary_rows:
        say(f"  #{row.issue_num}  {row.outcome}")
        say(f"        {row.reason}")
        if row.prurl:
            say(f"        {row.prurl}")

    say("\nNothing was merged. eligible-for-auto-merge is a finding, not an action --")
    say("acting on it is a separate decision (phase 3 of docs/design.md's rollout).")
    say(f"State: {state_dir}")


def main(argv: list[str] | None = None) -> int:
    from agent_sessions.driver import agent_session_driver

    ctx = agent_session_driver.preflight(argv)

    if ctx.classify_only:
        return agent_session_driver.run_classify_only(ctx)

    sel_res = agent_session_driver.select_queue(ctx)

    if ctx.dry_run:
        say("\ndry run -- no claude invocation.")
        return 0

    if not sel_res.candidates:
        say("\n== report ==")
        say("nothing eligible; no runs attempted. Reasons are listed above.")
        return 0

    attempted = 0
    total_cost = 0.0
    summary_rows: list[RunOutcome] = []

    for num, phase in sel_res.candidates:
        if attempted >= ctx.max_issues:
            say("\nreached --max-issues; stopping with issues still eligible.")
            break

        agent_session_driver.check_and_handle_rate_limit(
            env=credentials.agent_env(dict(os.environ), ctx.creds),
            say_fn=say,
        )

        run_repo_path = agent_session_driver.prepare_workspace(ctx, num)
        inv = agent_session_driver.invoke_agent(ctx, num, phase, run_repo_path, sel_res.open_prs, sel_res.board_item_ids)
        run_outcome = agent_session_driver.classify_and_record(ctx, inv, sel_res.open_prs)

        total_cost += run_outcome.cost
        attempted += 1
        summary_rows.append(run_outcome)

        if run_outcome.outcome in ("failed", "driver-fault", "budget-exhausted"):
            say("\nstopping the loop: outcome means an assumption is wrong, and retrying spends money on it.")
            break

    agent_session_driver.report_results(summary_rows, attempted, total_cost, ctx.state_dir)
    return 0
