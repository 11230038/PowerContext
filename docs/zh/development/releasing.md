---
title: 准备发布版本
description: 通过 Make 更新发布版本，检查独立版本组件，并验证发布产物。
---

# 准备发布版本

使用仓库的 Makefile 更新待发布的 PowerContext 版本及安装说明。Python 发行包的实际版本仍由 Hatch VCS 从
Git 派生。更新待发布版本不会创建 tag、发布软件包或创建 GitHub Release。

下文命令以 `1.2.0` 为操作示例。这些示例不表示当前发布版本，后续发布无需修改本文中的示例数字。

## 更新并检查待发布版本

在发布准备分支的仓库根目录运行：

```bash
make version-bump VERSION=1.2.0
make version-check
git diff --stat
git diff
```

`version-bump` 更新纳入管理的文件，并从 OpenAPI 契约重新生成 Python API 元数据。
它也接受 `1.3.0a1`、`1.3.0b1` 和 `1.3.0rc1` 等预发布版本。纳入管理的安装说明只指明所选版本，
不将其统一称为正式版本。
`version-check` 以 `openapi/powercontext.yaml` 中的 `info.version` 为准检查一致性，不修改文件。
也可以传入包版本或 tag 写法，核对明确的发布目标：

```bash
make version-check VERSION=1.2.0
make version-check VERSION=powercontext-v1.2.0
```

tag 写法用于指定预期版本，不证明该 tag 已存在，也不证明当前检出构建出的包已经是该版本。
提交前检查差异；生成的 Python 文件必须通过生成命令更新，不能手工修改。

正式发布时，在 `website/src/lib/releases.ts` 顶部新增双语条目，填写实际变化、发布日期、安装命令及 GitHub
Release 链接。保留所有已有条目，然后运行：

```bash
make release-check VERSION=1.2.0
```

`release-check` 先运行 `version-check`，安装网站依赖，再检查网站首条记录是否匹配目标版本、是否包含中英文说明，
以及安装命令和发布链接是否使用同一版本。此命令需要仓库指定的 Node/pnpm 环境。网站只列正式版本，因此 alpha、
beta 和 RC 跳过网站条目检查。`make docs-test` 也会通过网站测试运行此项检查。

## 版本位置清单

### 自动同步的版本

| 来源 | 自动管理的内容 |
| --- | --- |
| `openapi/powercontext.yaml` | `info.version`，作为待发布版本。 |
| `release/upgrade-support.json` | 目标发布版本；来源版本和支持策略需要单独进行兼容性审查。 |
| `src/powercontext/http/_generated/` | `operations.py` 的 `API_VERSION` 和 `schema.py` 的 `info.version`，通过 `make api-generate` 重新生成。 |
| `README.md`、`README_CN.md`、`README_JP.md` | 当前版本介绍、固定包版本的安装命令及配套 Agent 集成 tag。 |
| `docs/en/docs/get-started/quickstart.md`、`docs/zh/docs/get-started/quickstart.md` | 当前版本介绍及匹配的安装命令、tag。 |
| `docs/en/docs/get-started/manual-start.md`、`docs/zh/docs/get-started/manual-start.md` | CLI/Server 和 Python Client 安装版本及配套 Agent 集成 tag。 |
| `docs/en/docs/get-started/install-and-run.md`、`docs/zh/docs/get-started/install-and-run.md` | 页面描述、当前版本介绍、包版本和 tag、升级目标及 Python Client 安装命令。 |
| `integrations/dsh/plugins/powercontext/README.md` | Server 安装版本及对应的 `setup dsh --ref` tag。 |

安装指南也包含历史迁移版本，这些引用会保留。新增表示当前发布版本的安装示例时，应同时将其纳入版本工具的
管理路径及匹配规则，使下次发布可以自动更新和检查。

### 从其他来源派生的版本

| 内容 | 来源及处理方式 |
| --- | --- |
| Python wheel/sdist 版本及安装后的 `powercontext --version` | `pyproject.toml` 声明 `dynamic = ["version"]`，Hatch VCS 读取 Git 元数据。最终产物应从目标发布 tag 构建。 |
| Runtime 包元数据 | 读取已安装 Python 发行包的版本，没有另一份需要手工更新的 Runtime 静态版本。 |
| Desktop API 绑定 | 运行 `pnpm --dir desktop generate` 重新生成 OpenAPI 类型和契约摘要，再用 `pnpm --dir desktop generate:check` 检查。Desktop 应用本身使用独立包版本。 |
| Dify 工具契约 | 运行 `uv run python integrations/dify/generate_contract.py` 重新生成，再为同一命令添加 `--check`，检查 API 版本及 Schema。 |
| Docker 和 Bub harness 的构建版本 | 构建输入通过 `POWERCONTEXT_VERSION` 传递选定的包或 Git 版本，不应在 Dockerfile 中加入固定发布版本。 |
| 网站文档与 API 参考 | 从文档和 API 源文件生成，不编辑 `website/content/docs/`、`website/.generated/` 或 `website/out/`。 |
| 依赖锁文件 | 依赖或独立包元数据变化时，由对应包管理器重新生成。仅修改主发布版本，不需要替换锁文件中的版本。 |

