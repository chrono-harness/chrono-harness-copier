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
        self.owner.side_effect = self.route_responses

    def route_responses(self, args, **options):
        request = json.loads(options["input"])
        if args[-1] == "template-promotion-v1" and request.get("kind") == "event":
            if request["event_name"] == "workflow_dispatch":
                answer = "dispatch"
            else:
                answer = request["event"]["workflow_run"]["head_branch"]
            return subprocess.CompletedProcess(args, 0, json.dumps(answer), "")
        if args[-1] == "template-promotion-v1" and request.get("kind") == "tag":
            return subprocess.CompletedProcess(args, 0, json.dumps(bool(request["refs"])), "")
        return self.owner.return_value

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
            release = {"id": 15, "tag_name": tag, "draft": False, "prerelease": True,
                       "assets": [{"name": name, "digest": "sha256:" + digest, "state": "uploaded"}
                                  for name, digest in digests.items()]}
            def download(*args):
                self.assertEqual(args[:4], ("release", "download", tag, "--dir"))
                for name in digests:
                    shutil.copyfile(published / name, Path(args[4]) / name)

            env = {"MODE": "preview", "TAG": tag, "SOURCE_SHA": sha, "DIST": str(submitted)}
            ref = {"ref": "refs/tags/" + tag, "object": {"type": "commit", "sha": sha}}
            expected = {name: "sha256:" + digest for name, digest in digests.items()}
            prior = Path.cwd()
            try:
                os.chdir(stage)
                with patch.object(publish, "config_at", return_value={"kind": "binary", "binary": binary}) as read_config, \
                        patch.dict(os.environ, env), patch.object(publish, "optional", return_value=ref), \
                        patch.object(publish, "by_tag", return_value=release), \
                        patch.object(publish, "gh", side_effect=download), \
                        patch.object(publish, "binary_origins", return_value={"source": sha}), \
                        patch.object(publish, "request", side_effect=AssertionError("immutable release")):
                    for changed in [None, *names]:
                        with self.subTest(changed=changed):
                            for name in names:
                                data = (published / name).read_bytes()
                                (submitted / name).write_bytes(data + b"!" if changed == name else data)
                            def verify(args, **kwargs):
                                data = json.loads(kwargs["input"])
                                if args[-1] == "template-publication-v1" and data["kind"] == "state":
                                    self.assertEqual(data["reference"], ref)
                                    self.assertEqual(data["release"], release)
                                    self.assertEqual(data["source"], sha)
                                    if changed is not None:
                                        self.assertNotEqual(data["assets"][changed], digests[changed])
                                        return subprocess.CompletedProcess(args, 2, "", "existing asset differs")
                                    self.assertEqual(data["assets"], digests)
                                    return subprocess.CompletedProcess(args, 0,
                                        json.dumps({"action": "replay", "missing": [], "create_tag": False}), "")
                                if args[-1] == "template-release-v1":
                                    self.assertEqual(data, {"release": release, "tag": tag, "assets": expected,
                                                            "prerelease": True, "draft": False})
                                return subprocess.CompletedProcess(args, 0, "", "")
                            self.owner.side_effect = verify
                            if changed is None:
                                publish.main()
                            else:
                                with self.assertRaisesRegex(ValueError, "existing asset differs"):
                                    publish.main()
                    self.assertTrue(all(call.args == (repository, sha) for call in read_config.call_args_list))
                    self.assertEqual(read_config.call_count, 3)
            finally:
                os.chdir(prior)


