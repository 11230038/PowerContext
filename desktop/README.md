# PowerContext Desktop preview

Internal Windows preview for [#1654](https://github.com/oceanbase/powercontext/issues/1654), following RFC #1455. Its shared application layout provides Memory, Connections, Observation, and Settings & help, Chinese/English interfaces, and light/dark/system themes. Connection profiles, explicit activation, identity/readiness checks, exact Scope selection, local diagnostics, note saving, bounded FTS search and exact-version reading are implemented; native workflow qualification remains open.

See [中文说明](README.zh.md), [security boundary](SECURITY.md), and [validation guide](VALIDATION.md). This is not a supported or signed release, and does not close #1654 or #1428.

## Navigation and first use

Memory is the initial page. After Desktop state loads, an inactive connection offers **Set up locally** and **Connect an existing server**. Local setup opens **Settings & help → Local Server**, which explains that installation and service management are not available yet. Prepare a Server independently using the instructions below, or obtain its address and applicable credentials from an administrator. The global connection menu opens the selected configuration without activating it. Explicitly activate a connection, select an exact Scope, and use the existing Memory workspace.

The global context displays the connection, endpoint, exact Scope title and ID, identity, compatibility and last observed health facts on every page. Health does not grant operation permissions. Changing pages or connection targets requires confirmation when input is unsaved. Closing Scope selection leaves the current draft intact. Submitted writes retain their original target and are not automatically replayed.

Observation contains **Runtime state**, **Current-Scope inventory & usage**, and **This session**. These are unavailable placeholders until their owning features are integrated; no sample data, invented zero-valued statistics or automatic readiness probes are shown. Connections retains its explicit connection checks, whose native readiness behavior is tracked separately by #2101.

Settings & help remains available without HTTP and provides language, theme, Local Server guidance, explicit local CLI diagnostics, the observed Desktop version, and copyable usage/support links. An unavailable native version is shown as unknown. Local diagnostic failure does not disable independently available remote operations.

Use Tab to reach navigation and controls. The connection menu supports arrow keys, Home/End and Escape; Observation tabs support Left/Right and Home/End. Scope selection contains keyboard focus and restores it to the opening control when closed. Small windows use collapsible navigation; context and dialog contents can scroll without hiding recovery controls.

### UI integration interfaces

`ui/src/app/navigation.ts` defines `Page`, `ObservationTab`, `Theme`, and `NavigationTarget`. Application navigation accepts an optional connection ID, Observation tab, or `local-server` settings section. External connection selections pass the application's draft guard before reaching the editor. The editor's `selection` request invalidates pending editor completions, so a late save cannot replace a different selected configuration.

`Observation` accepts independent `panels` keyed by `runtime`, `inventory`, and `session`, with unavailable defaults. Each owning page provides data, authorization, refresh and cancellation behavior. `PageFeedback` presents loading/error/empty/unavailable states with caller-owned explanations and actions. Local setup and management belong to #2117; observation content belongs to #2105, #2106 and #2107. These interfaces do not extend native IPC or the public HTTP contract.

## Run the installed preview

Download and extract `desktop-windows-internal-unsigned` from a successful **Desktop validation** Actions run on this branch. The installer is under `src-tauri/target/release/bundle/nsis/`. Its accompanying `.artifacts/windows-smoke.json` records the commit, SHA-256 and signature status; compare the downloaded installer with `Get-FileHash -Algorithm SHA256 <installer-path>`. The current package is unsigned and intended for internal validation.

Install it, then open **PowerContext Desktop Preview** from the Windows Start menu. Vite, Python and a local Server are not prerequisites for launching the installed UI. No connection is active at startup; explicitly connect to an existing Server and select a Scope before saving or searching. Without a Server, the shell and settings remain available. Use the commands below for development mode.

Uninstall Desktop through Windows **Installed apps**. Uninstallation does not manage the independent Server, business database or Agent configuration; removing Server data is not part of removing Desktop.

Repeated launches activate the existing window for this channel. Profile storage is exclusively owned until the application exits, preventing concurrent instances from overwriting saved connections. Late save completions cannot clear the unsaved-input warning of a new editor or Scope.

## Build on Windows

Use Windows 11 x64, Visual Studio C++ Build Tools with a Windows SDK, Node **24.14.1**, pnpm **11.13.1**, Rust **1.95.0 MSVC**, **JDK 11 or newer with `java` available on `PATH`**, and WebView2. `desktop/.mise.toml`, `rust-toolchain.toml`, `pnpm-lock.yaml` and `src-tauri/Cargo.lock` pin the tools and dependencies independently of Python and the website.

The OpenAPI Generator used by `generate` and `generate:check` runs on Java. On the first run, `openapi-generator-cli` may download the pinned generator JAR from Maven Central, so the first generation or drift check requires network access. Subsequent runs can reuse the downloaded JAR.

Some machines default to Rust's GNU host. In PowerShell, explicitly select the pinned MSVC host for this process:

```powershell
rustup toolchain install 1.95.0-x86_64-pc-windows-msvc --profile minimal --component clippy --component rustfmt
$env:RUSTUP_TOOLCHAIN = '1.95.0-x86_64-pc-windows-msvc'
pnpm --dir desktop install --frozen-lockfile
pnpm --dir desktop desktop:dev
```

From the repository root:

```powershell
pnpm --dir desktop lint
pnpm --dir desktop typecheck
pnpm --dir desktop test
pnpm --dir desktop build
pnpm --dir desktop ipc:check
cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --check
cargo clippy --locked --manifest-path desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml
pnpm --dir desktop desktop:build
```

`build` produces UI assets only. `desktop:build` produces the release executable and current-user NSIS installer under `desktop/src-tauri/target/release/bundle/nsis/`. No Python, private HTTP server, or Vite process is embedded or started by the installed application. Closing the window exits Desktop.

The unsigned installer is for internal verification. If WebView2 is absent, its configured download bootstrapper needs network access and may require the user to complete Microsoft installation prerequisites. The absent-runtime and standard-user cases require a disposable Windows environment; never remove a developer's WebView2 to simulate them.

## Connect an existing Server

1. Open Connections and add a named profile. HTTP is restricted to literal loopback hosts; other addresses require HTTPS. A reverse-proxy path prefix is preserved.
2. Explicitly choose unauthenticated loopback access or Bearer authentication. Bearer storage is either Windows Credential Manager or this session only. Trust/address changes require credential reconfiguration. An optional CA augments system trust without disabling certificate checks.
3. Select a qualified compatibility profile after comparing its tested build with your deployment. The selection does not prove the remote binary identity. See [validation guide](VALIDATION.md) for the exact fixture and supported combinations.
4. Save, then explicitly use the connection. Merely selecting a saved profile does not activate it. Review liveness, readiness, identity and capabilities separately; none implies resource authorization.
5. Open the Scope dropdown and find an authorized Scope by title (50 per page). Selecting a result updates the active Scope and closes the dialog. Selection never creates a Scope or changes Agent bindings. Editing a query cancels its old read; connection and identity changes invalidate old results.

Profiles persist under the app data directory; credentials never appear in profile JSON. Active authorization, session-only credentials, Scope selection and query/results are not restored as an authenticated offline session. Remove a profile to remove its Desktop configuration and owned credential reference; it does not stop the Server or remove business data.

## Save, find and read a note

After explicitly activating a qualified connection and choosing a Scope, open **Memories** and enter a note in the save form. The target connection and exact Scope are shown before submission. Enter inserts a newline; only the save button submits. The input is plain text, limited conservatively to 8192 raw UTF-8 bytes without truncation. The Server owns normalization and the returned text is authoritative.

Search uses FTS in the selected Scope and returns at most 10 matches. This is not a full directory or history, and ten matches do not establish a total count. **Read exact version** reads the returned Atomic Memory reference (`{family: "atomic-memory", artifact_id, revision}`) at that exact revision; it never substitutes the latest version. Copy buttons explicitly copy either the full plain text or the reference JSON.

A successful save that returns no memory record is reported as an operation success without inventing a reference. A timeout or interrupted dispatched write is **unknown**, not a safe invitation to retry: inspect the original Server/Scope before deciding whether to submit again. Identical text alone cannot identify that operation. Desktop does not automatically replay writes or keep an offline queue. Switching context hides old results while retaining minimal original-operation metadata for this session. See [validation guide](VALIDATION.md) for tested behavior and qualification gaps.

## Contracts and resources

`pnpm --dir desktop generate` derives TypeScript schemas, the reviewed ten-operation manifest, and the Rust wire models from `openapi/powercontext.yaml`; `generate:check` detects drift, including a normalized contract SHA-256. The OpenAPI Generator CLI version is pinned in `desktop/openapitools.json`, and the limited Rust customization lives in `desktop/scripts/openapi-generator/rust/`. Generated `src-tauri/src/transport/wire.rs` must not be edited by hand: after changing the contract or generator template, run `pnpm --dir desktop generate`, then run `pnpm --dir desktop generate:check` in CI. Typed Rust adapters consume that generated manifest and generated wire schemas. No public route is independently handwritten in the application. The manifest is not an IPC permission grant.

`cargo run --locked --manifest-path desktop/src-tauri/Cargo.toml --example export_ipc` derives the TypeScript IPC request/receipt/error types from Rust. `ipc:check` verifies them. IPC exposes typed connection, Scope, memory and diagnostic operations to the main window only; no generic fetch, shell, file, database or secret-read command is granted.

The canonical brand source is `website/assets/powercontext-color.png`, which is read directly without running the website. `pnpm --dir desktop icons` extracts its square mark and uses the pinned Tauri CLI to derive the Windows icon; `icons:check` verifies all three generated assets against the canonical source. UI SVGs originate from the repository's Desktop design assets and are promoted into `ui/src/assets/` for reproducible builds. They are project resources under the repository Apache-2.0 license.

## Native credential feasibility

```powershell
cargo run --locked --manifest-path desktop/src-tauri/Cargo.toml --example credential_probe
```

This explicit probe creates a uniquely named synthetic credential in the preview namespace, loads it in another process and deletes it. It never reads another application's credential or prints a secret. Normal tests simulate unavailable storage and require an explicit session-only choice. Do not treat the probe as end-to-end S2 credential-form verification.

The Windows CI workflow runs on PRs and the preview branch, verifies native vault persistence, builds an unsigned internal installer, and tests Chinese-path installation/uninstallation on its disposable runner. It uploads the installer and a JSON smoke report. CI and mocked IPC tests do not prove clean-machine installation, notification activation, independent service login or Agent capture/recall.

## Local CLI diagnostics

Settings provides explicit local service and Agent integration checks. They remain separate from the active remote connection; a missing local CLI does not disable remote operations. Integration checks may start temporary Agent helpers and do not prove capture/recall.

Register an explicitly trusted local installation in `%APPDATA%/com.powercontext.desktop.preview/diagnostic-cli.json`:

```json
{
  "executable": "C:/trusted/powercontext/Scripts/powercontext.exe",
  "sha256": "REPLACE_WITH_VERIFIED_64_CHARACTER_SHA256",
  "source": "explicit_local_installation"
}
```

The native adapter verifies the absolute executable path and pinned digest before running either `service status --json` or `doctor codex claude-code dsh openclaw opencode pi hermes workbuddy kimi-code zcode --json`. Registration does not require a version; legacy `version` fields are ignored. Compatibility is determined by the diagnostic response matching the adapter's supported output schema. The observed CLI version is collected for display after a valid diagnostic response; an unavailable version is shown as unknown and does not reject the response. This is a local installation pin, not publisher-signature verification; the Python environment and dependencies must also be trusted. Update the registered digest if the executable changes. No PATH-first CLI selection or renderer-provided commands are accepted.

The optional version query has a 15-second deadline, service status 20 seconds, and integration diagnostics 60 seconds. Each invocation limits combined stdout/stderr to 256 KiB. Helpers run hidden in an owned Windows Job; completion, timeout and cancellation clean up their descendants. Only allowlisted status fields reach the UI. Valid unhealthy JSON remains useful even with exit code 1. Isolated real-CLI checks pass; installed-application qualification remains open in [validation guide](VALIDATION.md).

[Validation guide](VALIDATION.md) describes reproducible checks and outstanding platform and product gates.

## Remote installed-package acceptance

Windows GitHub Actions builds an unsigned installer, installs into a temporary Chinese path, and uses a matching Microsoft-signed WebDriver to operate the actual installed WebView2 page. An independent SQLite Server with synthetic data supports explicit connection activation, exact Scope selection, multiline Chinese note save, FTS search, exact reading, and paste-back verification of copied text and reference. The fixture Server and its temporary workspace are cleaned up afterward.

Reports, a screenshot and driver logs accompany the installer in the `desktop-windows-internal-unsigned` artifact. Failed or pending steps are not acceptance passes. The UI script permits only GitHub Windows runners and does not operate your local desktop. Hosted runners do not establish clean standard-user Windows 11, actual IME, screen-reader or Agent-host qualification.

To diagnose installed UI tests, manually dispatch `Desktop validation` with `installer_run` set to an existing Desktop CI run ID. It verifies the original package commit, digest and size before reusing that exact installer, and reports harness and installer commits separately. This diagnostic run does not replace final full-build acceptance.

Installed UI acceptance also checks content isolation between two independent connections, disconnect/reconnect, Server data preservation after removing an inactive profile, and the unknown outcome without replay after a real committed write loses its response. Credit each scenario only when its matching run report passes.

The CI-only lifecycle scenario forcibly ends its own installed Desktop process after saving a synthetic note, then checks that the independent Server still serves the original exact entry and accepts a new readable write. Consult the matching lifecycle report for its result; it does not simulate normal window closure or uninstall preservation.

Installed boundary checks exercise an 8192-byte Unicode note, reject over-budget input, display zero and capped-ten search results, and verify cancel/confirm behavior when disconnecting with an unsaved draft. Each result requires its matching remote report.

After upgrading from an earlier preview, open Connections and select your saved connection. Profiles matching the bundled API contract appear under “Available for this Desktop build”; compare their tested Server builds with your deployment before selecting one, saving, checking and explicitly using the connection again. New connections start with no compatibility selection.

Historical profiles appear as disabled records. A saved incompatible or unavailable selection remains visible with an explanation until explicitly replaced; it is never silently upgraded. This build currently has no product qualification record matching its bundled contract, so business operations remain unavailable in ordinary builds. The independently qualified `ci-fixtures` build is for disposable acceptance tests. Historical qualification evidence and remaining requirements are documented in the [validation guide](VALIDATION.md).
