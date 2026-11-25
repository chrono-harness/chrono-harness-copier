# chrono-harness-copier

组件的用途、开发仓库和示例见 [Chrono Harness 用户与开发者入口](https://github.com/chrono-harness/chrono-harness-main)。

仓库默认安装 GitHub 的四类 Issue 表单和 PR 模板。已有协作模板的仓库可在 Copier 中关闭 `github_templates`。

本仓开发 Chrono Harness 的 Copier 源模板。已有仓库可以按需安装组件并在后续升级时保留本地配置。新建 GitHub 仓库可用 [chrono-harness-template 的 Use this template](https://github.com/chrono-harness/chrono-harness-template/generate)。

在已有仓库的根目录运行 Copier。默认勾选全部可安装组件和 Verus。`test-git` 提供两个测试命令 `chrono-test-git` 和 `chrono-test-git-profile`。用空格取消任意工具，也可以全部取消。工具从各自版本固定的发行下载，mise 按 SHA-256 校验，安装在工作树外。选中 Verus 会一并安装其依赖的 Rust 1.95.0。

单选 cache 会安装 runner，恢复缓存、运行命令探测和保管原件时使用。默认选中 diagnostics，也可单选用来回收宿主滚动日志。只选 worktree 的宿主若启用 `.chrono-harness/logging.json`，须同时选择 diagnostics；未启用日志的宿主可取消。单选 worktree 可创建、维护和清理工作树。使用需要读取项目登记的检查流程时可加选 registration。选中 host-bootstrap 或 host-release 会一并安装其使用的 chrono-judge-registration。选装 host-release 还会安装校验原始构建报告的 host-bootstrap。单选 host-bootstrap 或 host-release 也会安装 runner，用于校验编译器输出、进程回执和保管已登记的产物。单选 judge-mixed 会安装 runner 和 registration。runner 校验原生判官请求，registration 提供固定提交的登记与语义文件。mixed 的分类和文档路径查询可以单独运行。单选 judge-filemap 会安装 runner、registration 和 mixed。FILEMAP 用 runner 读取固定 Git 端点、执行受限操作，用 registration 和 mixed 解释提交登记和变更内容，选择受影响的测试。单选 inputs 会安装 runner 读取固定 Git 事实、执行受限命令并交接保管原件，也安装 registration 解释 capture 和有执行单元的 compose。启用滚动日志时同时勾选 diagnostics。带执行单元的 compose 还使用 routes、FILEMAP 和 mixed。pair 和无执行单元的 compose 可离线单独运行。单选 registration 会安装 runner 和 routes。完整登记检查用 runner 读取固定提交、记录进程回执，用 routes 校验执行单元分配。

单选 judge-projects 会安装 runner、FILEMAP、routes 和 registration，用于执行登记操作、读取受影响节点、校验计划和原始执行回执，以及解释退役测试。单选 judge-workflow 会安装 runner、projects、routes 和 registration。runner 核验封存请求和进程记录，其余工具读取项目结果、核对计划与回执、解释固定提交的登记。单选 judge-ci 会为 FILEMAP 的端点查询安装 runner，也安装 FILEMAP 和 projects，用于按变更选择测试、核对项目配对，以及执行选中的计划并收集原始进程回执。完整调度和收集使用随装的 routes、mixed 与 registration。单选 routes 会安装 runner、FILEMAP 和 registration，用于核验原生请求、读取固定源码、解读影响范围和退役测试。单选 judge-cost 会安装 runner、FILEMAP 和 registration，分别用于校验请求、读取变更成本所需的输入和解释登记。只生成工作流的仓库可以单选 ci。需要按变更调度执行单元或汇总其报告时，同时选择 ci 和 judge-ci。支持 Linux x86_64 和 macOS arm64。

```sh
uvx --from copier==9.19.1 copier copy gh:chrono-harness/chrono-harness-copier .
mise trust
mise run harness-setup
```

首次安装选择最新的正式版本。用 `--vcs-ref <tag>` 可以选择指定正式版或预览版。Copier 将选中的标签和本仓答案写入 `.chrono-harness/template-answers.yml`。

安装时可填写本仓职责、源码位置和验证命令，模板会将它们直接写入根指南。每个仓库的 `AGENTS.md` 链接到本仓的 `CLAUDE.md`。默认生成的根文件包含首次安装、PR 与验证入口，以及 chrono-harness-instructions 发布的默认规则全文。克隆仓库即可阅读。工具的版本和校验值在本仓的 mise 清单中。

模板安装的 `.chrono-harness/rules.json` 默认为 `{"mode":"all"}`，省略该文件同样接受全部当前和以后新增的规则。每次开始任务时，运行 `mise run harness-setup`。选装 instructions 的仓库会用本仓固定版本的 `chrono-instructions sync-rules --host-root .` 读取上游已发布的规则，按本仓选择更新根指南。成功后重新阅读指南。仓库自己的职责、源码位置和检查入口放在生成块之外。同步失败会保留原指南。

| 需求 | 配置 |
| --- | --- |
| 全部接纳 | 省略文件或 `{"mode":"all"}` |
| 屏蔽个别 ID | `{"mode":"all","exclude":["job.wait"]}` |
| 仅接纳部分 ID | `{"mode":"only","include":["artifact.cleanup","job.wait"]}` |
| 关闭基础规则 | `{"mode":"off"}` |

查阅[上游规则及稳定 ID](https://raw.githubusercontent.com/chrono-harness/chrono-harness-instructions/published-rules/rules.json)。本地说明可写在 `CLAUDE.md` 末尾的“本仓追加指令”一节。重新选择工具时，Copier 会保留这些说明。启用继承需要网络和 curl；读取失败时命令报告失败。关闭继承可以离线工作。

本地 scoped 检查会登记供单元报告和汇总读取的原件。采用 runner 维护的宿主可选 `local_check_retention: true`，使用 `mise run harness-setup` 安装 runner 并初始化缺失的 24 小时策略，维护入口为 `mise run harness-maintain-checks`。将初始化的策略提交到宿主仓库。已有 `.chrono-harness/retention.json` 的宿主保留自己的窗口和生产者。使用 worktree 或其他专属维护入口的宿主继续使用原入口。生成的 `.chrono-harness/USAGE.md` 说明按小时调度、报告引用和窗口内转存。只下载工具或只输出 stdout 的检查可以关闭这个选项。

选择生成业务检查时，填写项目现有的检查命令和运行平台。本地与 GitHub Actions 都会执行 `mise run harness-check`。已有登记式检查的项目可以沿用自己的工作流。

先提交工作树里的本地改动。要调整本仓安装的工具，运行下面的命令重新选择，然后运行 `mise run harness-setup`。取消选项后，本仓的安装清单会移除对应工具。共享缓存仍可能供其他仓库使用。

```sh
uvx --from copier==9.19.1 copier update --vcs-ref :current: --answers-file .chrono-harness/template-answers.yml
```

从 alpha.5 迁移时，先核对旧生成块、catalog、manifest 和 host-context 中的本地修改。将选择迁入 `.chrono-harness/rules.json`，把本仓追加说明放回 `CLAUDE.md`。确认继承结果后删除旧生成块和已经迁移的输入。

升级模板本身时，将 `:current:` 换为目标发行标签。Copier 将模板变更与本仓已提交的定制合并，重叠修改由本仓处理。审核生成的 diff 后提交。

全部工具和业务检查都取消时，可以跳过 mise 步骤。选择记录位于 `.chrono-harness/template-answers.yml`，规则取舍归宿主的 `.chrono-harness/rules.json`。

## 迁移已有宿主的 Copier 来源

原 `chrono-harness-template` 的 Copier 宿主保留自己的选择和追加说明。迁移前提交已修改的文件，从 `.chrono-harness/template-answers.yml` 读取当前 `_commit` 标签，在新旧源上核对同一标签的 Git 文件树。以下命令在宿主内执行，将第一行的标签改成本仓当前记录的值。

```sh
tag=v0.1.1
audit=$(mktemp -d)
git -C "$audit" init -q
tree_at() {
  git -C "$audit" fetch --quiet --depth=1 --no-tags "$1" "refs/tags/$tag" &&
    git -C "$audit" rev-parse 'FETCH_HEAD^{tree}'
}
old_tree=$(tree_at https://github.com/chrono-harness/chrono-harness-template.git) &&
new_tree=$(tree_at https://github.com/chrono-harness/chrono-harness-copier.git) &&
test -n "$old_tree" && test "$old_tree" = "$new_tree"
```

树相同后，把 answers 的 `_src_path` 改成 `gh:chrono-harness/chrono-harness-copier`，保留 `_commit` 及其他回答，提交这行变更。先用当前标签验证，再按需升级目标版本。

```sh
uvx --from copier==9.19.1 copier update --defaults --vcs-ref "$tag" --answers-file .chrono-harness/template-answers.yml
```

核对生成的 diff 和本仓的业务检查。临时的 `$audit` 在比较完毕后可以删除。本仓开发者从 `dev` 开分支，修改 `scaffold/` 或 `copier.yml`，在仓库根运行 `./tests/check.sh` 验证默认选装、宿主定制和发布配方。

## Issue 与版本路线图

模板默认启用 `manage_roadmap`。在仓库的 **Issues → Milestones** 查看本仓路线图。新建或重开的事项保留已有里程碑。未分配事项进入 `.chrono-harness/release.json` 的 `version` 所对应的里程碑（例如 `v0.1.0`）。尚未制定版本计划或该版本已经正式发布时，事项进入 `Backlog`。维护者可以随时调整单项归属。PR 的 `Closes #123` 由 GitHub 在合入默认分支时关闭对应事项。

实际发布的测试版和正式版显示在对应版本的里程碑里。正式版公开且该里程碑开放事项为零时自动关闭。重开其中的事项会恢复里程碑。选择 `publisher_workflow` 时填写本仓发布工作流的名称，以接收 Actions 使用仓库令牌发布后的完成事件。手动运行 `Issue roadmap` 可从 GitHub 当前数据重算。工作流只在本仓读 Release 和写 Issues、Milestones。

发布工作流返回失败或超时时，路线图按 GitHub run ID 创建一条带 `release-failure` 标签的 Issue，保留提交及原尝试链接。同一运行重试成功会关闭该事项；新版本的修复可用 PR 的关闭引用关联原故障。

### 自动发布

`release_plan` 可以留空。选装后，Copier 将本仓的独立发布工作流和脚本写入宿主。宿主在 `.chrono-harness/release.json` 登记目标 `version`、开发分支检查的工作流 `check.file` 与名称 `check.name`，并在 `consumer` 中指定真实下游的仓库、分支、安装清单、落地工作流和实际验收步骤。宿主可从本仓的 release.json 开始配置。

`kind: copier` 发布固定 Git 提交。下游用自己的 Copier answers 登记来源与预览标签，工作流使用该标签渲染并核对选装的宿主文件。`kind: binary` 发布一个 Linux x86_64、macOS arm64 双平台命令，额外填写 `binary` 和宿主的 `build` 可执行文件路径。工作流给该入口传入平台和输出目录；入口执行产品自己的构建与验收并将文件写为 `<binary>-<platform>`。下游按固定版本、下载地址和两个 SHA-256 安装。

dev 落地检查通过后，工作流以该次检查的运行号发布预览。下游采用并通过登记的实际验收后，在提供方 dev 上派发 Release 工作流；它核对双方提交、落地任务、步骤与公开预览，快进 main 并从同一 SHA 发布正式版。二进制正式版沿用已经验证的预览字节。发布新版本时在 dev 更新目标版本。

Copier 源码产品可选 `version_policy: next_patch`。新提交在最高已公开正式版上递增补丁。需要次版本或主版本时，将仓内 `version` 提高到对应目标。路线图将新事项分配到同一版本里程碑。已经正式发布的提交或其祖先再次收到事件时直接结束。默认的 `explicit` 采用仓内版本，二进制产品沿用原生程序的版本声明。

## 开发模板

模板选项在 `copier.yml`，写入宿主的文件在 `scaffold/`。修改模板后，从仓库根目录运行 `./tests/check.sh`。

本仓自检将渲染副本交给比较和更新检查，退出时立即清理本次副本。在 Git 关联工作树中，副本位于工作树的 `copier-renders/`。托管工作树的宿主把该业务目录登记为可回收，独立维护任务回收到期工作树时一起清除中断遗留的副本。GitHub Actions 使用作业的 `RUNNER_TEMP`。长期主检出、源码归档及已有 `copier-renders` 符号链接的工作树使用 `TMPDIR`（缺省 `/tmp`）；强制终止后的保留期限由临时目录的维护者决定。


### 严格宿主的 CI 安装及标签发布

采用 shell 的 mise 安装入口、`source → build → publish` 标签工作流且启用严格 FILEMAP 的 Rust 工具仓，可以设置 `strict_host_adapters`。填写发布二进制名 `binary`、工作流实际安装的有序命令清单 `ci_tools` 和测试项目已有的 Verus 宏导出 crate 名 `verus_macro_crate`。模板生成 `.chrono-harness/ci/host_adapters.rs`。默认空配置不生成该文件。

本宿主把安装入口、发布 workflow 及生成的绑定根登记为 program，关联同一次受影响的整 crate Verus 操作与专属 Cargo 行为检查。Cargo 测试目标直接使用同一文件，本配置的测试项目使用 dev-dependencies `toml = "0.9"`（parse、serde、std）、`serde_yaml = "0.9"`、`tree-sitter = "0.25"` 和 `tree-sitter-bash = "0.25"`，分别读取实际工作流、安装脚本和发布命令。Verus 检查管理器选择、顺序和前置作业条件；实际 POSIX 和 GitHub 行为需要下游运行验收。源绑定固定当前 manager 表、平台摘要、选装工具、发布程序与 tag 参数。模板支持的两个固定上游版本为 host-bootstrap v0.1.0-alpha.15 的 `ci-install-table-v1 manager` 和 host-release v0.1.0-alpha.21 的 `check-pushed-tag`。

选装严格检查且生成 mise 清单时，同一验证根读取宿主真实 TOML。请将该清单登记为 program，指向该根。setup 验收检查本仓工具选择、安装与刷新指令的顺序。工具发行标签与摘要由宿主安装流程验证。