class DraftPublication(ReleaseAdapterTest):
    def test_resumes_only_missing_assets_and_verifies_before_writing(self):
        tag = "v0.1.0-alpha.15"
        ref = {"ref": "refs/tags/" + tag, "object": {"type": "commit", "sha": sha}}
        release = {"tag_name": tag, "id": 12, "draft": True, "prerelease": True, "assets": []}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for suffix in ("macos-aarch64", "linux-x86_64"):
                (root / ("tool-" + suffix)).write_bytes(suffix.encode())
            env = {"MODE": "preview", "SOURCE_SHA": sha, "TAG": tag, "DIST": tmp}
            mutating = []
            reject = False

            def respond(path, **options):
                if options:
                    mutating.append((path, options["method"]))
                if path == "git/ref/tags/" + tag:
                    return ref
                self.assertEqual(path, "releases/12")
                return dict(release, draft=not bool(options))

            def verify(args, **options):
                data = json.loads(options["input"])
                if args[-1] == "template-publication-v1" and data["kind"] == "state":
                    self.assertEqual(data["release"], release)
                    self.assertEqual((data["reference"], data["source"]), (ref, sha))
                    if reject:
                        return subprocess.CompletedProcess(args, 2, "", "existing asset differs")
                    return subprocess.CompletedProcess(args, 0, json.dumps({
                        "action": "resume", "create_tag": False, "missing": ["tool-linux-x86_64"]}), "")
                return subprocess.CompletedProcess(args, 0, "", "")

            self.owner.side_effect = verify
            prior = Path.cwd()
            try:
                os.chdir(root)
                with patch.object(publish, "config_at", return_value={"kind": "binary", "binary": "tool"}), \
                        patch.dict(os.environ, env), patch.object(publish, "optional", return_value=ref), \
                        patch.object(publish, "request", side_effect=respond), \
                        patch.object(publish, "by_tag", return_value=release), \
                        patch.object(publish, "binary_origins", return_value=None), patch.object(publish, "gh") as gh:
                    publish.main()
                    gh.assert_called_once_with("release", "upload", tag, root / "tool-linux-x86_64")
                    self.assertEqual(mutating, [("releases/12", "PATCH")])
                    mutating.clear()
                    gh.reset_mock()
                    reject = True
                    with self.assertRaisesRegex(ValueError, "existing asset differs"):
                        publish.main()
                    gh.assert_not_called()
                    self.assertEqual(mutating, [])
            finally:
                os.chdir(prior)


class CheckedPublicationWrites(ReleaseAdapterTest):
    def test_main_update_uses_its_response_and_rejects_a_different_ref_before_publication(self):
        tag, preview = "v0.1.0", "v0.1.0-alpha.15"
        correct = {"ref": "refs/heads/main", "object": {"sha": sha, "type": "commit"}}
        previous = {"ref": "refs/heads/main", "object": {"sha": "b" * 40, "type": "commit"}}
        wrong = {"ref": "refs/heads/unrelated", "object": {"sha": sha, "type": "commit"}}
        for initial, applied, passes in ((previous, wrong, False), (previous, correct, True),
                                         (correct, None, True)):
            with self.subTest(initial=initial, applied=applied), tempfile.TemporaryDirectory() as dist:
                writes = []
                reads = []
                verified_main = []
                def api(path, **options):
                    if path.startswith("git/ref/tags/"):
                        return {"ref": path.removeprefix("git/ref/"), "object": {"sha": sha}}
                    if path == "git/ref/heads/main":
                        reads.append(path)
                        return initial
                    if path == "git/refs/heads/main":
                        self.assertEqual((options["method"], json.loads(options["data"])),
                                         ("PATCH", {"sha": sha, "force": False}))
                        writes.append("main")
                        return applied
                    if options:
                        self.assertEqual((path, json.loads(options["data"])), ("releases/12", {"draft": False}))
                        writes.append("publish")
                    return {"id": 12}

                def owner(command, query):
                    if query["kind"] == "state":
                        return json.dumps({"action": "resume", "create_tag": False, "missing": []})
                    if query["kind"] == "main":
                        self.assertEqual(query, {"kind":"main","source":sha,"reference":initial})
                        return json.dumps(initial == previous)
                    if query["kind"] == "ref" and query["name"] == "refs/heads/main":
                        self.assertEqual(command, "template-publication-v1")
                        verified_main.append(query["reference"])
                        if query["reference"] != correct:
                            raise ValueError("owner rejected ref")
                    return ""

                env = {"MODE":"stable","TAG":tag,"PREVIEW":preview,"SOURCE_SHA":sha,"PROOF":"checked","DIST":dist}
                with patch.dict(os.environ, env), patch.object(publish,"config_at",return_value={"kind":"copier"}), \
                        patch.object(publish,"by_tag",return_value={"id":12}), patch.object(publish,"optional"), \
                        patch.object(publish,"check_release"), patch.object(publish,"judge",side_effect=owner), \
                        patch.object(publish,"request",side_effect=api):
                    if passes:
                        publish.main()
                    else:
                        with self.assertRaisesRegex(ValueError,"owner rejected ref"):
                            publish.main()
                self.assertEqual(reads, ["git/ref/heads/main"])
                self.assertEqual(verified_main, [applied if applied is not None else initial])
                self.assertEqual(writes, (["main"] if applied is not None else []) + (["publish"] if passes else []))

    def test_draft_notes_are_checked_on_both_complete_responses_before_publication(self):
        tag = "v0.1.0-alpha.15"
        origins = {"run": 123}
        expected = "Preview of " + sha + "\n\nBuild origins\n\n```json\n" + json.dumps(origins, indent=2) + "\n```"
        for after in (expected, expected + " "):
            with self.subTest(after=after), tempfile.TemporaryDirectory() as dist:
                for platform in ("macos-aarch64", "linux-x86_64"):
                    (Path(dist) / ("tool-" + platform)).write_bytes(b"build output")
                current = {"id":12, "body":expected+" ", "draft":True, "assets":[], "origin":"first"}
                final = dict(current, body=after, origin="second")
                drafts = iter([current, final])
                queries = []
                writes = []
                def api(path, **options):
                    if path != "releases/12":
                        return {"object":{"sha":sha}}
                    if options:
                        writes.append(json.loads(options["data"]))
                        return {"id":12}
                    return next(drafts)
                def owner(command, query):
                    if query["kind"] == "state":
                        return json.dumps({"action":"resume","create_tag":False,"missing":[]})
                    if query["kind"] == "draft":
                        self.assertEqual(command, "template-publication-v1")
                        queries.append(query)
                        changed = query["release"]["body"] != query["expected"]
                        if changed and query["verify"]:
                            raise ValueError("different build origins on draft")
                        return json.dumps(changed)
                    return ""
                env = {"MODE":"preview","TAG":tag,"SOURCE_SHA":sha,"DIST":dist}
                with patch.dict(os.environ,env), patch.object(publish,"config_at",return_value={"kind":"binary","binary":"tool"}), \
                        patch.object(publish,"by_tag",return_value={"id":12}),patch.object(publish,"optional"), \
                        patch.object(publish,"binary_origins",return_value=origins),patch.object(publish,"sums",return_value={}), \
                        patch.object(publish,"check_release"),patch.object(publish,"judge",side_effect=owner), \
                        patch.object(publish,"request",side_effect=api):
                    if after == expected:
                        publish.main()
                    else:
                        with self.assertRaisesRegex(ValueError,"different build origins"):
                            publish.main()
                self.assertEqual(queries, [{"kind":"draft","origins":True,"verify":verify,"release":draft,"expected":expected} for verify,draft in ((False,current),(True,final))])
                self.assertEqual(writes,[{"body":expected}] + ([{"draft":False}] if after == expected else []))


