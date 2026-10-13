# Cindy integration

`experimental`

Connect Cindy's native custom MCP client to PowerContext Server. The compatibility target is
[Cindy 0.1.104](https://github.com/makecindy/cindy/releases/tag/v0.1.104), source commit
`ebf092dc3fb9dfa3ad25b10258979c0bcd396634`.

Explicit tools use the same `/mcp` endpoint, Server schemas, authorization, and project-context guidance as other
PowerContext MCP integrations. An optional resident Ghost adapter adds automatic recall and original-prompt capture
through Cindy's `will-user-message` hook. Users install its standalone `.cindy` archive; DSH is not required.

The hook worker bundles the existing HTTP protocol client and PreparedContext validator from the DSH integration.
This is build-time source reuse. The archive contains the compiled implementation, uses Cindy's bundled Node
runtime, and loads no DSH plugin, harness, SDK, npm package, or source checkout at runtime.

## Connect

Start and verify an independently configured PowerContext Server. For a supported personal macOS/Linux service:

```bash
powercontext config validate --env-file /path/to/powercontext.env
powercontext service install --env-file /path/to/powercontext.env
powercontext service status
```

Load the corresponding client connection settings before `powercontext ready` and `powercontext capabilities`.
See [deployment](../../docs/en/docs/operate/deploy-server.md) and
[remote connections](../../docs/en/docs/operate/connect-remote-server.md) for environment-file and HTTPS requirements.

In Cindy settings, add a custom MCP server:

| Field | Value |
| --- | --- |
| Name | `PowerContext` |
| Transport | `http` (Streamable HTTP) |
| URL | `http://127.0.0.1:8000/mcp`, or the Server's HTTPS `/mcp` URL |
| Bearer token | The configured Server token, without the `Bearer ` prefix; leave empty for anonymous local use |
| Additional headers | Empty for ordinary Bearer authentication |

Use `http`, not legacy `sse`: Cindy's Codex and Pi paths consume the Streamable HTTP configuration.
The endpoint matches the [portable MCP configuration](../agent-plugin/powercontext/mcp.json); that file is a
reference for its URL and protocol, not a Cindy import format. Configure Cindy through its own UI and select the
connection for the task. PowerContext does not edit Cindy's database or bypass its credential UI.

For Cindy on another machine, use a reachable HTTPS Server URL. Desktop loopback is not the remote Agent's
loopback; Cindy's SSH Pi route connects to custom MCP URLs directly. Reconfigure credentials when changing Servers.

## Scope and behavior

Inspect the actual tool catalog before calling a tool. Cindy may namespace the Server's operation names.
Use `list_scopes` and `get_scope` to inspect an existing Scope, or `create_scope` only when the user requests one.
Before a scoped operation, call `resolve_scope_binding` with the selected Server-issued `explicit_scope_id`
and `allow_default: false`. Reuse the returned `scope_id` for subsequent calls. An absent binding stops the memory
operation; it does not authorize inventing a Scope, changing a binding, or silently using the Server default.

Native custom MCP configuration does not supply a trusted Cindy session ID or working directory to PowerContext,
so explicit tool calls use the selected Scope. The automatic hook receives its session identity from the Host event
and resolves the Server's `{integration: "cindy", kind: "session", external_id: sessionId}` binding. Neither path
creates bindings from Agent-authored paths or falls back to a global Scope. Workspace identity is not supplied by
this hook; DSH's workspace callback is a separate host capability.

Use the same intent routing as the
[shared project-context Skill](../agent-plugin/powercontext/skills/powercontext-project-context/SKILL.md):

- `search_memory` for requested recall; empty results are valid.
- `remember_memory` for an explicit durable save, then verify the result.
- `capture_content_source` for explicitly selected original material, retaining its `source_id` across retries.
- The shared Handoff and candidate-review tools for explicitly requested transfer or review.

Current instructions outrank retrieved history. Writes retain Cindy and Server authorization checks. An uncertain
write requires inspecting Server state before retrying. Failure stops the requested PowerContext operation while
ordinary work can continue from current context. Do not store credentials or captured recall as original evidence.

## Enable automatic hooks

Import `dist/powercontext-cindy-hooks-0.1.0.cindy` into Cindy and enable the plugin. In its settings, select the same
Server URL and Scope as the native MCP connection, configure its URL-bound credential if needed, and check
**Enable automatic memory**. Native MCP and Ghost credentials have separate Host-owned storage; configure both
through their respective UI. Prompt capture is independently selectable.

An explicit Scope setting overrides the session binding. To keep sessions separate, leave it empty and have an
operator set a session binding with the native `set_scope_binding` tool. The Ghost `status` tool reports the latest
observed `session_id`; it does not guess an ID from project text or invent a Scope. Reuse that Host-issued identity.

Before a local user message is dispatched, the adapter resolves its Scope, requests bounded PreparedContext, and
captures only the original incoming prompt as an independent Source. A ready context is appended as untrusted
historical evidence. Cindy's `rewrite` verdict changes the text displayed, persisted, and sent to the Agent; this
is not a hidden system-message injection. An empty or failed recall allows the original message to continue.
Capture can succeed independently of recall and does not establish extraction or Memory production.
The captured text is the Host's input to this adapter, before its own rewrite. Earlier Ghost rewriters may have
already changed it; Cindy does not supply an independent raw-draft field. Capture metadata identifies this stage.

Cindy gives entry hooks three seconds. The worker inherits a 1.8-second deadline from hook delivery, including
settings loading and worker startup; an expired request cannot start a late capture. The adapter sends
an allow verdict by 2.2 seconds after delivery if work has not completed. A late response cannot rewrite the message.
The Host independently enforces its own deadline. Context must fit the configured UTF-8 budget and the complete
rewrite must fit Cindy's 16,000-character limit; oversized context is omitted without truncating the user message.

Source identity includes Scope, trusted session ID, Host hook ID, and the original prompt. Repeating the same delivery
keeps the identity; a newly submitted message has a new Host hook ID. Cindy does not provide a durable message/turn
ID in this hook, so cross-delivery deduplication is not claimed. A message containing the adapter's historical-context
markers is allowed without recapture or further injection. Flagged credentials are skipped. Uncertain writes are
reported without an automatic retry. The plugin never blocks or rewrites an assistant reply.

Automatic hooks cover local user-message dispatch and steering. They do not establish coverage of remote, worker,
scheduled, goal-continuation, or pre-compaction flows. There is no `/pc` command or forced processing flush. The
Ghost `status` tool reports local outcomes, not Server readiness or successful model use of history.
Use the CLI for readiness. `prepare_context` remains the shared HTTP hook API; explicit business tools remain MCP.

## Validate locally

Use a disposable checkout of the pinned Cindy source and this repository's development environment:

```bash
git clone --depth 1 --branch v0.1.104 https://github.com/makecindy/cindy.git /tmp/cindy-mcp-validation
uv sync --locked
pnpm --dir integrations/dsh/plugins/powercontext install --frozen-lockfile --config.auto-install-peers=false
pnpm --dir integrations/dsh/plugins/powercontext exec tsdown --config ../../../cindy/tsdown.config.ts
uv run python integrations/cindy/scripts/package.py
node --test integrations/cindy/tests/*.test.cjs
POWERCONTEXT_CINDY_SOURCE=/tmp/cindy-mcp-validation \
  uv run pytest tests/e2e/test_cindy_mcp_chain.py tests/e2e/test_cindy_hooks_chain.py -q
uv run pytest tests/e2e/test_mcp_transport.py tests/e2e/test_mcp_full_profile.py -q
rm -rf /tmp/cindy-mcp-validation
```

The opt-in test runs Cindy's unmodified `CustomMcpProvider` with Node 22.18+ and uses its Claude Code, Codex,
and Pi configuration projections to connect the standard MCP SDK to a real loopback TCP Server with a fresh SQLite
database. It checks authentication, tool discovery, explicit Scope resolution, scope isolation, Memory readback
across connections, and idempotent Source capture. The Server and temporary database are cleaned up.

The hook test extracts the archive into a fresh directory and runs its worker with filesystem access limited to
that directory and with no DSH dependencies. It executes the pinned upstream subscription gateway against the
actual plugin entry and a real TCP Server. Host credential/message bridges and unused database imports are
simulated. It checks applied rewrite verdicts, independent session Scopes, persisted original Sources, missing
bindings, and prevention of recapturing edited historical context.

These are provider/gateway-source and real transport checks. They do not launch Cindy Desktop, operate its settings
or token vault, or run a model in its harnesses. Complete those checks on a desktop before adding Cindy to the
qualified host catalog. Host implementation references:
[configuration UI](https://github.com/makecindy/cindy/blob/v0.1.104/apps/desktop/src/renderer/components/settings/McpServerDialog.tsx),
[provider](https://github.com/makecindy/cindy/blob/v0.1.104/apps/desktop/src/main/mcp-integrations/custom-mcp-provider.ts),
[Pi routing](https://github.com/makecindy/cindy/blob/v0.1.104/apps/desktop/src/main/mcp-integrations/piEnvironment.ts).

The [hook contract](https://github.com/makecindy/cindy/blob/v0.1.104/apps/desktop/src/main/cindy-brain/forge.ts)
and [subscription gateway](https://github.com/makecindy/cindy/blob/v0.1.104/apps/desktop/src/main/cindy-brain/subscriptionGateway.ts)
define delivery, rewrite, and timeout semantics.
