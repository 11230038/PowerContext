# Desktop validation

Desktop is an unsigned internal Windows preview. Passing CI does not establish release qualification.

## Reproducible checks

Run from the repository root:

```sh
pnpm --dir desktop install --frozen-lockfile
pnpm --dir desktop lint
pnpm --dir desktop typecheck
pnpm --dir desktop test
pnpm --dir desktop build
pnpm --dir desktop ipc:check
cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --check
cargo clippy --locked --manifest-path desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml
```

[Desktop CI](../.github/workflows/desktop.yml) also builds a Server wheel, runs real Server and CLI tests, checks Windows credentials and process containment, builds the installer, and exercises installation, the installed UI and uninstallation. Consult the PR checks for the exact commit being reviewed. Reports, logs and screenshots are generated under ignored `.artifacts/` and uploaded as Actions artifacts; do not copy them into the repository.

## Compatibility scope

[compatibility.json](src-tauri/src/connections/compatibility.json) preserves the recorded Server sources, normalized OpenAPI contract digests and qualification-wheel digests for the historical profiles below. No product record currently matches this build’s bundled contract; ordinary builds keep business operations unavailable until an independently verified matching profile is added. Historical records are disabled in the selector, and saved unavailable selections remain visible until explicitly replaced. CI builds have their own artifact identities and do not change product qualification.

The real Server harness covers SQLite with anonymous loopback, static Bearer, HTTPS with explicit CA/base path, and injected-provider/enforced access. It exercises save/search/exact reads, identity changes, binding revocation, ambiguous writes without replay and Scope pagination. Installed UI checks cover repeated launches preserving the existing editor, late committed-save responses preserving a new Scope draft, explicit connection/Scope selection, clipboard copies, connection isolation, draft cancellation, byte limits and independent Server survival after Desktop exit.

Selecting a compatibility profile does not attest the remote binary identity. Existing `sqlite-1.1.1-v1` / `sqlite-63f918b7-v1` / `sqlite-ab43e3a7-v1` / `sqlite-f1089f4e-v1` / `sqlite-6e237568-v1` / `sqlite-legacy-58f7f4f6-v1` selections require explicitly choosing an available matching profile and rechecking the connection. Desktop reads memories only through Atomic Memory references, so Servers that answer only with Memory entry citations are not qualified. CLI diagnostics separately verify the registered executable path and digest, then validate the diagnostic response schema. The observed version is optional report information; a registration does not require a version.

### Atomic Memory protocol qualification

`sqlite-atomic-f702c041-v1` identifies Server sources at `f702c0418d69e3072e1ec2fa657e0df81e8e51b4`, contract digest `5d8bbad951234b05e3174f1b9113e0ffe066ac968abbe53ac2456b2375e406d3`, and qualification-wheel digest `4fe64b868a2e214316a088574d8d4023d9b9679ec42029e2d13502121e6aade9`. The wheel version is `1.2.1.dev78+g77dc6f73b.d20261009`. It was captured at HEAD `77dc6f73b86678221d34a14e2de61dade0ff9db3` with staged tree `d2e9d703877ea707d78191ce0c358112fd69f65f` and a dirty working tree. That tree became the recorded Server commit; all 460 runtime files in the wheel match its sources byte for byte. The runtime source-manifest digest is `e26a4c4581f32b855689e3e0db26b48239f2f6758ab594addc9efc047978390d` (sorted wheel runtime paths and content digests). The OpenAPI contract, project configuration and lock remained unchanged between capture and commit. CI builds have their own wheel identities.

The native `ConnectionManager` exercised the actual isolated built-wheel SQLite Server in four modes: anonymous loopback, static Bearer, HTTPS with explicit CA/base path, and injected-provider/enforced access. All four passed on macOS 26.2 ARM64 with Rust 1.95.0 and Python 3.12.7. Checks covered Atomic Memory save/search/exact Artifact revision reads, identity changes, binding revocation, ambiguous writes without replay, Scope pagination and independent Server survival after client exit. The catalog records the ten operations exercised, including `get_artifact_revision`. The native harness candidate remains separate from the product catalog.

These results establish the stated Server protocol compatibility. Windows credentials, process containment, registered-executable checks and installed-package acceptance for this Atomic profile require their actual Windows CI checks. This protocol record does not establish platform or release acceptance.

### Historical protocol qualifications

`sqlite-6e237568-v1` records the original Server source, contract digest and qualification-wheel digest. Its qualification wheel was built from checkout `ea30fd5c`; its backend sources, OpenAPI contract, project configuration and lock matched the recorded Server commit. The immutable catalog preserves its identities and original ten operations.

