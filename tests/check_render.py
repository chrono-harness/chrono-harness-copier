"""Verify the default installation and explicit tool choices."""
import json
import os
import subprocess
import tempfile
from pathlib import Path
import sys
import tomllib

empty, selected, full, diagnostics, bootstrap, release, inputs, routes, cost, worktree, filemap, mixed, projects, judge_ci, workflow, test_git = map(Path, sys.argv[1:])
manifest = Path(".config/mise/conf.d/chrono-harness.toml")
for path in (".github/roadmap.cjs", ".github/workflows/issue-roadmap.yml"):
    assert not (empty / path).exists()
    assert (full / path).read_bytes() == Path(path).read_bytes()

for path in [Path(".github/PULL_REQUEST_TEMPLATE.md"), *Path(".github/ISSUE_TEMPLATE").glob("*.yml")]:
    assert (full / path).read_bytes() == path.read_bytes()
    assert not (empty / path).exists()

retention_host = full.parent / "local-check-retention"
policy = Path(".chrono-harness/retention.json")
request = Path(".chrono-harness/maintain-checks.json")
for host in (empty, full, selected):
    assert not (host / policy).exists() and not (host / request).exists()
retention_config = tomllib.loads((retention_host / manifest).read_text())
assert set(retention_config["tools"]) == {"http:chrono-harness"}
assert retention_config["tasks"]["harness-maintain-checks"]["run"] == (
    f"chrono-harness retention --host-root . --request {request}"
)
assert json.loads((retention_host / request).read_bytes()) == {"operation": "maintain"}
assert json.loads((full.parent / "expiring-checks" / request).read_bytes()) == {
    "operation": "maintain",
    "expire_local_check_slots": [".chrono-harness/state/collection/check.json", ".chrono-harness/state/other/a b.json"],
}
# The combined timer preserves report stdout and attempts both independent jobs.
combined = tomllib.loads((full.parent / "expiring-checks" / manifest).read_text())
assert set(combined["tools"]) == {"http:chrono-host-bootstrap", "http:chrono-harness"}
with tempfile.TemporaryDirectory() as mock_directory:
    tools = Path(mock_directory)
    for name, expected, status in (
        ("chrono-host-bootstrap", "native-scratch maintain 45", "NATIVE_STATUS"),
        ("chrono-harness", f"retention --host-root . --request {request}", "REPORT_STATUS"),
    ):
        program = tools / name
        program.write_text(
            "#!/bin/sh\n"
            + f'test "$*" = "{expected}" || exit 98\n'
            + f'echo "{name}"\nexit "${status}"\n'
        )
        program.chmod(0o700)
    for native_status, report_status, expected in ((0, 0, 0), (7, 0, 7), (0, 9, 9), (7, 9, 9)):
        result = subprocess.run(
            ["/bin/sh", "-ec", combined["tasks"]["harness-maintain-checks"]["run"]],
            env={**os.environ, "PATH": mock_directory, "NATIVE_STATUS": str(native_status),
                 "REPORT_STATUS": str(report_status)},
            capture_output=True, text=True,
        )
        assert (result.returncode, result.stdout, result.stderr) == (
            expected, "chrono-harness\n", "chrono-host-bootstrap\n"
        )
assert not (retention_host / policy).exists()
assert retention_config["tasks"]["harness-setup"]["run"] == [
    "mise install", "sh .chrono-harness/setup-check-retention.sh"
]
assert not (empty / manifest).exists()
config = tomllib.loads((selected / manifest).read_text())
assert set(config["tools"]) == {"http:chrono-pr"}
assert json.loads((selected / ".chrono-harness/pr.json").read_text())["base"] == "dev"
assert (selected / ".github/workflows/harness-check.yml").is_file()
assert config["tasks"]["harness-check"]["run"] == "python3 check.py"

for host in (empty, selected, full):
    assert (host / "AGENTS.md").readlink() == Path("CLAUDE.md")
    assert (host / "CLAUDE.md").is_file()
    guide = (host / "AGENTS.md").read_text()
    assert guide == (host / "CLAUDE.md").read_text()
    assert "https://github.com/chrono-harness/chrono-harness-main" in guide
    if host == full:
        assert json.loads((host / ".chrono-harness/rules.json").read_text()) == {"mode": "all"}
        assert "## job.wait" in guide and "## artifact.cleanup" in guide
        assert "mise run harness-setup" in guide
        assert (host / "docs/licenses/trureturing-Apache-2.0.txt").is_file()
    else:
        assert not (host / ".chrono-harness/rules.json").exists()
        assert "## job.wait" not in guide
        assert not (host / "docs/licenses/trureturing-Apache-2.0.txt").exists()
    assert not (host / ".chrono-harness/instructions").exists()
    usage = (host / ".chrono-harness/USAGE.md").read_text()
    assert ("刷新根指南" in usage) == (host == full)

