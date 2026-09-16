#!/usr/bin/env python3
"""Publish validated public research data without including private workspace files.

The first complete site deployment must already exist on origin/main. Subsequent
runs may commit and push only validated research data and, when requested,
validated public portfolio data. GitHub Pages deployment is not verified by this
helper; a successful push is marked deployment_pending.
"""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


DATA_PATH = "docs/data/research.json"
PORTFOLIO_PATH = "docs/data/portfolio.json"
ENTRY_ID = re.compile(r"\d{8}T\d{6}\.\d{6}Z-(?:baseline_archive|intraday|after_close|failed_check)")
PORTFOLIO_HISTORY = "docs/data/portfolios/"
COMMIT_PREFIX = "Publish research log: "
SITE_URL = "https://howardwhsrun.github.io/Agentic-Trader/"
ALLOWED_ORIGINS = frozenset({
    "https://github.com/HowardWHSrun/Agentic-Trader.git",
    "git@github.com:HowardWHSrun/Agentic-Trader.git",
    "ssh://git@github.com/HowardWHSrun/Agentic-Trader.git",
})
UPSTREAM = "refs/remotes/origin/main"


class PublicationError(RuntimeError):
    """A safe, concise failure message suitable for the private state file."""


def _inside(path, directory):
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _atomic_state(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=str(path.parent), delete=False) as handle:
            temporary = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _run(repo, arguments, failure, allowed_codes=(0,)):
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_PAGER"] = "cat"
    try:
        completed = subprocess.run(
            arguments, cwd=str(repo), env=environment, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise PublicationError(failure) from None
    if completed.returncode not in allowed_codes:
        # Never include subprocess output: git/exporter diagnostics may contain
        # private local paths, log content, or credential-bearing configuration.
        raise PublicationError(failure)
    return completed


def _git(repo, arguments, failure, allowed_codes=(0,)):
    return _run(repo, ["git"] + arguments, failure, allowed_codes)


def _head(repo):
    return _git(repo, ["rev-parse", "HEAD"], "Cannot read the current commit.").stdout.strip()


def _verify_repository(repo, allowed_origins):
    actual = _git(repo, ["rev-parse", "--show-toplevel"], "The site is not an initialized Git repository.").stdout.strip()
    if Path(actual).resolve() != repo:
        raise PublicationError("The helper must run from the site repository, not a parent repository.")
    branch = _git(repo, ["symbolic-ref", "--quiet", "--short", "HEAD"], "The site must be on its main branch.").stdout.strip()
    if branch != "main":
        raise PublicationError("The site must be on its main branch.")
    for options in (["remote", "get-url", "--all", "origin"], ["remote", "get-url", "--push", "--all", "origin"]):
        urls = _git(repo, options, "Cannot verify the origin remote.").stdout.splitlines()
        if len(urls) != 1 or urls[0] not in allowed_origins:
            raise PublicationError("Origin must point only to the approved Agentic-Trader repository.")


def _history_path(path):
    return path.startswith(PORTFOLIO_HISTORY) and path.endswith(".json") and ENTRY_ID.fullmatch(path[len(PORTFOLIO_HISTORY):-5]) is not None


def _allowed_data_path(path, portfolio=False):
    return path == DATA_PATH or (portfolio and (path == PORTFOLIO_PATH or _history_path(path)))


def _safe_data_path(repo, relative):
    path = repo
    for component in Path(relative).parts:
        path = path / component
        if path.is_symlink():
            raise PublicationError("The public data path must not contain symbolic links.")
    return path


def _worktree_paths(repo, portfolio=False):
    output = _git(
        repo, ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        "Cannot inspect the site worktree.",
    ).stdout
    paths = []
    for entry in output.split("\0"):
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            raise PublicationError("The site contains an unsupported worktree change.")
        state, path = entry[:2], entry[3:]
        if "R" in state or "C" in state or "U" in state or state in {"AA", "DD"}:
            raise PublicationError("Resolve renamed, copied, or conflicted files before publication.")
        if not _allowed_data_path(path, portfolio):
            raise PublicationError("Unrelated staged, modified, or untracked files block publication.")
        _safe_data_path(repo, path)
        paths.append(path)
    # Do not follow symlinks while writing a public data export.
    _safe_data_path(repo, DATA_PATH)
    if portfolio:
        _safe_data_path(repo, PORTFOLIO_PATH)
        _safe_data_path(repo, PORTFOLIO_HISTORY.rstrip("/"))
    return paths


def _verify_worktree(repo, portfolio=False):
    return not _worktree_paths(repo, portfolio)


def _validator(repo, kind="research"):
    path = repo / "scripts" / ("export_" + kind + ".py")
    if not path.is_file() or path.is_symlink():
        raise PublicationError("The validated " + kind + " exporter is missing or unsafe.")
    module_name = "_" + kind + "_export_for_publication"
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            raise ValueError("No module loader")
        module = importlib.util.module_from_spec(spec)
        previous = sys.modules.get(module_name)
        sys.modules[module_name] = module
        previous_bytecode = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = previous_bytecode
            if previous is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous
        validator = getattr(module, "validate_public_payload", None)
        if not callable(validator):
            raise ValueError("Missing payload validator")
        return validator
    except Exception:
        raise PublicationError("The exporter must provide a working public-payload privacy validator.") from None


def _validate_json(contents, validator, failure):
    try:
        payload = json.loads(contents)
        if validator(payload) is False:
            raise ValueError("Public payload was rejected")
        return payload
    except Exception:
        raise PublicationError(failure) from None


def _observation_time(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp required")
    # Broker RFC3339 fractions may have fewer than three or more than six digits.
    value = re.sub(r"\.(\d+)(?=Z$|[+-]\d{2}:\d{2}$)",
                   lambda match: "." + match.group(1)[:6].ljust(6, "0"), value)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Timezone required")
    return parsed.astimezone(timezone.utc)


def _required_portfolio_snapshot(logs, portfolio_source):
    """Check the latest archived opt-in before any public checkout mutation."""
    try:
        entries = []
        for path in logs.glob("*/*/review.json"):
            review = json.loads(path.read_text(encoding="utf-8"))
            entries.append((_observation_time(review["checked_at"]), path.parent.name, path.parent))
        if not entries:
            return None
        checked_at, entry_id, folder = max(entries, key=lambda entry: entry[:2])
        config_path = folder / "config.json"
        if not config_path.exists():
            return None  # Older archives did not require a portfolio opt-in.
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config.get("position_management", {}).get("public_portfolio_reporting", {}).get("enabled") is not True:
            return None
        if not ENTRY_ID.fullmatch(entry_id):
            raise ValueError("Invalid entry id")
        if portfolio_source is None:
            raise PublicationError("The latest journal requires --portfolio-source for its authorized public portfolio snapshot.")
        source = json.loads(portfolio_source.read_text(encoding="utf-8"))
        if _observation_time(source["observed_at"]) != checked_at:
            raise PublicationError("The required portfolio source timestamp must match the latest journal review; public files were not changed.")
        return PORTFOLIO_HISTORY + entry_id + ".json"
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
        raise PublicationError("Cannot verify the latest journal's public portfolio requirement and matching source.") from None


def _snapshot_path(research, portfolio):
    """Only pair a portfolio observation with the same journal check."""
    try:
        entry = research["entries"][0]
        if not isinstance(entry["id"], str) or not ENTRY_ID.fullmatch(entry["id"]):
            raise ValueError("Invalid entry id")
        times = [_observation_time(value) for value in (entry["checked_at"], portfolio["updated_at"])]
        if times[0] != times[1]:
            return None
        return PORTFOLIO_HISTORY + entry["id"] + ".json"
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        raise PublicationError("Cannot safely match portfolio data to the latest research entry.") from None


def _prepare_exports(repo, logs, portfolio_source, validator, portfolio_validator, required_snapshot):
    """Validate both exports and their pairing before replacing public files."""
    with tempfile.TemporaryDirectory(prefix="agentic-trader-publish-") as staging:
        target = Path(staging) / "research.json"
        _run(repo, [sys.executable, str(repo / "scripts" / "export_research.py"), "--logs", str(logs), "--output", str(target)],
             "The public research export failed validation; no new publish commit was created.")
        contents = target.read_text(encoding="utf-8")
        research = _validate_json(contents, validator, "The exported data failed public-data privacy validation.")
        portfolio_contents, snapshot_path = None, None
        if portfolio_source is not None:
            portfolio_target = Path(staging) / "portfolio.json"
            _run(repo, [sys.executable, str(repo / "scripts" / "export_portfolio.py"), "--input", str(portfolio_source), "--output", str(portfolio_target)],
                 "The public portfolio export failed validation; no new publish commit was created.")
            portfolio_contents = portfolio_target.read_text(encoding="utf-8")
            public_portfolio = _validate_json(portfolio_contents, portfolio_validator, "The exported portfolio failed public-data privacy validation.")
            snapshot_path = _snapshot_path(research, public_portfolio)
        if required_snapshot is not None and snapshot_path != required_snapshot:
            raise PublicationError("The required dated portfolio snapshot does not match the latest journal; public files were not changed.")
        return contents, portfolio_contents, snapshot_path


def _commit_contents(repo, commit, path):
    tree = _git(repo, ["ls-tree", commit, "--", path], "Cannot inspect a pending data file.").stdout
    if not tree.startswith("100644 blob "):
        raise PublicationError("Pending public data must be a regular, nonexecutable JSON file.")
    return _git(repo, ["show", commit + ":" + path], "Cannot read a pending public data file.").stdout


def _verify_pending_commits(repo, validator):
    commits = _git(repo, ["rev-list", "--reverse", UPSTREAM + "..HEAD"], "Cannot inspect local commits.").stdout.splitlines()
    for commit in commits:
        description = _git(
            repo, ["show", "-s", "--format=%s%n%P", commit], "Cannot inspect a pending commit.",
        ).stdout.splitlines()
        if len(description) != 2 or not description[0].startswith(COMMIT_PREFIX) or len(description[1].split()) != 1:
            raise PublicationError("Unrelated local commits block publication; only prior research-log publish commits may be retried.")
        files = _git(
            repo, ["diff-tree", "--no-commit-id", "--name-only", "-z", "-r", commit],
            "Cannot inspect files in a pending commit.",
        ).stdout.split("\0")
        paths = [path for path in files if path]
        if not paths or any(not _allowed_data_path(path, True) for path in paths):
            raise PublicationError("A pending commit changes files beyond the public research data.")
        portfolio_validator = _validator(repo, "portfolio") if any(path != DATA_PATH for path in paths) else None
        for path in paths:
            contents = _commit_contents(repo, commit, path)
            payload = _validate_json(contents, validator if path == DATA_PATH else portfolio_validator,
                                     "A pending publish commit failed public-data privacy validation; it will not be pushed.")
            if _history_path(path):
                existing = _git(repo, ["ls-tree", commit + "^", "--", path], "Cannot inspect historical portfolio data.").stdout
                if existing:
                    raise PublicationError("Historical portfolio snapshots are immutable; a pending commit rewrites one.")
                research = _validate_json(_commit_contents(repo, commit, DATA_PATH), validator, "Pending research data failed privacy validation.")
                current = _commit_contents(repo, commit, PORTFOLIO_PATH)
                _validate_json(current, portfolio_validator, "Pending portfolio data failed privacy validation.")
                if path != _snapshot_path(research, payload) or contents != current:
                    raise PublicationError("A pending historical portfolio snapshot does not match its research entry and current portfolio.")
    return commits


def _fetch(repo):
    _git(
        repo, ["fetch", "--no-tags", "--recurse-submodules=no", "origin", "refs/heads/main:" + UPSTREAM],
        "Fetching origin/main failed. The initial site deployment must already exist, and the remote must be reachable.",
    )


def _synchronize(repo, validator, portfolio=False):
    _fetch(repo)
    ahead = _verify_pending_commits(repo, validator)
    behind = _git(repo, ["rev-list", "--count", "HEAD.." + UPSTREAM], "Cannot compare local and remote history.").stdout.strip()
    if behind != "0":
        if ahead:
            raise PublicationError("Local and remote history have diverged; publication will not rebase or force-push.")
        if not _verify_worktree(repo, portfolio):
            raise PublicationError("Remote updates require a clean worktree before a fast-forward can proceed.")
        _git(repo, ["merge", "--ff-only", UPSTREAM], "A clean fast-forward to origin/main failed.")
    return bool(ahead)


def publish(logs, state_path, *, portfolio_source=None, _repo=None, _allowed_origins=None):
    """Publish once; private test overrides are deliberately absent from the CLI."""
    repo = Path(_repo).resolve() if _repo is not None else Path(__file__).resolve().parents[1]
    allowed_origins = ALLOWED_ORIGINS if _allowed_origins is None else frozenset(_allowed_origins)
    logs, state_path = Path(logs).resolve(), Path(state_path).resolve()
    portfolio_source = Path(portfolio_source).resolve() if portfolio_source is not None else None
    if portfolio_source is not None and _inside(portfolio_source, repo):
        raise PublicationError("The private portfolio source must be outside the public repository.")
    if portfolio_source is not None and state_path == portfolio_source:
        raise PublicationError("Publication state must not overwrite the private portfolio source.")
    include_portfolio = portfolio_source is not None
    if _inside(state_path, repo) or _inside(state_path, logs):
        raise PublicationError("Publication state must be outside the public repository and the source-log directory.")
    state = {
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "status": "in_progress", "commit": None, "site_url": SITE_URL, "error": None,
    }
    try:
        _atomic_state(state_path, state)
        required_snapshot = _required_portfolio_snapshot(logs, portfolio_source)
        _verify_repository(repo, allowed_origins)
        _verify_worktree(repo, include_portfolio)
        state["commit"] = _head(repo)
        validator = _validator(repo)
        _synchronize(repo, validator, include_portfolio)
        # A fast-forward may update the exporter. Recheck the repository and
        # load the updated validator before creating or validating any new data.
        _verify_repository(repo, allowed_origins)
        _verify_worktree(repo, include_portfolio)
        validator = _validator(repo)
        start_head = _head(repo)
        state["commit"] = start_head
        required_snapshot = _required_portfolio_snapshot(logs, portfolio_source)
        portfolio_validator = _validator(repo, "portfolio") if include_portfolio else None
        contents, portfolio_contents, snapshot_path = _prepare_exports(
            repo, logs, portfolio_source, validator, portfolio_validator, required_snapshot)
        if _head(repo) != start_head:
            raise PublicationError("The site history changed during export; publication stopped for review.")
        _verify_repository(repo, allowed_origins)
        _verify_worktree(repo, include_portfolio)
        if snapshot_path:
            snapshot = _safe_data_path(repo, snapshot_path)
            if snapshot.exists() and snapshot.read_bytes() != portfolio_contents.encode("utf-8"):
                raise PublicationError("The historical portfolio snapshot already exists with different contents; it will not be overwritten.")
        _safe_data_path(repo, DATA_PATH).write_text(contents, encoding="utf-8")
        if include_portfolio:
            portfolio_target = _safe_data_path(repo, PORTFOLIO_PATH)
            portfolio_target.write_text(portfolio_contents, encoding="utf-8")
            state["portfolio_history_path"] = snapshot_path
            state["portfolio_history_status"] = "matched" if snapshot_path else "skipped_timestamp_mismatch"
            if snapshot_path:
                snapshot = _safe_data_path(repo, snapshot_path)
                if not snapshot.exists():
                    snapshot.parent.mkdir(parents=True, exist_ok=True)
                    # Exclusive creation prevents replacing an immutable observation.
                    with snapshot.open("xb") as handle:
                        handle.write(portfolio_target.read_bytes())
        changed_paths = _worktree_paths(repo, include_portfolio)
        for path in changed_paths:
            target = _safe_data_path(repo, path)
            if not target.is_file() or target.stat().st_mode & 0o111:
                raise PublicationError("Public data must be a regular, nonexecutable JSON file.")
            text = target.read_text(encoding="utf-8")
            _validate_json(text, validator if path == DATA_PATH else portfolio_validator,
                           "Changed public data failed privacy validation.")
            if _history_path(path):
                existing = _git(repo, ["ls-tree", "HEAD", "--", path], "Cannot inspect historical portfolio data.").stdout
                if existing or path != snapshot_path or text != portfolio_contents:
                    raise PublicationError("Only the new matching immutable portfolio snapshot may be published.")
        publish_paths = sorted(set(changed_paths + [DATA_PATH] + ([PORTFOLIO_PATH] if include_portfolio else [])))
        _git(repo, ["add", "--"] + publish_paths, "Staging the public research data failed.")
        _verify_worktree(repo, include_portfolio)
        changes = _git(
            repo, ["diff", "--cached", "--quiet", "--"] + publish_paths,
            "Cannot inspect staged public data.", allowed_codes=(0, 1),
        ).returncode == 1
        if changes:
            _git(
                repo, ["commit", "--only", "-m", COMMIT_PREFIX + state["attempted_at"], "--"] + publish_paths,
                "Committing the public data failed. The local data is preserved for review or retry.",
            )
        state["commit"] = _head(repo)
        _verify_repository(repo, allowed_origins)
        if not _verify_worktree(repo, include_portfolio):
            raise PublicationError("The public data changed during commit; publication stopped before pushing.")
        pending = _verify_pending_commits(repo, validator)
        if _head(repo) != state["commit"]:
            raise PublicationError("The site history changed before push; publication stopped for review.")
        if pending:
            _git(
                repo,
                ["-c", "push.followTags=false", "push", "--no-follow-tags", "--recurse-submodules=no", "origin", state["commit"] + ":refs/heads/main"],
                "Pushing failed. Validated local publish commits are preserved for a safe retry; no force-push was attempted.",
            )
            state["status"] = "deployment_pending"
            state["deployment_status"] = "not_verified"
        else:
            state["status"] = "unchanged"
            state["deployment_status"] = "not_verified"
        _atomic_state(state_path, state)
        return state
    except (PublicationError, OSError, UnicodeError) as exc:
        failure = str(exc) if isinstance(exc, PublicationError) else "A local file operation failed; no deployment success has been assumed."
        state["status"] = "failed"
        state["error"] = failure
        try:
            _atomic_state(state_path, state)
        except OSError:
            raise PublicationError("Publication failed, and its private state file could not be updated.") from None
        raise PublicationError(failure) from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", required=True, type=Path, help="Private source-log directory")
    parser.add_argument("--state", required=True, type=Path, help="Private state JSON outside the site repository and source logs")
    parser.add_argument("--portfolio-source", type=Path, help="Optional private input for the validated public portfolio exporter")
    arguments = parser.parse_args(argv)
    try:
        result = publish(arguments.logs, arguments.state, portfolio_source=arguments.portfolio_source)
    except PublicationError as exc:
        print("Publication failed: {}".format(exc), file=sys.stderr)
        return 1
    print("{}: {}; Pages deployment is not verified by this helper.".format(result["status"], result["commit"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
