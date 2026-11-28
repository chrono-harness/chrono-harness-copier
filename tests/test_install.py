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
NEXT = 'HTTP/2 200\r\nLink: <url>; rel="next"\r\n\r\n'
DONE = "HTTP/2 200\r\n\r\n"

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
            last = int(os.environ.get("LAST_PAGE", "2"))
            assert 1 <= int(number) <= last
            headers = Path(args[args.index("-D") + 1])
            if os.environ.get("FAULT") != "no-headers":
                raw = NEXT if int(number) < last else DONE
                if os.environ.get("FAULT") == "truncated":
                    raw = "HTTP/2 200\r\n"
                headers.write_bytes(raw.encode())
            output.write_text(number)
    elif name in ("mv", "rm"):
        target = Path(args[-1])
        if args[:2] == ["-rf", "--"]:
            assert target.name.startswith((".chrono-install.", "chrono-install."))
            shutil.rmtree(target)
        else:
            selection = Path.cwd() / ".chrono-harness/state/tool-selection"
            legacy = Path.cwd() / ".config/mise/conf.d/zz-chrono-harness-resolved.toml"
            assert args[0] == "-f"
            if name == "mv":
                assert len(args) == 3 and target == selection and Path(args[1]).name == "versions.toml"
            else:
                assert len(args) == 2 and target in (selection / "versions.toml", legacy)
            if os.environ.get("FAULT") == name:
                return 17
            if name == "mv":
                Path(args[1]).replace(selection / "versions.toml")
            else:
                target.unlink(missing_ok=True)
    elif name == "sha256sum":
        data = sys.stdin.buffer.read()
        digest = os.environ["SEED_DIGEST"] if data == (state / "mock").read_bytes() else hashlib.sha256(data).hexdigest()
        print(digest, "-")
    elif name == "chrono-host-release":
        if args[:2] == ["resolve-install-v1", "--page-state"]:
            assert len(args) == 3
            path = Path(args[2])
            if not path.is_file():
                return 2
            states = {NEXT.encode(): "next", DONE.encode(): "done"}
            if path.read_bytes() not in states:
                return 2
            print(states[path.read_bytes()])
            return 0
        operation, flag, command, repo, selector, linux, mac, *pages = args
        assert (operation, flag, repo) == ("resolve-install-v1", "--mise-tool", "chrono-harness/chrono-harness-test-git")
        assert (linux, mac) == (command + "-linux-x86_64", command + "-macos-aarch64")
        last = int(os.environ.get("LAST_PAGE", "2"))
        if os.environ.get("FAULT") in ("no-headers", "truncated"):
            # A partial array is valid release JSON; the resolver cannot detect the missing page.
            last = 1
        assert [Path(p).read_text() for p in pages] == [str(i) for i in range(1, last + 1)]
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
            tool, field = re.fullmatch(r'tools\."(http:[a-z-]+)"\.(.+)', args[4]).groups()
            value = config["tools"][tool]
            for key in field.split("."):
                value = value[key]
            print(value)
        else:
            assert args[0] == "-C"
            if args[2] == "install":
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
    for name in ("git", "uname", "curl", "sha256sum", "mise", "mv", "rm"):
        (state / name).symlink_to(mock.name)
    installer = host / ".chrono-harness/install-tools.sh"
    seed = re.search(r"Linux-x86_64\).*?seed_sha=([a-f0-9]{64})", installer.read_text())[1]
    env = dict(PATH=str(state) + os.pathsep + os.defpath, INSTALL_FIXTURE=str(state), SEED_DIGEST=seed,
               PREVIEW="1.0.0-alpha.1")
    receipt = host / ".chrono-harness/state/tool-selection/versions.toml"
    receipt.parent.mkdir(parents=True)
    assert not receipt.is_symlink() and not receipt.exists()

    def run(status=0, *, diagnostic=None, **options):
        (state / "calls").write_text("")
        result = subprocess.run(["/bin/sh", str(installer)], cwd=host, env={**env, **options},
                                capture_output=True, text=True)
        assert result.returncode == status, (result.returncode, result.stderr)
        if diagnostic is not None:
            assert result.stderr == diagnostic + "\n", (diagnostic, result.stderr)
        assert not list((host / ".config/mise/conf.d").glob(".chrono-install.*"))
        return [json.loads(line) for line in (state / "calls").read_text().splitlines()]

    def versions():
        tools = tomllib.loads(receipt.read_text()) if receipt.exists() else {}
        return {"http:" + name: values[0] for name, values in tools.items()}

    state_dir = receipt.parent.parent
    legacy = host / ".config/mise/conf.d/zz-chrono-harness-resolved.toml"
    # Reject simultaneous invalid targets in the original order, without downloading.
    receipt.parent.rmdir()
    state_dir.rmdir()
    state_dir.symlink_to(state / "uncreated")
    legacy.mkdir()
    directory_error = "Expected an installation state directory: "
    file_error = "Expected a regular installation selection: "
    def reject(diagnostic):
        calls = run(1, diagnostic=diagnostic, CHRONO_TOOL_CHANNEL="stable")
        assert not any(call[0] in ("curl", "chrono-host-release") for call in calls)

    reject(directory_error + str(state_dir))
    assert state_dir.is_symlink() and not state_dir.exists()
    state_dir.unlink()
    receipt.parent.mkdir(parents=True)
    receipt.symlink_to(state / "uncreated")
    reject(file_error + str(legacy))
    assert legacy.is_dir() and receipt.is_symlink()
    legacy.rmdir()
    reject(file_error + str(receipt))
    receipt.unlink()

    # A directory is a destination operand to mv. Reject it before staging or publishing.
    receipt.mkdir()
    neighbor = receipt / "source"
    neighbor.write_bytes(b"preserve this file")
    calls = run(1, CHRONO_TOOL_CHANNEL="preview")
    assert neighbor.read_bytes() == b"preserve this file" and list(receipt.iterdir()) == [neighbor]
    assert not any(call[0] == "curl" for call in calls)
    neighbor.unlink()
    receipt.rmdir()
    receipt.symlink_to(state / "uncreated")
    calls = run(1, CHRONO_TOOL_CHANNEL="stable")
    assert receipt.is_symlink() and not (state / "uncreated").exists()
    assert not any(call[0] == "curl" for call in calls)
    receipt.unlink()

    for filename in ("source.swift", "versions.toml.copy", ".hidden"):
        neighbor = receipt.with_name(filename)
        neighbor.write_bytes(b"keep")
        calls = run(1, CHRONO_TOOL_CHANNEL="stable")
        assert neighbor.read_bytes() == b"keep" and not any(row[0] == "curl" for row in calls)
        neighbor.unlink()

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
        exact = ["mise", "-C"]
        requested = ["%s@%s" % (tool, cfg["version"]) for tool, cfg in tomllib.loads(selection)["tools"].items()]
        assert [a[4:] for a in calls if a[:2] == exact and a[3] == "install"] == [requested, []]
        run(CHRONO_TOOL_CHANNEL="stable")
        assert set(versions().values()) == {"1.0.0"}
        before = receipt.read_bytes()
        run(9, FAULT="install")
        assert receipt.read_bytes() == before
        calls = run(17, FAULT="rm")
        assert receipt.read_bytes() == before and not any(c[0] in ("curl", "chrono-host-release") for c in calls)
        calls = run()
        assert not receipt.exists() and not any(c[0] == "curl" for c in calls)
        assert base.read_text() == selection
        return

    legacy.write_bytes(b"# previous installation\n")
    for fault, status in (("no-headers", 2), ("truncated", 2), ("mv", 17)):
        run(status, FAULT=fault)
        assert not receipt.exists() and legacy.read_bytes() == b"# previous installation\n"
    first = run(LAST_PAGE="10")
    assert not legacy.exists()
    assert len([c for c in first if c[0] == "curl" and "-D" in c]) == 10
    primary = "http:chrono-test-git"
    profile = "http:chrono-test-git-profile"
    assert versions() == {primary: "1.2.3", profile: "1.0.0-alpha.1"}
    assert [a[4:] for a in first if a[0] == "mise" and a[3:4] == ["install"]] == [
        [primary + "@1.2.3", profile + "@1.0.0-alpha.1"], []
    ]
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
    extra = receipt.with_name("..dangling")
    extra.symlink_to(state / "uncreated")
    reject("Unexpected installation data entry: " + str(extra))
    assert extra.is_symlink() and not extra.exists() and receipt.read_bytes() == before
    extra.unlink()
    for invalid in ("", "all", "development", "v1;cmd", "v1.2", "v1.2.3\nbad"):
        calls = run(1, CHRONO_TOOL_CHANNEL=invalid)
        assert not any(c[0] == "curl" for c in calls)
        assert receipt.read_bytes() == before
    for fault, status in (("api", 22), ("selection", 2), ("no-headers", 2), ("truncated", 2), ("mv", 17), ("cache", 1), ("install", 9)):
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
