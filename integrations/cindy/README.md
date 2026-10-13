# Cindy integration

`experimental`

Connect Cindy's native custom MCP client to PowerContext Server. The compatibility target is
[Cindy 0.1.104](https://github.com/makecindy/cindy/releases/tag/v0.1.104), source commit
`ebf092dc3fb9dfa3ad25b10258979c0bcd396634`.

The connection uses the same `/mcp` endpoint, Server tool schemas, authorization, and project-context guidance as
the other PowerContext MCP integrations. Cindy owns MCP transport and credential storage. No `.cindy` archive,
Node worker, separate REST client, or PowerContext package installation inside Cindy is required.

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

Native custom MCP configuration does not supply a trusted Cindy session ID or working directory to PowerContext.
This integration therefore uses explicit Scope selection. It does not create session/workspace bindings from
Agent-authored paths. DSH's automatic workspace binding depends on its own trusted host callback and is not assumed
to exist in Cindy. An operator can manage existing durable bindings through the shared Server operations.

Use the same intent routing as the
[shared project-context Skill](../agent-plugin/powercontext/skills/powercontext-project-context/SKILL.md):

- `search_memory` for requested recall; empty results are valid.
- `remember_memory` for an explicit durable save, then verify the result.
- `capture_content_source` for explicitly selected original material, retaining its `source_id` across retries.
- The shared Handoff and candidate-review tools for explicitly requested transfer or review.

Current instructions outrank retrieved history. Writes retain Cindy and Server authorization checks. An uncertain
write requires inspecting Server state before retrying. Failure stops the requested PowerContext operation while
ordinary work can continue from current context. Do not store credentials or captured recall as original evidence.

This connection provides explicit tools. It has no prompt hooks, automatic Source capture, automatic PreparedContext
injection, `/pc` command, or separate plugin `status` tool. Use the CLI for readiness and the discovered MCP tools for
business operations. Server `prepare_context` is an HTTP hook API and is not exposed in the current MCP catalog.
No equivalent is invented by combining searches.

## Validate locally

Use a disposable checkout of the pinned Cindy source and this repository's development environment:

```bash
git clone --depth 1 --branch v0.1.104 https://github.com/makecindy/cindy.git /tmp/cindy-mcp-validation
uv sync --locked
POWERCONTEXT_CINDY_SOURCE=/tmp/cindy-mcp-validation \
  uv run pytest tests/e2e/test_cindy_mcp_chain.py -q
uv run pytest tests/e2e/test_mcp_transport.py tests/e2e/test_mcp_full_profile.py -q
rm -rf /tmp/cindy-mcp-validation
```

The opt-in test runs Cindy's unmodified `CustomMcpProvider` with Node 22.18+ and uses its Claude Code, Codex,
and Pi configuration projections to connect the standard MCP SDK to a real loopback TCP Server with a fresh SQLite
database. It checks authentication, tool discovery, explicit Scope resolution, scope isolation, Memory readback
across connections, and idempotent Source capture. The Server and temporary database are cleaned up.

This is provider-source and real-MCP acceptance. It does not launch Cindy Desktop, operate its settings or token
vault, or run a model in its harnesses. Complete those checks on a desktop before adding Cindy to the qualified
host catalog. Host implementation references:
[configuration UI](https://github.com/makecindy/cindy/blob/v0.1.104/apps/desktop/src/renderer/components/settings/McpServerDialog.tsx),
[provider](https://github.com/makecindy/cindy/blob/v0.1.104/apps/desktop/src/main/mcp-integrations/custom-mcp-provider.ts),
[Pi routing](https://github.com/makecindy/cindy/blob/v0.1.104/apps/desktop/src/main/mcp-integrations/piEnvironment.ts).
