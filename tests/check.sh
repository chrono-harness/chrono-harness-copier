#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
node --test tests/roadmap.test.cjs
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --python ">=3.11" --with PyYAML==6.0.3 python tests/test_release.py
stage_parent=${TMPDIR:-/tmp}
if [[ ${GITHUB_ACTIONS:-} == true && -n ${RUNNER_TEMP:-} ]]; then
  stage_parent=$RUNNER_TEMP
elif git_dir=$(git rev-parse --absolute-git-dir 2>/dev/null) && [[ -f "$git_dir/commondir" && ! -L copier-renders ]]; then
  stage_parent=$PWD/copier-renders
  mkdir -p -- "$stage_parent"
fi
stage_parent=$(cd -- "$stage_parent" && pwd -P)
stage=$(mktemp -d "$stage_parent/copier-check.XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT
uvx --from copier==9.19.1 copier copy --defaults --vcs-ref HEAD -d repository=chrono-harness/chrono-harness-copier "$PWD" "$stage/default"
uvx --from copier==9.19.1 copier copy --defaults --vcs-ref HEAD -d 'features=[]' -d github_templates=false -d manage_roadmap=false . "$stage/empty"
uvx --from copier==9.19.1 copier copy --defaults --vcs-ref HEAD \
  -d 'features=["pr"]' -d repository=chrono-harness/chrono-harness-copier \
  -d 'project_guide=业务源码位于 src/。' -d generate_check=true -d 'check_command=python3 check.py' . "$stage/selected"
uvx --from copier==9.19.1 copier copy --defaults --vcs-ref HEAD \
  -d 'features=[]' -d local_check_retention=true "$PWD" "$stage/local-check-retention"
(
  cp -R "$stage/local-check-retention" "$stage/retention-update"
  cd "$stage/retention-update"
  sh .chrono-harness/setup-check-retention.sh
  python3 -c 'import json; p=json.load(open(".chrono-harness/retention.json")); assert p["max_lifetime_seconds"] == 86400 and p["producers"]["check-original"] == [".chrono-harness/state/"]'
  echo '{"custom":"host-owned"}' >.chrono-harness/retention.json
  sh .chrono-harness/setup-check-retention.sh
  git init -qb dev
  git add .
  git -c user.name=Copier -c user.email=copier@example.invalid commit -qm "Host with its own policy"
  uvx --from copier==9.19.1 copier update --defaults --vcs-ref HEAD \
    --answers-file .chrono-harness/template-answers.yml -d local_check_retention=false
  grep -Fxq '{"custom":"host-owned"}' .chrono-harness/retention.json
  test ! -e .chrono-harness/maintain-checks.json
  test ! -e .chrono-harness/setup-check-retention.sh
)
# Render the self-hosted publisher and both choices of the host release contract.
source_plan=$(cat .chrono-harness/release.json)
binary_plan=$(python3 -c 'import json,sys; p=json.load(sys.stdin); p.update(kind="binary",version_policy="explicit",binary="demo",build="tools/build.sh"); print(json.dumps(p))' < .chrono-harness/release.json)
for kind in copier binary; do
  plan=$source_plan
  if [[ "$kind" == binary ]]; then plan=$binary_plan; fi
  uvx --from copier==9.19.1 copier copy --defaults --vcs-ref HEAD \
    -d 'features=[]' -d "release_plan=$plan" . "$stage/$kind"
  cmp .github/release/plan.py "$stage/$kind/.github/release/plan.py"
  cmp .github/release/publish.py "$stage/$kind/.github/release/publish.py"
done
# A host can keep roadmap automation while opting out of every locally installed tool.
test ! -e "$stage/copier/.config/mise/conf.d/chrono-harness.toml"
test ! -e "$stage/default/.chrono-harness/ci/host_adapters.rs"
uvx --from copier==9.19.1 copier copy --defaults --vcs-ref HEAD \
  -d repository=sample/strict-example \
  -d 'strict_host_adapters={"binary":"chrono-example","verus_macro_crate":"chrono_example","ci_tools":["chrono-harness","verus"]}' \
  . "$stage/strict"
grep -Fq 'use chrono_example::verus;' "$stage/strict/.chrono-harness/ci/host_adapters.rs"
grep -Fq 'set -- chrono-harness verus' "$stage/strict/.chrono-harness/ci/host_adapters.rs"
grep -Fq '$RUNNER_TEMP/example-mise.XXXXXXXX' "$stage/strict/.chrono-harness/ci/host_adapters.rs"
grep -Fq 'let selected = true;' "$stage/strict/.chrono-harness/ci/host_adapters.rs"
uvx --from copier==9.19.1 copier copy --defaults --vcs-ref HEAD \
  -d 'features=["cache"]' \
  -d 'strict_host_adapters={"binary":"chrono-example","verus_macro_crate":"chrono_example","ci_tools":["verus"]}' \
  . "$stage/strict-without-instructions"
grep -Fq 'let selected = false;' "$stage/strict-without-instructions/.chrono-harness/ci/host_adapters.rs"
cmp .github/roadmap.cjs "$stage/copier/.github/roadmap.cjs"
cmp .github/workflows/issue-roadmap.yml "$stage/copier/.github/workflows/issue-roadmap.yml"
cmp .github/workflows/release.yml "$stage/copier/.github/workflows/release.yml"
grep -q '^  build:' "$stage/binary/.github/workflows/release.yml"
test ! -e "$stage/empty/.github/workflows/release.yml"
test ! -e "$stage/empty/.github/release"
for tool in cache registration diagnostics host-bootstrap host-release inputs judge-routes judge-cost worktree judge-filemap judge-mixed judge-projects judge-ci judge-workflow test-git verus; do
  uvx --from copier==9.19.1 copier copy --defaults --vcs-ref HEAD \
    -d repository=chrono-harness/chrono-harness-copier -d "features=[\"$tool\"]" . "$stage/$tool"
done
uvx --from copier==9.19.1 copier copy --defaults --vcs-ref HEAD \
  -d 'features=["judge-ci","verus"]' . "$stage/judge-ci-verus"
uv run --no-project --python ">=3.11" python tests/check_render.py "$stage/empty" "$stage/selected" "$stage/default" "$stage/diagnostics" "$stage/host-bootstrap" "$stage/host-release" "$stage/inputs" "$stage/judge-routes" "$stage/judge-cost" "$stage/worktree" "$stage/judge-filemap" "$stage/judge-mixed" "$stage/judge-projects" "$stage/judge-ci" "$stage/judge-workflow" "$stage/test-git"

# Exercise a real host that edits its guide and later changes its tool choices.
(
  cd "$stage/default"
  git init -q -b dev
  echo '保留这条宿主指令。' >> CLAUDE.md
  record_host() {
    git add .
    git -c user.name=Copier -c user.email=copier@example.invalid commit -qm 'Record local host inputs'
  }
  record_host
  for choice in '[]' '["instructions"]'; do
    uvx --from copier==9.19.1 copier update --defaults --vcs-ref HEAD \
      --answers-file .chrono-harness/template-answers.yml -d "features=$choice"
    echo "Verify tool choice $choice"
    if [[ -n "$(git ls-files --unmerged)" ]]; then
      git diff --cc -- CLAUDE.md
      git ls-files --unmerged
      exit 1
    fi
    grep -Fxq '保留这条宿主指令。' AGENTS.md
    if [[ "$choice" = '[]' ]]; then
      test ! -f docs/licenses/trureturing-Apache-2.0.txt
      if grep -Fq '<!-- chrono-instructions:begin -->' CLAUDE.md; then exit 1; fi
    else
      test -f docs/licenses/trureturing-Apache-2.0.txt
      grep -Fxq '## job.wait' CLAUDE.md
    fi
    record_host
  done
)