OpenAPI 版本描述待发布的 API 契约，不覆盖 Hatch VCS。打 tag 前，开发检出的 Python 包版本可以仍是开发版本，
同时 API 契约已经更新为下一次发布的版本。

### 独立版本的组件

这些组件的行为或发行物发生变化时，应按自身发布要求检查。`make version-bump` 不会将它们统一为 PowerContext
主版本。

| 组件 | 版本位置及检查范围 |
| --- | --- |
| Claude Code 插件 | 发布插件更新时，`integrations/claude-code/plugins/powercontext/.claude-plugin/plugin.json` 与 `.claude-plugin/marketplace.json` 的版本必须一致；同时检查断言 manifest 版本的契约测试。 |
| Codex 插件 | `integrations/codex/plugins/powercontext/.codex-plugin/plugin.json` 与同级 `pyproject.toml` 分别描述插件及其 Runtime 包，插件发布时一起检查，并刷新插件的 `uv.lock`。`plugin_version.py` 从 manifest 派生 Hook 和 Scope 绑定请求的 User-Agent 版本。 |
| 通用 Agent Plugin | `integrations/agent-plugin/powercontext/plugin.json`；其包版本与 Agent Plugins schema 版本相互独立。 |
| Hermes 插件 | `integrations/hermes/plugins/{powercontext,powercontext-command}/plugin.yaml`。 |
| MiniMax 和 ZCode 插件 | `integrations/minimax/plugins/powercontext/.minimax-plugin/plugin.json` 与 `integrations/zcode/plugins/powercontext/.zcode-plugin/plugin.json`。 |
| JavaScript 插件 | `integrations/{dsh,opencode,pi}/plugins/powercontext/package.json` 与 `integrations/openclaw/plugins/memory-powercontext/package.json`；OpenClaw 的发现 manifest 没有独立版本字段。 |
| WorkBuddy 集成 | Hook 和传输脚本包含 User-Agent 字符串，没有需要与 Server 对齐的插件 manifest 版本。 |
| Skill Receiver | `src/powercontext/client/skill_receiver.py` 中的 `RECEIVER_VERSION` 提供注册、协调及回执上报时默认使用的 Receiver 身份版本，独立于 Server 版本。 |
| Python 集成包 | `integrations/{bub,langchain,langgraph,opendal,pydantic-ai}/pyproject.toml` 有各自的发行版本；依赖范围表示兼容性，不是当前主发布版本。 |
| 评测及 harness 包 | `evaluation/pyproject.toml`、`evaluation/coding/swebench_pro/web/package.json`、`e2e/bub/pyproject.toml` 有各自的包版本。 |
| 协议及依赖 | Agent Plugins schema 版本、持久化格式版本、OpenAPI 规范版本、API 路径、宿主最低版本及第三方依赖仅随自身契约更新。 |

通过匹配的 `powercontext-v…` 仓库 tag 安装 Agent 集成，可以选中配套的源码修订，不要求每个插件 manifest 的
数字版本都与 Server 相同。

独立发布插件时，还应审计 Python Hook、脚本及 JavaScript `src/errors.ts` 中含版本的 User-Agent 字符串、
对应契约测试、生成的 bundle 和相关锁文件。这些值可能与 manifest 不一致，主发布版本检查不会验证它们。
DSH 的 `pack:release` 先构建再给包 manifest 写入版本，而写版本脚本只修改 manifest；给打包命令传入新版本，
不会更新已经编译进 bundle 的传输版本。

### 历史记录及测试示例

保留 `website/src/lib/releases.ts` 的已有条目，包括日期、安装命令和 GitHub 链接。正式发布时，为新版本单独
增加条目，写明实际的用户可见变化和升级说明。网站只列正式版本；alpha、beta 和 RC 说明放在 GitHub Releases。
版本工具不会自动编写发布说明。

同样保留迁移引入版本、旧版兼容说明、RFC 基线、历史发布素材及用于验证旧版本或任意版本的测试数据。例如，
`1.1.0` 引入标签表迁移、`1.0.0` 之前数据库需要处理迁移，都是历史事实。测试数据中出现 `1.0.0` 并不意味着
它是遗漏更新的当前版本声明。

