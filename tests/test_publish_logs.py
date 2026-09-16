import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "publish_logs.py"
SPEC = importlib.util.spec_from_file_location("publish_logs", str(MODULE_PATH))
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)

EXPORTER = '''import argparse
import json
from pathlib import Path

def validate_public_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {"version"} or type(payload["version"]) is not int:
        raise ValueError("Private data rejected")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads((args.logs / "value.json").read_text())
    validate_public_payload(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, sort_keys=True) + "\\n")

if __name__ == "__main__":
    main()
'''

ENTRY_ID = "20260916T154500.000000Z-intraday"
CHECKED_AT = "2026-09-16T15:45:00Z"
PORTFOLIO_EXPORTER = '''import argparse
import json
from pathlib import Path

def validate_public_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {"updated_at", "positions"}:
        raise ValueError("Private extra fields rejected")
    if not isinstance(payload["updated_at"], str) or not isinstance(payload["positions"], list):
        raise ValueError("Invalid portfolio")
    for position in payload["positions"]:
        if set(position) != {"symbol", "quantity", "purchase_price"}:
            raise ValueError("Private position identifiers rejected")
        if not all(isinstance(value, str) for value in position.values()):
            raise ValueError("Expected decimal strings")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = json.loads(args.input.read_text())
    if set(source) != {"observed_at", "positions"}:
        raise ValueError("Unexpected private input")
    payload = {"updated_at": source["observed_at"], "positions": source["positions"]}
    validate_public_payload(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, sort_keys=True) + "\\n")

if __name__ == "__main__":
    main()
'''


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "site"
        self.remote = self.base / "remote.git"
        self.logs = self.base / "logs"
        self.logs.mkdir()
        self.state = self.base / "private" / "publication.json"
        self.run_git(self.base, "init", "--bare", str(self.remote))
        self.run_git(self.base, "init", "-b", "main", str(self.repo))
        self.git("config", "user.name", "Publisher Test")
        self.git("config", "user.email", "publisher@example.invalid")
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / "export_research.py").write_text(EXPORTER)
        (self.repo / "docs" / "data").mkdir(parents=True)
        (self.repo / publisher.DATA_PATH).write_text('{"version": 0}\n')
        (self.repo / "README.md").write_text("Test site\n")
        self.git("add", ".")
        self.git("commit", "-m", "Initial site")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-u", "origin", "main")
        self.set_data(1)

    def run_git(self, directory, *arguments):
        return subprocess.run(["git"] + list(arguments), cwd=str(directory), check=True, capture_output=True, text=True).stdout.strip()

    def git(self, *arguments):
        return self.run_git(self.repo, *arguments)

    def set_data(self, version):
        (self.logs / "value.json").write_text(json.dumps({"version": version}))

    def publish(self, portfolio_source=None):
        return publisher.publish(self.logs, self.state, portfolio_source=portfolio_source, _repo=self.repo, _allowed_origins={str(self.remote)})

    def assert_failed(self, portfolio_source=None):
        with self.assertRaises(publisher.PublicationError):
            self.publish(portfolio_source)
        state = json.loads(self.state.read_text())
        self.assertEqual(state["status"], "failed")
        self.assertTrue(state["error"])
        self.assertEqual(state["site_url"], publisher.SITE_URL)
        return state

    def test_publishes_only_data_and_marks_deployment_pending(self):
        source_before = (self.logs / "value.json").read_bytes()
        result = self.publish()
        self.assertEqual(result["status"], "deployment_pending")
        self.assertEqual(result["deployment_status"], "not_verified")
        self.assertEqual(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"), publisher.DATA_PATH)
        self.assertTrue(self.git("show", "-s", "--format=%s", "HEAD").startswith(publisher.COMMIT_PREFIX))
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.run_git(self.remote, "rev-parse", "main"))
        self.assertEqual((self.logs / "value.json").read_bytes(), source_before)

    def test_unrelated_dirty_staged_and_untracked_files_are_blocked(self):
        original_head = self.git("rev-parse", "HEAD")
        readme = self.repo / "README.md"
        readme.write_text("Unrelated edit\n")
        self.assert_failed()
        self.git("add", "README.md")
        self.assert_failed()
        self.git("reset", "--hard", "HEAD")
        untracked = self.repo / "private.csv"
        untracked.write_text("Test data that must never publish\n")
        self.assert_failed()
        self.assertEqual(self.git("rev-parse", "HEAD"), original_head)
        self.assertFalse((self.repo / ".git" / "index.lock").exists())

    def test_wrong_origin_and_push_url_are_blocked(self):
        self.git("remote", "set-url", "origin", "https://example.invalid/wrong.git")
        self.assert_failed()
        self.git("remote", "set-url", "origin", str(self.remote))
        self.git("remote", "set-url", "--push", "origin", "https://example.invalid/wrong.git")
        self.assert_failed()

    def test_non_main_branch_is_blocked(self):
        self.git("switch", "-c", "draft")
        self.assert_failed()

    def test_no_change_is_idempotent(self):
        self.publish()
        original_head = self.git("rev-parse", "HEAD")
        result = self.publish()
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(result["commit"], original_head)
        self.assertEqual(self.git("rev-parse", "HEAD"), original_head)

    def test_failed_push_retries_own_commit_without_an_extra_commit(self):
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        state = self.assert_failed()
        pending_head = self.git("rev-parse", "HEAD")
        self.assertEqual(state["commit"], pending_head)
        self.assertEqual(self.git("rev-list", "--count", "origin/main..HEAD"), "1")
        hook.unlink()
        result = self.publish()
        self.assertEqual(result["status"], "deployment_pending")
        self.assertEqual(result["commit"], pending_head)
        self.assertEqual(self.run_git(self.remote, "rev-parse", "main"), pending_head)

    def remote_update(self):
        checkout = self.base / "other-checkout"
        self.run_git(self.base, "clone", "--branch", "main", str(self.remote), str(checkout))
        self.run_git(checkout, "config", "user.name", "Other Test")
        self.run_git(checkout, "config", "user.email", "other@example.invalid")
        (checkout / "README.md").write_text("A newer remote site description\n")
        self.run_git(checkout, "add", "README.md")
        self.run_git(checkout, "commit", "-m", "Update site remotely")
        self.run_git(checkout, "push", "origin", "main")

    def test_clean_remote_update_fast_forwards_before_data_publication(self):
        self.remote_update()
        result = self.publish()
        self.assertEqual(result["status"], "deployment_pending")
        self.assertEqual((self.repo / "README.md").read_text(), "A newer remote site description\n")
        self.assertEqual(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"), publisher.DATA_PATH)

    def test_divergent_history_is_not_rebased_or_force_pushed(self):
        (self.repo / publisher.DATA_PATH).write_text('{"version": 1}\n')
        self.git("add", publisher.DATA_PATH)
        self.git("commit", "-m", publisher.COMMIT_PREFIX + "valid pending data")
        local_before = self.git("rev-parse", "HEAD")
        self.remote_update()
        remote_before = self.run_git(self.remote, "rev-parse", "main")
        state = self.assert_failed()
        self.assertIn("diverged", state["error"])
        self.assertEqual(self.git("rev-parse", "HEAD"), local_before)
        self.assertEqual(self.run_git(self.remote, "rev-parse", "main"), remote_before)

    def test_remote_update_does_not_overwrite_dirty_public_data(self):
        (self.repo / publisher.DATA_PATH).write_text('{"version": 8}\n')
        self.remote_update()
        self.assert_failed()
        self.assertEqual((self.repo / publisher.DATA_PATH).read_text(), '{"version": 8}\n')

    def test_push_does_not_include_unrelated_annotated_tags(self):
        self.git("tag", "-a", "local-review-only", "-m", "Do not publish this tag")
        self.git("config", "push.followTags", "true")
        self.publish()
        result = subprocess.run(["git", "show-ref", "--verify", "refs/tags/local-review-only"], cwd=str(self.remote), capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_unrelated_local_commit_is_not_pushed(self):
        (self.repo / "README.md").write_text("Unpublished site edit\n")
        self.git("add", "README.md")
        self.git("commit", "-m", "Unrelated change")
        remote_before = self.run_git(self.remote, "rev-parse", "main")
        self.assert_failed()
        self.assertEqual(self.run_git(self.remote, "rev-parse", "main"), remote_before)

    def test_publish_prefix_cannot_hide_changes_to_other_files(self):
        (self.repo / "README.md").write_text("Unrelated content\n")
        self.git("add", "README.md")
        self.git("commit", "-m", publisher.COMMIT_PREFIX + "pretend")
        self.assert_failed()

    def test_historical_private_data_blocks_retry_even_when_current_data_is_clean(self):
        target = self.repo / publisher.DATA_PATH
        target.write_text('{"secret": "synthetic-test-only"}\n')
        self.git("add", publisher.DATA_PATH)
        self.git("commit", "-m", publisher.COMMIT_PREFIX + "invalid historical payload")
        target.write_text('{"version": 1}\n')
        self.git("add", publisher.DATA_PATH)
        self.git("commit", "-m", publisher.COMMIT_PREFIX + "cleaned payload")
        state = self.assert_failed()
        self.assertIn("privacy validation", state["error"])
        self.assertNotIn("synthetic-test-only", self.state.read_text())

    def test_export_validation_failure_leaves_history_and_logs_unchanged(self):
        source = self.logs / "value.json"
        source.write_text('{"secret": "synthetic-test-only"}')
        original = source.read_bytes()
        previous_head = self.git("rev-parse", "HEAD")
        state = self.assert_failed()
        self.assertEqual(self.git("rev-parse", "HEAD"), previous_head)
        self.assertEqual(source.read_bytes(), original)
        self.assertNotIn("synthetic-test-only", json.dumps(state))

    def test_state_cannot_be_written_inside_public_repo_or_source_logs(self):
        for unsafe in (self.repo / "state.json", self.logs / "state.json"):
            with self.subTest(path=unsafe):
                with self.assertRaises(publisher.PublicationError):
                    publisher.publish(self.logs, unsafe, _repo=self.repo, _allowed_origins={str(self.remote)})
                self.assertFalse(unsafe.exists())

    def install_portfolio_fixture(self, observed_at=CHECKED_AT):
        # A deployed exporter is part of the site baseline, never a data-publish change.
        exporter = EXPORTER.replace('set(payload) != {"version"}', 'set(payload) not in ({"version"}, {"version", "entries"})')
        (self.repo / "scripts" / "export_research.py").write_text(exporter)
        (self.repo / "scripts" / "export_portfolio.py").write_text(PORTFOLIO_EXPORTER)
        self.git("add", "scripts")
        self.git("commit", "-m", "Deploy portfolio exporter")
        self.git("push", "origin", "main")
        (self.logs / "value.json").write_text(json.dumps({"version": 1, "entries": [{"id": ENTRY_ID, "checked_at": CHECKED_AT}]}))
        self.portfolio_source = self.base / "private-portfolio.json"
        self.portfolio_source.write_text(json.dumps({
            "observed_at": observed_at,
            "positions": [{"symbol": "MSFT", "quantity": "0.125", "purchase_price": "500.00"}],
        }))
        return self.portfolio_source

    def test_optional_portfolio_publishes_only_validated_data_and_matching_snapshot(self):
        source = self.install_portfolio_fixture("2026-09-16T10:45:00-05:00")
        source_before = source.read_bytes()
        result = self.publish(source)
        archive = publisher.PORTFOLIO_HISTORY + ENTRY_ID + ".json"
        self.assertEqual(result["portfolio_history_status"], "matched")
        self.assertEqual(result["portfolio_history_path"], archive)
        self.assertEqual(set(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()),
                         {publisher.DATA_PATH, publisher.PORTFOLIO_PATH, archive})
        self.assertEqual((self.repo / archive).read_bytes(), (self.repo / publisher.PORTFOLIO_PATH).read_bytes())
        self.assertNotIn("observed_at", (self.repo / publisher.PORTFOLIO_PATH).read_text())
        self.assertEqual(source.read_bytes(), source_before)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.publish(source)["status"], "unchanged")

    def test_portfolio_is_not_exported_without_flag_and_dirty_portfolio_is_blocked(self):
        self.install_portfolio_fixture()
        self.publish()
        self.assertFalse((self.repo / publisher.PORTFOLIO_PATH).exists())
        (self.repo / publisher.PORTFOLIO_PATH).write_text('{"private": "not-authorized-by-flag"}')
        self.assert_failed()

    def test_mismatched_observation_skips_history_without_pairing_wrong_prices(self):
        source = self.install_portfolio_fixture("2026-09-16T15:44:59Z")
        result = self.publish(source)
        self.assertEqual(result["portfolio_history_status"], "skipped_timestamp_mismatch")
        self.assertIsNone(result["portfolio_history_path"])
        self.assertFalse((self.repo / publisher.PORTFOLIO_HISTORY).exists())
        self.assertEqual(set(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()),
                         {publisher.DATA_PATH, publisher.PORTFOLIO_PATH})

    def test_portfolio_exporter_rejection_preserves_private_source_and_remote(self):
        source = self.install_portfolio_fixture()
        payload = json.loads(source.read_text())
        payload["positions"][0]["account_id"] = "synthetic-secret-id"
        source.write_text(json.dumps(payload))
        before = source.read_bytes()
        remote_before = self.run_git(self.remote, "rev-parse", "main")
        state = self.assert_failed(source)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(self.run_git(self.remote, "rev-parse", "main"), remote_before)
        self.assertFalse((self.repo / publisher.PORTFOLIO_PATH).exists())
        self.assertNotIn("synthetic-secret-id", json.dumps(state))

    def test_portfolio_flag_does_not_allow_unrelated_changes(self):
        source = self.install_portfolio_fixture()
        (self.repo / "README.md").write_text("An unrelated site edit")
        self.git("add", "README.md")
        self.assert_failed(source)

    def test_portfolio_and_history_symlinks_are_blocked_before_export(self):
        source = self.install_portfolio_fixture()
        outside = self.base / "outside"
        outside.mkdir()
        for path in (publisher.PORTFOLIO_PATH, publisher.PORTFOLIO_HISTORY.rstrip("/")):
            with self.subTest(path=path):
                target = self.repo / path
                target.symlink_to(outside, target_is_directory=True)
                self.assert_failed(source)
                target.unlink()
        self.assertEqual(list(outside.iterdir()), [])

    def test_existing_portfolio_snapshot_is_never_overwritten(self):
        source = self.install_portfolio_fixture()
        self.publish(source)
        archive = self.repo / (publisher.PORTFOLIO_HISTORY + ENTRY_ID + ".json")
        before = archive.read_bytes()
        remote_before = self.run_git(self.remote, "rev-parse", "main")
        payload = json.loads(source.read_text())
        payload["positions"][0]["quantity"] = "0.25"
        source.write_text(json.dumps(payload))
        self.assert_failed(source)
        self.assertEqual(archive.read_bytes(), before)
        self.assertEqual(self.run_git(self.remote, "rev-parse", "main"), remote_before)

    def test_historical_private_portfolio_blocks_retry_after_cleanup(self):
        source = self.install_portfolio_fixture()
        target = self.repo / publisher.PORTFOLIO_PATH
        target.write_text('{"account_id": "synthetic-secret-id"}')
        self.git("add", publisher.PORTFOLIO_PATH)
        self.git("commit", "-m", publisher.COMMIT_PREFIX + "invalid portfolio")
        target.write_text(json.dumps({"updated_at": CHECKED_AT, "positions": []}))
        self.git("add", publisher.PORTFOLIO_PATH)
        self.git("commit", "-m", publisher.COMMIT_PREFIX + "cleaned portfolio")
        state = self.assert_failed(source)
        self.assertIn("privacy validation", state["error"])
        self.assertNotIn("synthetic-secret-id", json.dumps(state))

    def test_failed_portfolio_push_can_retry_validated_history_without_flag(self):
        source = self.install_portfolio_fixture()
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.assert_failed(source)
        pending = self.git("rev-parse", "HEAD")
        hook.unlink()
        result = self.publish()
        self.assertEqual(result["status"], "deployment_pending")
        self.assertEqual(result["commit"], pending)

    def test_pending_snapshot_with_wrong_entry_is_not_pushed(self):
        source = self.install_portfolio_fixture()
        self.publish(source)
        original = self.repo / (publisher.PORTFOLIO_HISTORY + ENTRY_ID + ".json")
        wrong = self.repo / (publisher.PORTFOLIO_HISTORY + "20260916T154600.000000Z-intraday.json")
        wrong.write_bytes(original.read_bytes())
        self.git("add", str(wrong.relative_to(self.repo)))
        self.git("commit", "-m", publisher.COMMIT_PREFIX + "incorrect historical pairing")
        state = self.assert_failed(source)
        self.assertIn("does not match", state["error"])

    def test_private_portfolio_source_inside_site_is_rejected(self):
        path = self.repo / "private-source.json"
        with self.assertRaises(publisher.PublicationError):
            self.publish(path)
        self.assertFalse(path.exists())

    def test_state_cannot_overwrite_private_portfolio_input(self):
        source = self.install_portfolio_fixture()
        before = source.read_bytes()
        with self.assertRaises(publisher.PublicationError):
            publisher.publish(self.logs, source, portfolio_source=source, _repo=self.repo, _allowed_origins={str(self.remote)})
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