expected = ['http:chrono-cache', 'http:chrono-ci', 'http:chrono-diagnostics', 'http:chrono-distribution', 'http:chrono-harness', 'http:chrono-host-bootstrap', 'http:chrono-host-release', 'http:chrono-inputs', 'http:chrono-instructions', 'http:chrono-judge-ci', 'http:chrono-judge-cost', 'http:chrono-judge-filemap', 'http:chrono-judge-mixed', 'http:chrono-judge-projects', 'http:chrono-judge-registration', 'http:chrono-judge-routes', 'http:chrono-judge-workflow', 'http:chrono-pr', 'http:chrono-test-git', 'http:chrono-test-git-profile', 'http:chrono-worktree', 'http:verus']
default_config = tomllib.loads((full / manifest).read_text())
assert default_config["tasks"]["harness-setup"]["run"] == [
    "mise install", "mise exec -- chrono-instructions sync-rules --host-root ."
]
assert config["tasks"]["harness-setup"]["run"] == "mise install"
default_tools = default_config["tools"].copy()
assert default_tools == tomllib.loads(manifest.read_text())["tools"]
assert default_tools.pop("rust") == {"version": "1.95.0", "profile": "minimal"}
assert set(default_tools) == set(expected)
for tool in default_tools.values():
    assert set(tool["platforms"]) == {"linux-x64", "macos-arm64"}

for name, expected_tools in (
    ("verus", {"rust", "http:verus"}),
    ("judge-ci-verus", set(tomllib.loads((judge_ci / manifest).read_text())["tools"]) | {"rust", "http:verus"}),
):
    rendered = full.parent / name
    dependencies = tomllib.loads((rendered / manifest).read_text())["tools"]
    assert set(dependencies) == expected_tools
    for tool, value in dependencies.items():
        assert value == default_config["tools"][tool]
    assert "tool_dependencies:" not in (rendered / ".chrono-harness/template-answers.yml").read_text()

assert "业务源码位于 src/。" in (selected / "AGENTS.md").read_text()
for host, commands in [
    (full.parent / "cache", {"chrono-cache", "chrono-harness"}),
    (full.parent / "registration", {"chrono-judge-registration", "chrono-judge-routes", "chrono-harness"}),
    (diagnostics, {"chrono-diagnostics"}),
    (test_git, {"chrono-test-git", "chrono-test-git-profile"}),
    (worktree, {"chrono-worktree"}),
    (bootstrap, {"chrono-harness", "chrono-host-bootstrap", "chrono-judge-registration"}),
    (release, {"chrono-harness", "chrono-host-release", "chrono-host-bootstrap", "chrono-judge-registration"}),
    (inputs, {"chrono-harness", "chrono-inputs", "chrono-judge-registration", "chrono-judge-routes", "chrono-judge-filemap", "chrono-judge-mixed"}),
    (workflow, {"chrono-harness", "chrono-judge-workflow", "chrono-judge-projects", "chrono-judge-routes", "chrono-judge-registration"}),
    (projects, {"chrono-harness", "chrono-judge-projects", "chrono-judge-filemap", "chrono-judge-routes", "chrono-judge-registration"}),
    (judge_ci, {"chrono-harness", "chrono-judge-ci", "chrono-judge-projects", "chrono-judge-filemap", "chrono-judge-routes", "chrono-judge-mixed", "chrono-judge-registration"}),
    (mixed, {"chrono-harness", "chrono-judge-mixed", "chrono-judge-registration"}),
    (filemap, {"chrono-harness", "chrono-judge-filemap", "chrono-judge-mixed", "chrono-judge-registration"}),
    (routes, {"chrono-harness", "chrono-judge-routes", "chrono-judge-filemap", "chrono-judge-registration"}),
    (cost, {"chrono-harness", "chrono-judge-cost", "chrono-judge-filemap", "chrono-judge-registration"}),
]:
    assert (host / "AGENTS.md").read_text().splitlines()[0] == "# chrono-harness/chrono-harness-copier 工作说明"
    assert (host / ".chrono-harness/USAGE.md").read_text().splitlines()[0] == "# chrono-harness/chrono-harness-copier 工具入口"
    assert not (host / ".chrono-harness/pr.json").exists()
    tools = tomllib.loads((host / manifest).read_text())["tools"]
    assert set(tools) == {"http:" + command for command in commands}
    for name, declaration in tools.items():
        assert declaration == default_tools[name]