`sqlite-legacy-58f7f4f6-v1` identifies Server sources at `58f7f4f6cbadd698bac35b3fca019d9f48f55b81`, contract digest `9f4ba7b35ecd3b3639af4e648aff84b713a7f30b51d5a4c30c8809aeb8dc8024`, and qualification-wheel digest `7203cf1a98cb9dfd8631e142f7a0f5e74c39845da4fb7d862117a49fa1ef38af`. Its original ten Desktop operations and Legacy Memory protocol were exercised by the native `ConnectionManager` against the isolated built-wheel SQLite Server in all four harness modes: anonymous loopback, Bearer, HTTPS with explicit CA/base path, and injected-provider/enforced access. These checks cover save/search/exact historical citation reads, identity changes, revocation, ambiguous writes without replay, and Scope pagination. The original `sqlite-6e237568-v1` record retains its identities and operations. The Base Legacy qualification requires explicitly selecting a profile whose recorded contract matches the bundled Desktop contract and rechecking the connection.

This qualification used macOS 26.2 ARM64, Rust 1.95.0 and Python 3.12.7. An external system Python launcher was used for native process creation because this environment can terminate native subprocesses before their first request. The wheel, native client, fixtures and business assertions were preserved. The real CLI's fixed version, service-status and integration commands were also exercised with an isolated home and PATH; their actual outputs passed the native projections. These checks establish the stated SQLite compatibility and CLI response handling. Windows registered-executable checks, credentials, process containment and installed-package acceptance require their actual Windows CI checks. No remote legacy deployment was tested in this qualification.

`sqlite-atomic-7bd5b85c-v1` identifies Server sources at `7bd5b85c154c284d0ad550de31ecf8aa629d8ccf`, contract digest `0807df984ba706b505d4fff0cb849d4566222f10572d91a5e03399b833d1fe4f`, and qualification-wheel digest `057eca5de29961684bfea8ea8aece7c133b3d8b46a024db69a944519bc5b2746`. Its native `ConnectionManager` was exercised against the isolated built-wheel SQLite Server in all four harness modes: anonymous loopback, Bearer, HTTPS with explicit CA/base path, and injected-provider/enforced access. These checks cover Atomic writes, all returned references, search, immutable revision reads, identity changes, revocation, ambiguous writes without replay, and Scope pagination. These are historical results for that qualified build; this Desktop build reads only Atomic Memory references and does not retain the Legacy citation protocol.

The Atomic qualification run used macOS 26.2 ARM64, Rust 1.95.0 and Python 3.12.7. An external launcher routed native process creation through system Python 3.9.6 because the same signed native executable exited with SIGKILL when launched by the Conda Python parent before its first request. The wheel, native client, harness fixtures and business assertions were unchanged by that launcher. This establishes the stated SQLite compatibility; Windows IPC, vault, process containment and installed-package acceptance require their actual Windows CI checks. No legacy remote deployment was tested in the Atomic qualification run.

## CI fixture 的独立资格

CI fixture 使用独立资格记录，不会修改历史生产资格。原生 HTTP 测试显式注入 synthetic profile；真实 Server 和安装验收使用 `fixture_qualification.py` 从当前合同、Server 提交和构建 wheel 生成的 `.artifacts/ci-compatibility.json`，读取时重新核对合同、操作集合和 wheel 哈希。

只有显式启用 `ci-fixtures` 的测试安装包会包含这个 profile。普通构建仍只使用历史资格记录，并保留合同不匹配时的 fail-closed 行为。CI fixture 和其安装包不能作为生产发布资格证据。

```sh
uv build --wheel --out-dir desktop/.artifacts/server-wheel
DESKTOP_FIXTURE_COMMIT=$(git rev-parse HEAD)
uv run python desktop/tests/fixture_qualification.py --server-commit "$DESKTOP_FIXTURE_COMMIT"
pnpm --dir desktop tauri build --bundles nsis --ci --features ci-fixtures -- --locked
```

## Observation navigation (#2102)

The application opens Overview and provides Overview, Connections, Memories, and Observation in the main navigation. Settings & diagnostics remains at the bottom. Observation provides Runtime state, Current-Scope inventory & usage, and This session tabs with unavailable data views; navigation does not initiate connection checks or local diagnostics.

Local verification on Windows x64 on 2026-10-21 used Node 24.14.1, pnpm 11.13.1, and Rust 1.95.0 for generated-contract checking. All 37 UI tests, type checking, lint, and the frontend production build passed. Existing Overview, connection, Memory, Scope and diagnostic behavior tests remain in place; Observation tests cover navigation, English/Chinese, keyboard tabs, unavailable states and the existing draft confirmation.

Headless Edge 155.0.4283.62 with synthetic IPC checked all five pages in 24 combinations of English/Chinese, light/dark/system, and CSS viewports 1180×800, 800×600, 400×400 and 400×300. The pages had no horizontal overflow. At desktop widths, Settings & diagnostics had the same coordinates with and without the Observation entry; at small widths it remained below the main navigation. The 400×300 viewport at device scale factor 2 checks layout equivalent to 800×600 at 200%, not installed WebView zoom. Browser fixtures and mocked IPC do not establish real Server, installed-package, native IME, screen-reader or macOS qualification.

应用默认进入总览，主导航包含总览、连接、记忆、观察，“设置与诊断”位于底部。观察包含运行状态、当前 Scope 库存与用量、本次会话三个标签页，数据视图尚未可用；页面及标签切换不会执行连接检查或本机诊断。

