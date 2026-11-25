# chrono-harness-copier 使用说明

组件的用途、开发仓库和示例见 [Chrono Harness 用户与开发者入口](https://github.com/chrono-harness/chrono-harness-main)。

本仓维护供独立仓库选装工具的 Copier 模板。

开发分支为 `dev`，正式分支为 `main`。已选组件见 [Copier 答案](template-answers.yml)。

[组织协作规范](https://github.com/chrono-harness/chrono-harness-instructions/blob/dev/docs/contributing.md)

首次检出运行 `mise trust` 和 `mise run harness-setup`。本仓默认安装策略为 `pinned`。固定配方读取 [.config/mise/conf.d/chrono-harness.toml](../.config/mise/conf.d/chrono-harness.toml)。模板答案 `tool_versions` 可以为每个工具选择 stable、preview 或精确标签。临时运行 `CHRONO_TOOL_CHANNEL=preview mise run harness-setup` 会为已选组织工具安装各自最新测试版，也可以把 `preview` 换成 `stable` 或精确的 `v` 标签。再次运行普通安装即可恢复本仓选择。本仓的模板测试工作流使用 uv 和 Node 运行测试。各分支、标签和 detached HEAD 使用相同规则。

刷新根指南使用 `mise run harness-setup`。本仓选择在 `.chrono-harness/rules.json`。

用 `mise exec -- chrono-pr pr-reminders` 查看本地提醒，再运行 `mise exec -- chrono-pr pr-status --pr NUMBER --head-sha SHA` 查询 GitHub。

## 本仓验证

模板选项在 `copier.yml`，生成宿主的文件在 `scaffold/`，模板自身的检查在 `tests/`。从仓库根目录运行 `./tests/check.sh` 验证生成结果、路线图和发布流程。
