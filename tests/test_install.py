"""Exercise the rendered installer against command-boundary fixtures."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

# The same Python program is the fake external command and its test driver.
# The shell under test sees the normal argv, stdin, output files and exit status.
def external(name, args):
    state = Path(os.environ["INSTALL_FIXTURE"])
    with (state / "calls").open("a") as log:
        print(json.dumps([name, *args]), file=log)
    if name == "git":
        raise AssertionError("install must not read the consumer's Git branch")
    elif name == "uname":
        print({"-s": "Linux", "-m": "x86_64"}[args[0]])
    elif name == "curl":
        output = Path(args[args.index("-o") + 1])
        if "-D" not in args:
            shutil.copyfile(state / "mock", output)
        else:
            assert not output.is_relative_to(Path.cwd())
            assert args[-1].startswith("https://api.github.com/repos/chrono-harness/chrono-harness-test-git/releases?")
            if os.environ.get("FAULT") == "api":
                return 22
            number = args[-1].rsplit("=", 1)[1]
            assert number in ("1", "2")
            Path(args[args.index("-D") + 1]).write_text('Link: <url>; rel="next"\n' if number == "1" else "")
            output.write_text(number)
    elif name == "sha256sum":
        data = sys.stdin.buffer.read()
        digest = os.environ["SEED_DIGEST"] if data == (state / "mock").read_bytes() else hashlib.sha256(data).hexdigest()
        print(digest, "-")
    elif name == "chrono-host-release":
        operation, flag, command, repo, selector, linux, mac, *pages = args
        assert (operation, flag, repo) == ("resolve-install-v1", "--mise-tool", "chrono-harness/chrono-harness-test-git")
        assert (linux, mac) == (command + "-linux-x86_64", command + "-macos-aarch64")
        assert [Path(p).read_text() for p in pages] == ["1", "2"]
        if os.environ.get("FAULT") == "selection":
            return 2
        if selector == "preview":
            version = os.environ["PREVIEW"]
        elif selector == "stable":
            version = os.environ.get("STABLE", "1.0.0")
        else:
            assert re.fullmatch(r"v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", selector)
            version = selector[1:]
        digest = hashlib.sha256(command.encode()).hexdigest()
        print(f'[tools."http:{command}"]\nversion="{version}"\nbin="{command}"')
        print(f'[tools."http:{command}".platforms]')
        for platform, asset in (("linux-x64", linux), ("macos-arm64", mac)):
            print(f'{platform} = {{url="https://github.com/{repo}/releases/download/v{version}/{asset}",checksum="sha256:{digest}"}}')
    elif name == "mise":
        if args == ["settings", "get", "disable_tools"]:
            print(os.environ.get("DISABLED", "[]"))
        elif args[:3] == ["config", "get", "--file"]:
            config = tomllib.loads(Path(args[3]).read_text())
            tool = re.fullmatch(r'tools\."(http:[a-z-]+)"\.platforms\.linux-x64\.checksum', args[4])[1]
            print(config["tools"][tool]["platforms"]["linux-x64"]["checksum"])
        else:
            assert args[0] == "-C"
            if args[2:] == ["install"]:
                if os.environ.get("FAULT") == "install":
                    return 9
            else:
                assert args[2] == "which"
                payload = state / args[3]
                payload.write_text("wrong bytes" if os.environ.get("FAULT") == "cache" else args[3])
                print(payload)
    else:
        raise AssertionError(name)
    return 0


def exercise(host, state, *, pinned):
    mock = state / "mock"
    mock.write_text("#!" + sys.executable + "\n" + Path(__file__).read_text())
    mock.chmod(0o700)
    for name in ("git", "uname", "curl", "sha256sum", "mise"):
        (state / name).symlink_to(mock.name)
    installer = host / ".chrono-harness/install-tools.sh"
    seed = re.search(r"Linux-x86_64\).*?seed_sha=([a-f0-9]{64})", installer.read_text())[1]
    env = dict(PATH=str(state) + os.pathsep + os.defpath, INSTALL_FIXTURE=str(state), SEED_DIGEST=seed,
               PREVIEW="1.0.0-alpha.1")
    receipt = host / ".config/mise/conf.d/zz-chrono-harness-resolved.toml"
    assert not receipt.is_symlink() and not receipt.exists()

    def run(status=0, **options):
        (state / "calls").write_text("")
        result = subprocess.run(["/bin/sh", str(installer)], cwd=host, env={**env, **options},
                                capture_output=True, text=True)
        assert result.returncode == status, (result.returncode, result.stderr)
        return [json.loads(line) for line in (state / "calls").read_text().splitlines()]

    def versions():
        tools = tomllib.loads(receipt.read_text()).get("tools", {}) if receipt.exists() else {}
        return {key: value["version"] for key, value in tools.items()}

    if pinned:
        base = host / ".config/mise/conf.d/chrono-harness.toml"
        selection = base.read_text()
        for name, config in tomllib.loads(selection)["tools"].items():
            binary = name.removeprefix("http:")
            digest = hashlib.sha256(binary.encode()).hexdigest()
            selection = selection.replace(config["platforms"]["linux-x64"]["checksum"], "sha256:" + digest)
        base.write_text(selection)
        calls = run()
        assert not receipt.exists() and not any(c[0] == "curl" for c in calls)
        run(CHRONO_TOOL_CHANNEL="stable")
        assert set(versions().values()) == {"1.0.0"}
        before = receipt.read_bytes()
        run(9, FAULT="install")
        assert receipt.read_bytes() == before
        calls = run()
        assert not receipt.exists() and not any(c[0] == "curl" for c in calls)
        assert base.read_text() == selection
        return

    first = run()
    assert len([c for c in first if c[0] == "curl" and "-D" in c]) == 2
    primary = "http:chrono-test-git"
    profile = "http:chrono-test-git-profile"
    assert versions() == {primary: "1.2.3", profile: "1.0.0-alpha.1"}
    # The repository pin survives new releases. Explicit installation choices override it.
    run(PREVIEW="1.0.0-alpha.2")
    assert versions() == {primary: "1.2.3", profile: "1.0.0-alpha.2"}
    for branch, selector, expected in (
        ("main", "preview", "1.0.0-alpha.1"),
        ("dev", "stable", "1.0.0"),
        ("personal/experiment", "v2.4.1", "2.4.1"),
        ("", "preview", "1.0.0-alpha.1"),
        ("", "v2.4.1-rc.2", "2.4.1-rc.2"),
    ):
        context = dict(GITHUB_ACTIONS="true", GITHUB_SHA="detached-sha",
                       GITHUB_EVENT_NAME="pull_request", GITHUB_HEAD_REF=branch,
                       GITHUB_BASE_REF="main", GITHUB_REF="refs/tags/detached")
        calls = run(CHRONO_TOOL_CHANNEL=selector, **context)
        assert not any(call[0] == "git" for call in calls)
        assert versions() == {primary: expected, profile: expected}
    run(CHRONO_TOOL_CHANNEL="stable", STABLE="1.1.0")
    assert set(versions().values()) == {"1.1.0"}
    run(CHRONO_TOOL_CHANNEL="v2.4.1", PREVIEW="9.0.0-alpha.2", STABLE="9.0.0")
    assert set(versions().values()) == {"2.4.1"}
    before = receipt.read_bytes()
    for invalid in ("", "all", "development", "v1;cmd", "v1.2", "v1.2.3\nbad"):
        calls = run(1, CHRONO_TOOL_CHANNEL=invalid)
        assert not any(c[0] == "curl" for c in calls)
        assert receipt.read_bytes() == before
    for fault, status in (("api", 22), ("selection", 2), ("cache", 1), ("install", 9)):
        run(status, FAULT=fault)
        assert receipt.read_bytes() == before
    run(DISABLED='["http:chrono-test-git"]')
    assert set(versions()) == {"http:chrono-test-git-profile"}
    calls = run(DISABLED='["http:chrono-test-git","http:chrono-test-git-profile"]')
    assert not versions() and not any(c[0] in ("curl", "chrono-host-release") for c in calls)


if __name__ == "__main__":
    command = Path(sys.argv[0]).name
    if command != "test_install.py":
        raise SystemExit(external(command, sys.argv[1:]))
    for host, pinned in ((sys.argv[1], False), (sys.argv[2], True)):
        with tempfile.TemporaryDirectory() as work:
            exercise(Path(host).resolve(), Path(work), pinned=pinned)
