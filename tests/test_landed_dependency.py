import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / ".github"))
from landed_dependency import bind


class LandedDependency(unittest.TestCase):
    def setUp(self):
        data = json.loads((root / "tests/fixtures/landed-dependency.json").read_text())
        self.run, self.pull, self.commit = data["run"], data["pull"], data["commit"]
        self.repo, self.sha = self.run["repository"]["full_name"], self.run["head_sha"]
        self.routes = {
            "actions/runs/45895050659/attempts/1": self.run,
            f"commits/{self.sha}/pulls?per_page=100&page=1": data["associated"],
            "pulls/108": self.pull,
            f"git/commits/{self.sha}": self.commit,
        }
        self.read = Mock(side_effect=self.routes.__getitem__)

    def native(self):
        return bind(self.repo, "workflow_run", {"workflow_run": self.run}, self.read)

    def recovery(self, source="45895050659/1"):
        return bind(self.repo, "workflow_dispatch", {"inputs": {"codeql_attempt": source}}, self.read)

    def test_original_notification_and_recovery_bind_the_same_landed_commit(self):
        result = self.native()
        self.assertEqual(result, self.recovery())
        self.assertEqual(result, {
            "pr": 108, "base": self.commit["parents"][0]["sha"],
            "head": self.pull["head"]["sha"], "sha": self.sha,
            "codeql_run": 45895050659, "codeql_attempt": 1,
        })

    def test_failed_or_other_upstream_never_selects_source(self):
        for field, value in (("event", "pull_request"), ("path", ".github/workflows/codeql.yml"),
                             ("head_branch", "main"), ("conclusion", "failure"),
                             ("head_repository", {"full_name": "elsewhere/fork"})):
            old = self.run[field]
            self.run[field] = value
            with self.assertRaises(ValueError):
                self.native()
            self.run[field] = old
        self.read.assert_not_called()

    def test_mismatched_attempt_and_malformed_recovery(self):
        self.run["run_attempt"] = 2
        with self.assertRaises(ValueError):
            self.recovery()
        with self.assertRaises(ValueError):
            self.recovery("45895050659/0")

    def test_human_merge_is_skipped_and_cannot_be_recovered_as_a_bot_merge(self):
        self.pull["merged_by"]["login"] = "owner"
        self.assertIsNone(self.native())
        with self.assertRaises(ValueError):
            self.recovery()

    def test_wrong_or_ambiguous_merge_cannot_select_code(self):
        self.commit["parents"].reverse()
        with self.assertRaises(ValueError):
            self.native()
        key = f"commits/{self.sha}/pulls?per_page=100&page=1"
        self.routes[key] *= 2
        with self.assertRaises(ValueError):
            self.native()


if __name__ == "__main__":
    unittest.main()
