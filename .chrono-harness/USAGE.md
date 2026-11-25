# chrono-harness-copier 使用说明

组件的用途、开发仓库和示例见 [Chrono Harness 用户与开发者入口](https://github.com/chrono-harness/chrono-harness-main)。

本仓维护供独立仓库选装工具的 Copier 模板。

开发分支为 `dev`，正式分支为 `main`。已选组件见 [Copier 答案](template-answers.yml)。

[组织协作规范](https://github.com/chrono-harness/chrono-harness-instructions/blob/dev/docs/contributing.md)

首次检出运行 `mise trust` 和 `mise run harness-setup`。工具版本见 [.config/mise/conf.d/chrono-harness.toml](../.config/mise/conf.d/chrono-harness.toml)。

刷新根指南使用 `mise run harness-setup`。本仓选择在 `.chrono-harness/rules.json`。

用 `mise exec -- chrono-pr pr-reminders` 查看本地提醒，再运行 `mise exec -- chrono-pr pr-status --pr NUMBER --head-sha SHA` 查询 GitHub。

## 本仓验证

模板选项在 `copier.yml`，生成宿主的文件在 `scaffold/`，模板自身的检查在 `tests/`。从仓库根目录运行 `./tests/check.sh` 验证生成结果、路线图和发布流程。
