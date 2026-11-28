# 模板渲染、安装器选择与目标路径

| 文件 | 负责方及输入 | 当前使用方与操作 | 成本 |
| --- | --- | --- | --- |
| `verification/install_target.rs` | Copier。`program`，证明根为该文件。输入是访问顺序及 Shell 的路径观察 | `tests/check.sh` 编译整 crate，执行边界证明，再运行同一编译结果生成模板片段 | 未知 |
| `verification/install_selection.rs` | Copier。由 `verification/install_target.rs` 整根编译。输入为禁用工具、覆盖存在性、平台、解析器页终态和成功校验后是否含动态选项 | 两个安装器使用同一编译程序生成的 Shell 函数，独立边界预期同时运行 | 每次检查生成一次 |
| `.chrono-harness/install-policy.sh` | 同一证明编译程序以 `--selection` 生成 | 自装脚本直接读取，宿主模板直接嵌入。`tests/check.sh` 逐字比较 | 首装无需额外可执行文件 |
| `.chrono-harness/install-tools.sh` | 本仓安装入口。读取共享判据、mise 固定配方及外部程序的原始结果 | `mise run harness-setup` 和两平台 Install base tools 工作流。动态选择在成功后发布为完整 mise 覆盖 | 未知 |
| `install-target.jinja` | 上述整 crate 编译结果生成的数据。输入是全部角色与布尔观察组合 | `tests/check.sh` 比对字节。Copier 渲染时直接嵌入选装组织工具的安装器 | 每次验证生成一次，首次安装无额外可执行文件 |
| `scaffold/.chrono-harness/…install-tools.sh…jinja` | Copier。只在目标路径准入范围使用上述证明根，读取选装配置、固定片段与实际路径 | 实际宿主通过 `mise run harness-setup` 调用渲染安装器 | 文件观察成本未知 |
| `verification/render_selection.rs` | Copier。 `program`，证明根 `verification/install_target.rs`。输入是工具在显式组件依赖中的成员关系、保留开关、检查入口选择、仓库名及版本观察 | 同次 `tests/check.sh` 验证整根、独立边界预期并编译生成 `render-selection.jinja` | 每次检查生成一次 |
| `render-selection.jinja` | 同一证明编译程序以 `--render-selection` 枚举布尔输入，按原结果生成数据 | `copier.yml`、`render-tools.jinja` 实际读取。检查逐字对照，源码发行包含该文件 | 渲染无需额外可执行文件 |
| `render-tools.jinja` | Copier 渲染适配器。读取 `copier.yml` 的组件依赖、宿主回答及生成数据 | `tool-catalog.jinja` 读取工具并集。生成路径、mise 任务、安装脚本、版本 validator 读取同一决定 | 未知 |
| `copier.yml` | Copier 选项、依赖和问题次序。仓库名、仓默认通道与逐工具覆盖校验读取已证明结果 | Copier 9.19.1 的 `copy`、`update`，example 的 `Template adoption / copier` 验收实际采用 | 未知 |
| `tool-catalog.jinja` | Copier。读选中工具与各工具固定配方 | 实际渲染的 mise 配方、安装器和严格宿主适配器 | 未知 |
| `tests/check.sh` 的渲染检查 | Copier。以固定候选运行原正常入口，核对编译生成字节、选择、首错、更新与宿主指令 | 本地、Copier CI、发行来源检查 | 未知 |
| `tests/test_install.py` | Copier。输入为实际渲染的固定选版和动态选版安装器，以及命令替身 | `tests/check.sh` 执行，断言错误文本、首错、原件、安装选择和恢复边界 | 未知 |

本地与 Copier CI 使用 `./tests/check.sh`。证明在该入口运行
`mise exec -- verus --no-cheating --no-external-by-default --compile --edition=2021`，
输出写入该次检查的临时目录。mise 配方固定 Rust 1.95.0 及 Verus、随附 vstd 和宏
`0.2026.04.24.f8e1704`。此仓检查入口直接执行证明、对照生成物并验证渲染行为，失败即退出。

外部接口是 POSIX Shell 的 `test -L/-e/-d/-f`、路径字符串相等、原有的三组 glob
及其展开顺序，以及 `fail` 的 stderr 和退出 1。生成器只序列化 Verus 给出的检查顺序、
表项和拒绝类别。空 glob 的未匹配文字仍以路径观察处理，悬空符号链接由 `-L` 提供。
证明范围是这些观察到准入和拒绝类别的映射以及固定访问顺序。实际渲染测试检查
Shell 的路径观察、调用结果、首错和错误后恢复。


渲染判据的外部输入来自 Copier 的答案类型与提问顺序、Jinja 的列表拼接、成员观察、去重及 Python 正则匹配。组件依赖由 `copier.yml` 声明。模板把已有依赖中的成员关系、两个保留请求和覆盖键是否存在交给生成的布尔表。该表给出工具成员、安装入口、两类保留组合、仓库名准入和覆盖准入。逐工具覆盖先经准入，再选择覆盖或仓默认通道。模板按这个结果生成实际路径和安装记录。Copier 的 Git 三方更新及冲突提示由现行 `update` 实测，属于外部接口。