DSH README 中说明某项能力已包含在 `1.1.0` 的文字同样属于历史说明，仅其当前安装命令中的版本参与同步。

## 发布前验证

### 数据库升级支持范围

`release/upgrade-support.json` 声明目标版本、来源版本选择策略、后端和配置。`automatic_sources` 从 PyPI 自动选择
大于等于 `minimum_version`、小于实际目标 wheel 的全部稳定版本，再与每个后端配置展开组合。新稳定版发布后，
后续运行会自动将其加入来源，不必逐版本新增测试。证据会记录具体来源 wheel 的 SHA-256。
当前策略为 `fresh-install-only`，不支持已有 Server 数据库升级；配置中的空套件路径只生成候选组合，不算验收通过。
启用支持升级模式时，每个后端配置都必须有真实套件。只有实现并通过已安装发行包的完整升级验收，才能声明支持
对应组合。验收契约和证据要求见仓库中的 `tests/release_upgrades/README.md`。

`make check` 和 `make release-check` 会核对策略及双语安装说明。受管持久化文件变化时，必须审查兼容性影响，
更新摘要和理由。摘要用于触发审查，本身不证明迁移正确。`make version-bump` 同时更新策略中的目标版本；
支持矩阵变化后，运行 `uv run python scripts/upgrade_release_gate.py --write-docs` 更新安装说明中的支持范围。

将唯一的目标 wheel 构建到 `dist/` 后，执行声明的升级组合验收：

```bash
make upgrade-release-test
uv run python scripts/run_upgrade_release_gate.py --release --release-notes /path/to/release-notes.md
```

发布检查要求实际 wheel 版本与策略一致，发布说明包含安装指南中的完整英文支持声明。每个组合分别安装准确的
旧版发行包和目标 wheel。测试缺失、后端跳过、执行失败或证据缺失都会阻断检查。`fresh-install-only` 策略检查
通过不表示存在升级路径。普通 PR 构建允许使用开发版本；`--release` 必须验证最终 tag 构建的 wheel，不能覆盖版本号。

CI 中的 **Upgrade release gate** 还会使用真实 1.3.0 SQLite 和嵌入式 seekDB Server 数据库复现已知的升级拒绝行为。
seekDB 直接在 runner 的临时目录中启动，不需要外部服务。启用支持升级模式后，固定的拒绝断言退出，自动展开的
全部成功升级组合必须通过验收。仓库管理员需要在分支保护中将该检查设为必需。
发布工作流只有验收通过才会上传发行包、发布 PyPI 和上传 Release 附件，并归档验收证据。工作流在
`release.published` 后运行，无法阻止之前手动发布 GitHub Release 页面，因此必须先运行上述命令再发布页面。
`make publish` 要求提供 `UPGRADE_RELEASE_NOTES=/path/to/release-notes.md`，并在上传软件包之前执行相同门禁。

针对本次发布的完整变化运行检查，包括生成的契约和文档：

```bash
make release-check VERSION=1.2.0
make contract-test
make check
make test
make docs-test
make build
uvx --from twine twine check dist/*
```

网站检查应使用受支持的 Node/pnpm 环境。独立更新插件或适配器时，还需运行对应集成检查。根据实际变化验证
兼容性和数据迁移；版本一致性检查本身不证明向后兼容。

在目标发布 tag 的干净检出中，构建最终产物前检查实际包版本：

```bash
uvx --from hatchling --with hatch-vcs hatchling version
```

输出必须与 tag 表示的包版本一致。不能用 pretend-version 覆盖值来证明该 tag 能生成正确版本。
在独立环境中安装构建产物，并运行 `scripts/ci_release_smoke.py --version <package-version>`，验证 CLI、
Server、MCP 和 SQLite 行为。

仓库的 `.github/workflows/release.yml` 在 GitHub Release **发布**时触发，在构建和发布 PyPI 包前运行
`release-check`，并检查 tag 与 Hatch VCS 版本一致性。随后构建和检查发行包、发布到 PyPI、上传附件并执行发布验证。
仅推送 tag 不会触发该工作流。
创建 tag、发布 GitHub Release 是准备与审阅完成之后的独立发布操作。

发布 tag 存在后，检查 `integrations/capabilities.toml` 中的可用性声明。`released` 条目必须指定已存在的
`release_tag`，且该 tag 应包含声明的实现及证据；这与插件自身版本是不同的概念。支持契约未改变时，试验性集成
继续保持试验性。在本地和 CI 检出中获取所引用的 tag 后再运行集成 manifest 检查，使用
`make integration-manifest-docs` 重新生成双语能力矩阵，并同步相关集成概览和评测说明。不要仅为通过可用性检查
而创建或移动发布 tag。
