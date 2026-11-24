import base64
import copy
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github" / "release"))
import plan
with patch.dict(os.environ, {"GITHUB_REPOSITORY": "chrono-harness/chrono-harness-pr"}):
    import publish


repository = "chrono-harness/chrono-harness-pr"
sha = "a"*40
version = "0.1.0"
config = {"kind": "binary", "check": {"file": "check.yml"}, "version":version, "binary":"chrono-pr"}
run = {"repository":{"full_name":repository}, "head_repository":{"full_name":repository},
       "path":".github/workflows/check.yml", "event":"push", "status":"completed", "conclusion":"success",
       "head_sha":sha, "head_branch":"dev", "run_number":15}
event = {"repository":{"full_name":repository}, "workflow_run":run}


class ReleaseAdapterTest(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.enterContext(patch.object(plan.subprocess, "run"))
        self.owner.return_value = subprocess.CompletedProcess([], 0, "", "")

    def reject(self, message):
        self.owner.return_value = subprocess.CompletedProcess([], 2, "", message)


class PublishedBinaryRetry(ReleaseAdapterTest):
    def test_retry_compares_each_submitted_binary_with_the_published_bytes(self):
        tag = "v0.1.0-alpha.15"
        binary = "chrono-pr"
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            published = stage / "published"
            submitted = stage / "submitted"
            published.mkdir()
            submitted.mkdir()
            names = [binary + "-macos-aarch64", binary + "-linux-x86_64"]
            for name in names:
                (published / name).write_bytes(name.encode())
            (published / "SHA256SUMS").write_text("".join(
                hashlib.sha256((published / name).read_bytes()).hexdigest() + "  " + name + "\n"
                for name in names))
            digests = publish.sums(published, binary)
            release = {"tag_name": tag, "draft": False, "prerelease": True,
                       "assets": [{"name": name, "digest": "sha256:" + digest, "state": "uploaded"}
                                  for name, digest in digests.items()]}
            config_path = stage / ".chrono-harness" / "release.json"
            config_path.parent.mkdir()
            config_path.write_text(json.dumps({"kind": "binary", "binary": binary}))

            def download(*args):
                self.assertEqual(args[:4], ("release", "download", tag, "--dir"))
                for name in digests:
                    shutil.copyfile(published / name, Path(args[4]) / name)

            env = {"MODE": "preview", "TAG": tag, "SOURCE_SHA": sha, "DIST": str(submitted)}
            prior = Path.cwd()
            try:
                os.chdir(stage)
                with patch.dict(os.environ, env), patch.object(publish, "sha_of", return_value=sha), \
                        patch.object(publish, "by_tag", return_value=release), \
                        patch.object(publish, "gh", side_effect=download), \
                        patch.object(publish, "binary_origins", return_value={"source": sha}), \
                        patch.object(publish, "request", side_effect=AssertionError("immutable release")):
                    for changed in [None, *names]:
                        with self.subTest(changed=changed):
                            for name in names:
                                data = (published / name).read_bytes()
                                (submitted / name).write_bytes(data + b"!" if changed == name else data)
                            if changed is None:
                                publish.main()
                                self.assertEqual(self.owner.call_args.args[0],
                                                 ["chrono-host-release", "template-release-v1"])
                                self.assertEqual(json.loads(self.owner.call_args.kwargs["input"]), {
                                    "release": release, "tag": tag, "draft": False, "prerelease": True,
                                    "assets": {name: "sha256:" + value for name, value in digests.items()},
                                })
                            else:
                                with self.assertRaisesRegex(ValueError, "retry assets differ"):
                                    publish.main()
            finally:
                os.chdir(prior)


class BinaryOrigins(ReleaseAdapterTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        event = Path(self.temp.name) / "event.json"
        event.write_text(json.dumps({"workflow_run": {"id": 5, "run_attempt": 2}}))
        self.api = {"actions/runs/5/attempts/2": dict(run, id=5, run_attempt=2)}
        self.outputs = {}
        self.files = {}
        for key, platform, attempt, artifact in (("linux", "linux-x86_64", 1, 31),
                                                ("macos", "macos-aarch64", 2, 32)):
            binary = "chrono-pr-" + platform
            digest = hashlib.sha256(binary.encode()).hexdigest()
            self.files[binary] = digest
            archive = hashlib.sha256((binary + ".zip").encode()).hexdigest()
            self.outputs[key] = json.dumps({"id": str(artifact), "run": "20",
                                           "attempt": str(attempt), "archive": archive, "file": digest})
            path = f"actions/runs/20/attempts/{attempt}"
            self.api[path] = dict(run, id=20, run_attempt=attempt, head_sha="b" * 40,
                                  event="workflow_run", path=".github/workflows/release.yml")
            self.api[path + "/jobs?per_page=100"] = {"jobs": [
                {"id": artifact + 10, "name": "Build " + platform, "conclusion": "success",
                 "head_sha": "b" * 40, "steps": [{"name": step, "conclusion": "success"} for step in
                                           ("Build and exercise the release binary", "Upload the exercised binary")]}]}
            self.api[f"actions/artifacts/{artifact}"] = {
                "id": artifact, "name": f"{platform}-{sha}-{attempt}", "expired": False,
                "digest": "sha256:" + archive, "workflow_run": {"id": 20, "head_sha": "b" * 40}}
        self.env = {"GITHUB_EVENT_PATH": str(event), "GITHUB_RUN_ID": "20", "GITHUB_RUN_ATTEMPT": "2",
                    "GITHUB_SHA": "b" * 40, "BUILD_RECEIPTS": json.dumps(self.outputs)}

    def origins(self):
        with patch.dict(os.environ, self.env), patch.object(publish, "request", side_effect=self.api.__getitem__):
            return publish.binary_origins(config, sha, self.files)

    def test_reads_original_attempt_for_each_platform(self):
        source = self.origins()
        self.assertEqual(source["check"], {"run": 5, "attempt": 2})
        self.assertEqual([(row["attempt"], row["artifact"]) for row in source["builds"].values()],
                         [(2, 32), (1, 31)])

    def test_rejects_mismatched_native_producer_or_checked_source(self):
        for target, key, bad in [
            ("actions/artifacts/31", "digest", "sha256:" + "0" * 64),
            ("actions/artifacts/31", "expired", True),
            ("actions/artifacts/31", "name", "another-attempt"),
            ("actions/artifacts/31", "workflow_run", {"id": 21, "head_sha": "b" * 40}),
            ("actions/runs/20/attempts/1", "run_attempt", 2),
            ("actions/runs/20/attempts/1", "head_branch", "feature/other"),
            ("actions/runs/20/attempts/1/jobs?per_page=100", "jobs", []),

        ]:
            with self.subTest(target=target, key=key), patch.dict(self.api[target], {key: bad}):
                with self.assertRaises(ValueError):
                    self.origins()
        with patch.dict(self.files, {"chrono-pr-macos-aarch64": "0" * 64}):
            with self.assertRaisesRegex(ValueError, "downloaded bytes differ"):
                self.origins()


class ReleasePlan(ReleaseAdapterTest):
    @patch.object(plan, "api", side_effect=lambda path: {"status":"identical"} if "/compare/" in path else [])
    def test_preview_rejects_wrong_events(self, github):
        selected = plan.plan(config, repository, event, "workflow_run")
        self.assertEqual(selected, {"mode":"preview", "sha":sha, "tag":"v0.1.0-alpha.15"})
        self.owner.assert_called_once()
        self.assertEqual(self.owner.call_args.args[0], ["chrono-host-release", "template-run-v1"])
        self.assertEqual(json.loads(self.owner.call_args.kwargs["input"]),
                         {"repository": repository, "branch": "dev", "workflow": "check.yml", "sha": sha, "run": run})
        self.reject("wrong run")
        with self.assertRaisesRegex(ValueError, "wrong run"):
            plan.plan(config, repository, event, "workflow_run")
        self.owner.return_value = subprocess.CompletedProcess([], 0, "", "")
        github.side_effect = lambda path: {"status":"diverged"}
        with self.assertRaisesRegex(ValueError, "does not contain"):
            plan.plan(config, repository, event, "workflow_run")

    def test_real_draft_api_shape_uses_the_release_id(self):
        import os
        with patch.dict(os.environ, {"GITHUB_REPOSITORY":repository}):
            import publish
        draft={"id":455959087,"tag_name":"v0.1.0-alpha.29","draft":True,"assets":[]}
        with patch.object(publish, "optional", return_value=None), patch.object(publish, "request",
                side_effect=[[{"tag_name":"other"}]*100,[draft]]) as pages:
            self.assertEqual(publish.by_tag(draft["tag_name"]), draft)
            self.assertEqual(pages.call_args.args, ("releases?per_page=100&page=2",))

    def test_published_stable_finishes_the_plan(self):
        with patch.object(plan, "api", side_effect=[{"status":"ahead"}, [{"ref":"refs/tags/v0.1.0"}],
                                                    {"draft":False,"prerelease":False,"tag_name":"v0.1.0"},
                                                    {"object":{"type":"commit","sha":sha}}, {"status":"identical"}]):
            self.assertEqual(plan.plan(config, repository, event, "workflow_run")["mode"], "complete")

    def test_validates_both_downloads(self):
        digest = "sha256:"+"c"*64
        prefix = f"https://github.com/{repository}/releases/download/v0.1.0-alpha.15/chrono-pr-"
        tools = {"bin":"chrono-pr", "version":"0.1.0-alpha.15", "platforms":{
            "linux-x64":{"url":prefix+"linux-x86_64","checksum":digest},
            "macos-arm64":{"url":prefix+"macos-aarch64","checksum":digest}}}
        tag = "v0.1.0-alpha.15"
        checks = {f"chrono-pr-{suffix}":digest for suffix in ("linux-x86_64","macos-aarch64")}
        self.owner.return_value = subprocess.CompletedProcess([], 0, json.dumps([tag, checks]), "")
        self.assertEqual(plan.pin_manifest(repository, "chrono-pr", version, tools), (tag, checks))
        args, options = self.owner.call_args
        self.assertEqual(args, (["chrono-host-release", "template-consumer-pin-v1"],))
        self.assertEqual(json.loads(options["input"]), {"kind":"binary", "repository":repository,
                         "binary":"chrono-pr", "version":version, "tool":tools})
        self.assertEqual(tag, "v0.1.0-alpha.15")
        for platform in tools["platforms"]:
            wrong = copy.deepcopy(tools)
            wrong["platforms"][platform]["url"] += "other"
            self.reject("wrong platform")
            with self.assertRaises(ValueError):
                plan.pin_manifest(repository, "chrono-pr", version, wrong)
        self.owner.return_value = subprocess.CompletedProcess([], 0, "", "")
        release = {"tag_name":tag,"draft":False,"prerelease":True,
                   "assets":[{"name":name,"state":"uploaded","digest":digest}
                             for name in [*checks,"SHA256SUMS"]]}
        with patch.object(plan, "api", return_value=release):
            self.assertEqual(plan.public_preview(repository, tag, checks), release)
            self.assertEqual(self.owner.call_args.args[0], ["chrono-host-release", "template-release-v1"])
            self.assertEqual(json.loads(self.owner.call_args.kwargs["input"]), {
                "release": release, "tag": tag, "draft": False, "prerelease": True,
                "assets": {**checks, "SHA256SUMS": None}})
            self.reject("release assets differ")
            with self.assertRaisesRegex(ValueError, "release assets differ"):
                plan.public_preview(repository, tag, checks)

    def test_skipped_or_wrong_platform_does_not_prove_adoption(self):
        consumer={"jobs":["mac","linux"], "step":"exercise"}
        job={"name":"mac","conclusion":"success","head_sha":sha,
             "steps":[{"name":"exercise","conclusion":"success"}]}
        checked=dict(run,id=1,run_attempt=1)
        jobs=[job,dict(job,name="linux")]
        with patch.object(plan,"api",return_value={"jobs":jobs}):
            plan.check_acceptance("example/org",checked,consumer)
            self.assertEqual(self.owner.call_args.args[0], ["chrono-host-release", "template-acceptance-v1"])
            self.assertEqual(json.loads(self.owner.call_args.kwargs["input"]),
                             {"jobs": jobs, "sha": sha, "required_jobs": ["mac", "linux"], "step": "exercise"})
            self.reject("missing exercised product")
            with self.assertRaisesRegex(ValueError, "missing exercised"):
                plan.check_acceptance("example/org", checked, consumer)

    def test_dispatch_requires_landed_consumer(self):
        consumer = {"branch":"dev","workflow":"pr-adoption.yml","repository":"example/org","pin":"lock.toml"}
        with patch.object(plan,"sha_of",return_value=sha), patch.object(plan,"api",return_value={"workflow_runs":[]}):
            with self.assertRaisesRegex(ValueError, "no successful"):
                plan.plan(dict(config, consumer=consumer), repository,
                          {"ref":"refs/heads/dev","repository":{"full_name":repository}}, "workflow_dispatch")

    def test_successful_other_candidate_cannot_release_main(self):
        consumer = {"branch":"dev","workflow":"pr-adoption.yml","repository":"example/org","pin":"lock.toml"}
        main = dict(event, workflow_run=dict(run, head_branch="main"))
        with patch.object(plan,"sha_of",return_value="b"*40), patch.object(plan,"successful_run",return_value=run), \
                patch.object(plan,"check_acceptance"), patch.object(plan,"consumer_pin",return_value=("v0.1.0-alpha.15", {})):
            with self.assertRaisesRegex(ValueError, "main differs"):
                plan.plan(dict(config, consumer=consumer), repository, main, "workflow_run")


class CopierPromotion(ReleaseAdapterTest):
    source = "chrono-harness/chrono-harness-copier"
    preview = "v0.1.0-alpha.15"
    consumer = {"repository": "example/host", "branch": "dev", "workflow": "copier.yml",
                "pin": ".chrono-harness/template-answers.yml", "jobs": ["copier"], "step": "render"}
    config = {"kind": "copier", "version": version, "check": {"file": "check.yml"}, "consumer": consumer}

    def response(self, path):
        consumer = self.consumer["repository"]
        if "/git/ref/" in path:
            return {"object": {"type": "commit", "sha": self.adopted if consumer in path else sha}}
        if "/actions/workflows/" in path:
            repo = consumer if consumer in path else self.source
            workflow = "copier.yml" if repo == consumer else "check.yml"
            checked = dict(run, repository={"full_name": repo}, head_repository={"full_name": repo},
                           path=".github/workflows/" + workflow, head_sha=self.adopted if repo == consumer else sha,
                           id=135, run_attempt=1, html_url="https://github.com/" + repo + "/actions/runs/135")
            return {"workflow_runs": [checked]}
        if "/jobs?" in path:
            return {"jobs": [{"name": "copier", "conclusion": "success", "head_sha": self.adopted,
                              "steps": [{"name": "render", "conclusion": self.outcome}]}]}
        if "/contents/" in path:
            self.assertTrue(path.endswith("?ref=" + self.adopted))
            return {"content": base64.b64encode(self.answers.encode()).decode()}
        if "/compare/" in path:
            return {"status": "ahead"}
        if "/releases/tags/" in path:
            return self.release
        raise AssertionError(path)

    def setUp(self):
        super().setUp()
        self.adopted = "b" * 40
        self.answers = "_src_path: gh:" + self.source + "\n_commit: " + self.preview
        self.release = {"tag_name": self.preview, "prerelease": True, "draft": False, "assets": []}
        self.outcome = "success"
        self.expected_version = version
        def select(args, **options):
            if args[-1] == "template-consumer-pin-v1":
                request = json.loads(options["input"])
                self.assertEqual(request["kind"], "copier")
                self.assertEqual(request["repository"], self.source)
                self.assertEqual(request["version"], self.expected_version)
                self.assertEqual(request["rolling"], self.config.get("version_policy") == "next_patch")
                answers = request["answers"]
                if answers["_src_path"] == "gh:other/repo":
                    return subprocess.CompletedProcess(args, 2, "", "consumer uses another template")
                return subprocess.CompletedProcess(args, 0, json.dumps([answers["_commit"], None]), "")
            return self.owner.return_value
        self.owner.side_effect = select

    def promote(self):
        with patch.object(plan, "api", side_effect=self.response):
            return plan.plan(self.config, self.source,
                             {"repository": {"full_name": self.source}, "ref": "refs/heads/dev"}, "workflow_dispatch")

    def test_promotes_the_accepted_source(self):
        result = self.promote()
        self.assertEqual((result["mode"], result["sha"], result["preview"], result["adopted"]),
                         ("stable", sha, self.preview, self.adopted))

    def test_rejects_different_source_tag_or_skipped_adoption(self):
        valid = self.answers
        for text, error in [(valid.replace(self.source, "other/repo"), "another template"),
                            (valid.replace("alpha.15", "alpha.14"), "verified dev run")]:
            self.answers = text
            with self.assertRaisesRegex(ValueError, error):
                self.promote()
        self.answers = valid
        self.outcome = "skipped"
        previous = self.owner.side_effect
        def skipped(args, **options):
            if args[-1] == "template-acceptance-v1":
                self.assertEqual(json.loads(options["input"])["jobs"][0]["steps"][0]["conclusion"], "skipped")
                return subprocess.CompletedProcess(args, 2, "", "missing exercised product")
            return previous(args, **options) if previous else self.owner.return_value
        self.owner.side_effect = skipped
        with self.assertRaisesRegex(ValueError, "missing exercised"):
            self.promote()

    def test_forwards_source_release_and_propagates_the_verifier_exit(self):
        self.release["draft"] = True
        self.release["assets"] = [{"state": "starter"}]
        previous = self.owner.side_effect
        def reject_release(args, **options):
            if args[-1] == "template-release-v1":
                self.assertEqual(json.loads(options["input"]), {"release": self.release, "tag": self.preview,
                                 "draft": False, "prerelease": True, "assets": {}})
                return subprocess.CompletedProcess(args, 2, "", "source release differs")
            return previous(args, **options) if previous else self.owner.return_value
        self.owner.side_effect = reject_release
        with self.assertRaisesRegex(ValueError, "source release differs"):
            self.promote()


class NextSourceCycle(CopierPromotion):
    config = dict(CopierPromotion.config, version_policy="next_patch")

    def setUp(self):
        super().setUp()
        previous = self.owner.side_effect
        def release_command(args, **options):
            if args[-1] != "template-next-version-v1":
                return previous(args, **options)
            observed = json.loads(options["input"])
            self.assertEqual(observed["latest"], "0.1.0")
            responses = {"0.1.0": "0.1.1", "2.0.0": "2.0.0"}
            return subprocess.CompletedProcess(args, 0, json.dumps(responses[observed["floor"]]), "")
        self.owner.side_effect = release_command
        self.preview = "v0.1.1-alpha.15"
        self.expected_version = "0.1.1"
        self.answers = "_src_path: gh:" + self.source + "\n_commit: " + self.preview
        self.release["tag_name"] = self.preview
        self.previous = "c" * 40
        self.candidate_relation = "ahead"

    def response(self, path):
        if "/releases?" in path:
            return [{"tag_name": "v0.1.0", "published_at": "2026-01-10", "draft": False, "prerelease": False},
                    {"tag_name": "v7.0.0", "published_at": None, "draft": True, "prerelease": False}]
        if path.endswith("/git/ref/tags/v0.1.0"):
            return {"object": {"type": "commit", "sha": self.previous}}
        if path.endswith(self.previous + "..." + sha):
            return {"status": self.candidate_relation}
        if "/git/matching-refs/" in path:
            return []
        return super().response(path)

    def test_stable_semver_increments_and_host_can_plan_a_major(self):
        self.assertEqual(self.promote()["tag"], "v0.1.1")
        with patch.object(plan, "api", side_effect=self.response):
            target, _ = plan.next_target(dict(self.config, version="2.0.0"), self.source)
        self.assertEqual(target["version"], "2.0.0")

    def test_previously_released_source_is_terminal(self):
        for relation in ("identical", "behind"):
            self.candidate_relation = relation
            self.assertEqual(self.promote(), {"mode": "complete", "sha": self.previous, "tag": "v0.1.0"})
        self.candidate_relation = "diverged"
        with self.assertRaisesRegex(ValueError, "diverges"):
            self.promote()

    def test_source_plan_never_relabels_a_binary(self):
        with self.assertRaisesRegex(ValueError, "Copier"):
            plan.next_target(dict(self.config, kind="binary"), self.source)


if __name__ == "__main__":
    unittest.main()