2026-10-21 在 Windows x64 上使用 Node 24.14.1、pnpm 11.13.1 验证，生成合同检查使用 Rust 1.95.0。37 项 UI 测试、类型检查、lint 和前端生产构建通过。原有业务行为测试保留，观察测试覆盖导航、双语、键盘标签切换、不可用状态和现有草稿确认。

无头 Edge 155.0.4283.62 使用合成 IPC 检查中英文、三种主题及上述四组 CSS 视口，共 24 种组合，五个页面没有横向溢出。在桌面宽度下，有无观察入口时“设置与诊断”的坐标一致；小窗口中它仍位于主导航下方。400×300 配合设备缩放因子 2 仅检查 800×600 在 200% 下的等效布局，不代表安装版 WebView 缩放。真实 Server、安装包、原生 IME、屏幕阅读器和 macOS 仍需实际验收。


## Shared feedback and global context (#2102)

On 2026-10-22, Windows x64 local checks used Node 24.14.1, pnpm 11.13.1 and Rust 1.95.0. Focused feedback/context tests and all 50 frontend tests passed, together with typecheck, lint (including generated contracts and icons in check mode) and production build. Coverage includes pending/failed/disconnected initialization, local-state recovery without readiness probes, same-name Scope IDs, latest matching connection facts, identity/health/compatibility separation, prerequisite recovery, Scope pagination recovery, failed exact-read retries retaining the original revision, preserved drafts, local diagnostics, keyboard menus and modal focus. Existing save, unknown-write and late-response protections remain covered.

Headless Edge 155.0.4283.62 with synthetic IPC exercised all five pages in 48 combinations: connected/disconnected, English/Chinese, light/dark/system, and CSS viewports 1180×800, 800×600, 400×400 and 400×300. Long addresses and Scope IDs, permission errors, Scope selection and missing-local-CLI errors had no horizontal overflow. A forced-colors run checked pending-search feedback. Screenshots were inspected for the 800×600 Scope dialog and forced-colors loading view. The 400×300 viewport with device scale factor 2 is a layout equivalent of 800×600 at 200%, not actual installed WebView zoom.

These checks use browser fixtures and mock IPC. No real native/backend, installer, platform IME or screen-reader acceptance was executed for this change. Repository-wide `uv run --locked prek run -a` retains the existing Windows `ty check` failures involving `os.O_NOFOLLOW`, `fcntl` and `resource` in unchanged Python code; other hooks passed. Logs and browser evidence are under ignored `.artifacts/desktop-shell/`.

2026-10-22 在 Windows x64 上使用上述固定工具版本，专项测试及全部 50 项前端测试、typecheck、lint 和生产构建通过。测试覆盖加载／失败／未连接区分、恢复入口、同名 Scope 的完整 ID、最新匹配连接事实、身份／健康／兼容性分别表达、原版本精确读取重试、草稿保护及键盘焦点。

Edge 合成 IPC 检查覆盖上述 48 组配置和五个页面，包含权限及本机诊断错误、长地址和 Scope ID、Scope 弹窗，无横向溢出；另检查强制高对比度的加载反馈并查看截图。200% 为等效布局检查。本次没有执行真实原生／后端、安装包、平台 IME 或屏幕阅读器验收。仓库检查中，未修改 Python 代码的 Windows 类型检查存在上述既有错误，其余钩子通过。

## Save outcome recovery (#2102)

On 2026-10-22, mocked-IPC UI tests verified that a resolved `WriteOutcome` with `record.status: "failed"` and `forbidden` displays the same permission recovery guidance as the exception path in English and Chinese, preserves the draft and dirty state, and does not replay the write. Unknown-write coverage verifies that cancelling resubmission sends no request and explicit confirmation permits a new submission. All 16 Memory tests and all 52 frontend tests passed, along with typecheck, lint and production build using the pinned tools above. No real native/backend or installed-package acceptance was executed for this fix. Repository hooks retain the existing Windows Python `ty check` failures described above.

2026-10-22 的模拟 IPC 测试验证：确定失败的保存结果显示与异常分支一致的中英文权限恢复说明，保留草稿及未保存状态，不自动重放写入；未知写入取消再次提交时不发请求，确认后才提交。16 项 Memory 测试、全部 52 项前端测试、typecheck、lint 和生产构建通过。本次未执行真实原生／后端或安装包验收；仓库钩子仍有上述既有 Windows Python 类型检查错误。

## Remaining release qualification

- Clean standard-user Windows 11, including absent/present WebView2 and bootstrap recovery.
- Publisher signing and release ownership.
- Actual IME, screen reader, high contrast and complete keyboard accessibility.
- Notification cold activation, independent service login/reboot behavior and a named Agent host's capture/recall workflow.
- Maintainer ownership and approved performance budgets.

Hosted Windows CI and developer-machine checks do not replace these platform and product gates. This preview does not close #1654 or #1428.
