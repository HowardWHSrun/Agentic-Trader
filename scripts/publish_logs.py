#!/usr/bin/env python3
"""Publish validated public research data without including private workspace files.

The first complete site deployment must already exist on origin/main. Subsequent
runs may commit and push only docs/data/research.json. GitHub Pages deployment is
not verified by this helper; a successful push is marked deployment_pending.
"""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


DATA_PATH = "docs/data/research.json"
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


def _verify_worktree(repo):
    output = _git(
        repo, ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        "Cannot inspect the site worktree.",
    ).stdout
    for entry in output.split("\0"):
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            raise PublicationError("The site contains an unsupported worktree change.")
        state, path = entry[:2], entry[3:]
        if "R" in state or "C" in state or "U" in state or state in {"AA", "DD"}:
            raise PublicationError("Resolve renamed, copied, or conflicted files before publication.")
        if path != DATA_PATH:
            raise PublicationError("Unrelated staged, modified, or untracked files block publication.")
    # Do not follow symlinks while writing a public data export.
    path = repo
    for component in Path(DATA_PATH).parts:
        path = path / component
        if path.is_symlink():
            raise PublicationError("The public data path must not contain symbolic links.")
    return not bool(output)


def _validator(repo):
    path = repo / "scripts" / "export_research.py"
    if not path.is_file() or path.is_symlink():
        raise PublicationError("The validated research exporter is missing or unsafe.")
    module_name = "_research_export_for_publication"
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
    except Exception:
        raise PublicationError(failure) from None


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
        if [path for path in files if path] != [DATA_PATH]:
            raise PublicationError("A pending commit changes files beyond the public research data.")
        tree = _git(repo, ["ls-tree", commit, "--", DATA_PATH], "Cannot inspect a pending data file.").stdout
        if not tree.startswith("100644 blob "):
            raise PublicationError("Pending public data must be a regular, nonexecutable JSON file.")
        contents = _git(repo, ["show", commit + ":" + DATA_PATH], "Cannot read a pending public data file.").stdout
        _validate_json(contents, validator, "A pending publish commit failed public-data privacy validation; it will not be pushed.")
    return commits


def _fetch(repo):
    _git(
        repo, ["fetch", "--no-tags", "--recurse-submodules=no", "origin", "refs/heads/main:" + UPSTREAM],
        "Fetching origin/main failed. The initial site deployment must already exist, and the remote must be reachable.",
    )


def _synchronize(repo, validator):
    _fetch(repo)
    ahead = _verify_pending_commits(repo, validator)
    behind = _git(repo, ["rev-list", "--count", "HEAD.." + UPSTREAM], "Cannot compare local and remote history.").stdout.strip()
    if behind != "0":
        if ahead:
            raise PublicationError("Local and remote history have diverged; publication will not rebase or force-push.")
        if not _verify_worktree(repo):
            raise PublicationError("Remote updates require a clean worktree before a fast-forward can proceed.")
        _git(repo, ["merge", "--ff-only", UPSTREAM], "A clean fast-forward to origin/main failed.")
    return bool(ahead)


def publish(logs, state_path, *, _repo=None, _allowed_origins=None):
    """Publish once; private test overrides are deliberately absent from the CLI."""
    repo = Path(_repo).resolve() if _repo is not None else Path(__file__).resolve().parents[1]
    allowed_origins = ALLOWED_ORIGINS if _allowed_origins is None else frozenset(_allowed_origins)
    logs, state_path = Path(logs).resolve(), Path(state_path).resolve()
    if _inside(state_path, repo) or _inside(state_path, logs):
        raise PublicationError("Publication state must be outside the public repository and the source-log directory.")
    state = {
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "status": "in_progress", "commit": None, "site_url": SITE_URL, "error": None,
    }
    try:
        _atomic_state(state_path, state)
        _verify_repository(repo, allowed_origins)
        _verify_worktree(repo)
        state["commit"] = _head(repo)
        validator = _validator(repo)
        _synchronize(repo, validator)
        # A fast-forward may update the exporter. Recheck the repository and
        # load the updated validator before creating or validating any new data.
        _verify_repository(repo, allowed_origins)
        _verify_worktree(repo)
        validator = _validator(repo)
        start_head = _head(repo)
        state["commit"] = start_head
        _run(
            repo,
            [sys.executable, str(repo / "scripts" / "export_research.py"), "--logs", str(logs), "--output", DATA_PATH],
            "The public research export failed validation; no new publish commit was created.",
        )
        if _head(repo) != start_head:
            raise PublicationError("The site history changed during export; publication stopped for review.")
        _verify_repository(repo, allowed_origins)
        _verify_worktree(repo)
        target = repo / DATA_PATH
        if not target.is_file():
            raise PublicationError("The exporter did not create the required public data file.")
        try:
            contents = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise PublicationError("The public data file is not readable UTF-8 JSON.") from None
        _validate_json(contents, validator, "The exported data failed public-data privacy validation.")
        _git(repo, ["add", "--", DATA_PATH], "Staging the public research data failed.")
        _verify_worktree(repo)
        changes = _git(
            repo, ["diff", "--cached", "--quiet", "--", DATA_PATH],
            "Cannot inspect staged public data.", allowed_codes=(0, 1),
        ).returncode == 1
        if changes:
            _git(
                repo, ["commit", "--only", "-m", COMMIT_PREFIX + state["attempted_at"], "--", DATA_PATH],
                "Committing the public data failed. The local data is preserved for review or retry.",
            )
        state["commit"] = _head(repo)
        _verify_repository(repo, allowed_origins)
        if not _verify_worktree(repo):
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
    except (PublicationError, OSError) as exc:
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
    arguments = parser.parse_args(argv)
    try:
        result = publish(arguments.logs, arguments.state)
    except PublicationError as exc:
        print("Publication failed: {}".format(exc), file=sys.stderr)
        return 1
    print("{}: {}; Pages deployment is not verified by this helper.".format(result["status"], result["commit"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
