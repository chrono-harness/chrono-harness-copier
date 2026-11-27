import hashlib
import json
import os
import runpy
import tempfile
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


class LandedReports(unittest.TestCase):
    def setUp(self):
        self.stage = tempfile.TemporaryDirectory()
        self.addCleanup(self.stage.cleanup)
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.stage.name)
        self.profile = Path(".chrono-harness/ci/check.json")
        self.profile.parent.mkdir(parents=True)
        Path(".chrono-harness/config.json").write_text(json.dumps(
            {"canonical_check":{"profile":str(self.profile)}}
        ))
        self.profile.write_text('{"policy":{}}')
        script, = (root / "scaffold/.github").glob("*landed_report.py*")
        self.inspect = runpy.run_path(str(script))["landed_report"]
        self.slot = Path(".chrono-harness/state/collection/check.json")
        self.slot.parent.mkdir(parents=True)
        self.before, self.after = "before", "after"
        self.response = {"request_id":"R", "status":"passed"}
        self.report = {
            "schema":"chrono-check-report/v1", "request":{"request_id":"R","base":"before","candidate":"after"},
            "response":self.response, "publication":{"exit_code":0,"slot":str(self.slot),"originals":[]},
            "judge":{"exit_code":0,"failure":None,"owned_work_joined":True}
        }
        self.reference = False

    def original(self, name, raw):
        path = Path(".chrono-harness/state/preparation") / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
        return {"path":str(path), "sha256":hashlib.sha256(raw).hexdigest()}

    def read(self, request):
        op = request["operation"]
        if op == "scoped-check-profile":
            self.assertEqual(request["path"], str(self.profile))
            return {"report_path":str(self.slot), "retained_reference":self.reference}
        if op == "read-bounded-text":
            self.assertEqual(request["path"], str(self.slot))
            return self.slot.read_text()
        ref = request["original"]
        raw = Path(ref["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ValueError("digest")
        if op == "verify-original":
            return None
        self.assertEqual(op, "read-original")
        return raw.decode()

    def check(self):
        paths = []
        self.inspect(self.before, self.after, paths, self.read)
        return paths

    def test_inline_range_and_status(self):
        self.slot.write_text(json.dumps(self.report))
        self.assertEqual(self.check(), [self.slot.parent])
        self.report["request"]["base"] = "wrong"
        self.slot.write_text(json.dumps(self.report))
        with self.assertRaises(ValueError):
            self.check()

    def test_retained_originals_include_binary_stderr_and_check_digests(self):
        self.reference = True
        self.report["schema"] = "chrono-check-report/v2"
        for stream, raw in [("stdout",json.dumps(self.report.pop("response")).encode()), ("stderr", b"\xff")]:
            ref = self.original(stream, raw)
            self.report["judge"].update({stream+"_complete":True, stream+"_original":ref,
                                         stream+"_sha256":ref["sha256"]})
            self.report["publication"]["originals"].append(ref["path"])
        self.report["retained_report"] = ".chrono-harness/state/preparation/report"
        original = self.original("report",json.dumps(self.report).encode())
        self.slot.write_text(json.dumps({"schema":"chrono-check-reference/v1","original":original}))
        paths = set(self.check())
        self.assertEqual(paths, {self.slot.parent, Path(original["path"]),
                                  *map(Path, self.report["publication"]["originals"])})
        Path(self.report["judge"]["stderr_original"]["path"]).write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError,"digest"):
            self.check()
        self.slot.write_text(json.dumps({"schema":"chrono-check-reference/v1",
                                        "original":{"path":"../unrelated","sha256":"0"*64}}))
        with self.assertRaisesRegex(ValueError, "artifact path"):
            self.check()


if __name__ == "__main__":
    unittest.main()