class BinaryOrigins(ReleaseAdapterTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        event = Path(self.temp.name) / "event.json"
        event.write_text(json.dumps({"workflow_run": {"id": 5, "run_attempt": 2}}))
        self.api = {"actions/runs/5/attempts/2": dict(run, id=5, run_attempt=2)}
        self.extra_jobs = [{"id": index, "name": "other"} for index in range(100)]
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
        pages_read = []
        def job_pages(args):
            path = args[-1].removeprefix("repos/" + repository + "/")
            self.assertEqual(args, ["gh", "api", "--paginate", "--slurp", f"repos/{repository}/{path}"])
            pages_read.append(path)
            return json.dumps([{"jobs": self.extra_jobs}, self.api[path]])
        with patch.dict(os.environ, self.env), patch.object(publish, "request", side_effect=self.api.__getitem__) as get, \
                patch.object(plan.subprocess, "check_output", side_effect=job_pages):
            receipt = publish.binary_origins(config, sha, self.files)
        return receipt, [call.args[0] for call in get.call_args_list] + pages_read

    def test_forwards_observed_metadata_and_downloaded_bytes(self):
        receipt = {"source": sha, "check": {"run": 5, "attempt": 2}, "builds": {"owner": "receipt"}}
        self.owner.return_value = subprocess.CompletedProcess([], 0, json.dumps(receipt), "")
        for linux_attempt in [1, 2]:
            with self.subTest(linux_attempt=linux_attempt):
                linux = dict(json.loads(self.outputs["linux"]), attempt=str(linux_attempt))
                self.env["BUILD_RECEIPTS"] = json.dumps(dict(self.outputs, linux=json.dumps(linux)))
                result, fetched = self.origins()
                self.assertEqual(result, receipt)
                args, kwargs = self.owner.call_args
                self.assertEqual(args, (["chrono-host-release", "template-binary-origins-v1"],))
                request = json.loads(kwargs["input"])
                expected = {"repository": repository, "binary": "chrono-pr", "source": sha,
                            "workflow": "check.yml", "check_id": 5, "check_attempt": 2, "run_id": 20,
                            "current_attempt": 2, "workflow_sha": "b" * 40,
                            "check": self.api["actions/runs/5/attempts/2"]}
                for key, platform, selected in (("macos", "macos-aarch64", json.loads(self.outputs["macos"])),
                                                ("linux", "linux-x86_64", linux)):
                    path = "actions/runs/20/attempts/" + selected["attempt"]
                    expected[key] = {
                        "selected_run": 20, "attempt": int(selected["attempt"]), "artifact_id": int(selected["id"]),
                        "archive": selected["archive"], "file": selected["file"],
                        "downloaded": self.files["chrono-pr-" + platform], "run": self.api[path],
                        "jobs": self.extra_jobs + self.api[path + "/jobs?per_page=100"]["jobs"],
                        "artifact": self.api["actions/artifacts/" + selected["id"]],
                    }
                self.assertEqual(request, expected)
                self.assertEqual(len(fetched), len(set(fetched)))
                self.assertEqual(len(fetched), 3 + 2 * len({linux_attempt, 2}))

    def test_propagates_owner_rejection(self):
        self.reject("different release workflow or producing attempt")
        with self.assertRaisesRegex(ValueError, "different release workflow or producing attempt"):
            self.origins()


class ReleasePlan(ReleaseAdapterTest):
    def test_late_check_uses_the_version_from_its_checked_source(self):
        later = "b" * 40
        configs = {sha: dict(config, version="0.1.3"), later: dict(config, version="0.1.4")}
        def read(path):
            if "/contents/" in path:
                selected = path.rsplit("=", 1)[1]
                return {"content": base64.b64encode(json.dumps(configs[selected]).encode()).decode()}
            return {"status": "ahead"} if "/compare/" in path else []
        with patch.object(plan, "api", side_effect=read):
            self.assertEqual(plan.event_plan(repository, event, "workflow_run", later)["tag"], "v0.1.3-alpha.15")
            with self.assertRaisesRegex(ValueError, "commit SHA"):
                plan.config_at(repository, "dev")

    @patch.object(plan, "api", side_effect=lambda path: {"status":"identical"} if "/compare/" in path else [])
    def test_preview_rejects_wrong_events(self, github):
        selected = plan.plan(config, repository, event, "workflow_run")
        self.assertEqual(selected, {"mode":"preview", "sha":sha, "tag":"v0.1.0-alpha.15"})
        routed, checked, contained, matching = self.owner.call_args_list
        self.assertEqual(json.loads(routed.kwargs["input"])["event"]["workflow_run"]["head_branch"], "dev")
        self.assertEqual(json.loads(matching.kwargs["input"]), {"kind":"tag","tag":"v0.1.0","refs":[]})
        self.assertEqual(checked.args[0], ["chrono-host-release", "template-run-v1"])
        self.assertEqual(json.loads(checked.kwargs["input"]),
                         {"repository": repository, "branch": "dev", "workflow": "check.yml", "sha": sha, "run": run})
        self.assertEqual(contained.args[0], ["chrono-host-release", "template-promotion-v1"])
        self.assertEqual(json.loads(contained.kwargs["input"]),
                         {"kind": "contains", "comparison": {"status": "identical"}})
        self.reject("wrong run")
        with self.assertRaisesRegex(ValueError, "wrong run"):
            plan.plan(config, repository, event, "workflow_run")
        self.owner.side_effect = [subprocess.CompletedProcess([], 0, '"dev"', ""),
                                  subprocess.CompletedProcess([], 0, "", ""),
                                  subprocess.CompletedProcess([], 2, "", "branch does not contain commit")]
        github.side_effect = lambda path: {"status":"diverged"}
        with self.assertRaisesRegex(ValueError, "does not contain"):
            plan.plan(config, repository, event, "workflow_run")

    def test_rejected_event_stops_before_reading_release_config(self):
        cases = [
            ("workflow_run", {"repository":{"full_name":"other/repo"}, "workflow_run":{"head_branch":"dev"}}, "wrong event repository"),
            ("workflow_run", {"repository":{"full_name":repository}, "workflow_run":{"head_branch":"topic"}}, "unsupported release branch"),
            ("workflow_dispatch", {"repository":{"full_name":repository}, "ref":"refs/heads/main"}, "dispatch from dev"),
        ]
        for name, invalid, message in cases:
            with self.subTest(name=name,message=message), patch.object(plan, "api") as fetch:
                self.owner.side_effect = None
                self.reject(message)
                with self.assertRaisesRegex(ValueError, message):
                    plan.event_plan(repository, invalid, name, sha)
                fetch.assert_not_called()
                args, options = self.owner.call_args
                self.assertEqual(args[0], ["chrono-host-release","template-promotion-v1"])
                request = json.loads(options["input"])
                self.assertEqual((request["kind"], request["repository"], request["event_name"]), ("event",repository,name))
                self.assertEqual(request["event"]["repository"],invalid["repository"])

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
        self.owner.return_value = subprocess.CompletedProcess([], 0, "true", "")
        with patch.object(plan, "api", side_effect=[{"status":"ahead"}, [{"ref":"refs/tags/v0.1.0"}],
                                                    {"draft":False,"prerelease":False,"tag_name":"v0.1.0","published_at":"date"},
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
        pages = json.dumps([{"jobs": jobs[:1]}, {"jobs": jobs[1:]}])
        with patch.object(plan.subprocess, "check_output", return_value=pages) as get:
            plan.check_acceptance("example/org",checked,consumer)
            get.assert_called_once_with(["gh", "api", "--paginate", "--slurp",
                                         "repos/example/org/actions/runs/1/attempts/1/jobs?per_page=100"])
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
        def refuse_different_main(args, **options):
            if args[-1] == "template-promotion-v1" and json.loads(options["input"])["kind"] == "adopted":
                request = json.loads(options["input"])
                self.assertEqual((request["checked_main"], request["selected"]), (sha, "b"*40))
                return subprocess.CompletedProcess(args, 2, "", "main differs")
            return self.route_responses(args, **options)
        self.owner.side_effect = refuse_different_main
        with patch.object(plan,"compare",return_value={"status":"ahead"}), patch.object(plan,"sha_of",return_value="b"*40), patch.object(plan,"successful_run",return_value=run), \
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
        if path == f"repos/{self.source}/contents/.chrono-harness/release.json?ref={sha}":
            return {"content": base64.b64encode(json.dumps(self.config).encode()).decode()}
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
            if json.loads(options["input"]).get("kind") in ("event", "tag"):
                return self.route_responses(args, **options)
            if args[-1] == "template-promotion-v1":
                request = json.loads(options["input"])
                if request["kind"] == "adopted":
                    self.assertEqual((request["origin"]["head_sha"], request["selected"], request["workflow"]),
                                     (sha, sha, "check.yml"))
                    self.assertEqual((request["development"], request["main"]), ({"status":"ahead"}, {"status":"ahead"}))
                    if request["tag"].endswith("alpha.14"):
                        return subprocess.CompletedProcess(args, 2, "", "tag differs from the verified dev run")
                    self.assertEqual((request["tag"], request["origin"]["run_number"]), (self.preview, 15))
                if request["kind"] == "candidate":
                    relation = request["comparison"]["status"]
                    if relation == "diverged":
                        return subprocess.CompletedProcess(args, 2, "", "candidate diverges")
                    return subprocess.CompletedProcess(args, 0, {"ahead":"false","identical":"true","behind":"true"}[relation], "")
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
        def job_pages(args):
            self.assertEqual(args[:4], ["gh", "api", "--paginate", "--slurp"])
            return json.dumps([self.response(args[4])])
        with patch.object(plan, "api", side_effect=self.response), \
                patch.object(plan.subprocess, "check_output", side_effect=job_pages):
            return plan.plan(self.config, self.source,
                             {"repository": {"full_name": self.source}, "ref": "refs/heads/dev"}, "workflow_dispatch")

    def test_rejects_dispatch_with_a_different_source_release_config(self):
        with patch.object(plan, "config_at", return_value=dict(self.config, version="9.9.9")) as source:
            with self.assertRaisesRegex(ValueError, "different release config"):
                self.promote()
        source.assert_called_once_with(self.source, sha)

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
            if args[-1] == "template-latest-stable-v1":
                self.assertEqual(json.loads(options["input"]), self.response("/releases?"))
                return subprocess.CompletedProcess(args, 0, '"v0.1.0"', "")
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

    def test_all_release_pages_reach_the_selector(self):
        original = {"tag_name":"v0.1.0", "draft":False, "prerelease":False, "published_at":"date"}
        rows = [dict(original, tag_name=f"v0.0.{n}") for n in range(100)] + [original]
        def page(path):
            if path.endswith("per_page=100&page=1"):
                return rows[:100]
            if path.endswith("per_page=100&page=2"):
                return rows[100:]
            return self.response(path)
        def select(command, request):
            if command == "template-promotion-v1":
                self.assertEqual(request, {"kind": "contains", "comparison": {"status": "ahead"}})
                return "null"
            self.assertEqual(command, "template-latest-stable-v1")
            self.assertEqual(request, rows)
            return '"v0.1.0"'
        with patch.object(plan, "api", side_effect=page), patch.object(plan, "judge", side_effect=select):
            self.assertEqual(plan.latest_source_release(self.source), ("v0.1.0", self.previous))

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
