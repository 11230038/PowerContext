---
title: Cindy
description: Connect Cindy 0.1.104 to the shared PowerContext MCP tools.
---

# Cindy

`experimental`

Cindy connects to the running PowerContext Server through its native custom MCP settings. This uses the same
Server tool catalog and authorization as other MCP integrations. No Ghost plugin or separate REST worker is required.
The compatibility target is [Cindy 0.1.104](https://github.com/makecindy/cindy/releases/tag/v0.1.104).

## Connect the Server

Follow [Install and run](../get-started/install-and-run.md) to install PowerContext and
[Deploy the Server](../operate/deploy-server.md) to configure and verify it. On supported personal macOS/Linux:

```bash
powercontext service install --env-file /path/to/powercontext.env
powercontext service status
```

Load the corresponding client connection settings, then run `powercontext ready` and `powercontext capabilities`.
In Cindy settings, add a custom MCP server with these values:

| Field | Value |
| --- | --- |
| Name | `PowerContext` |
| Transport | `http` (Streamable HTTP) |
| URL | `http://127.0.0.1:8000/mcp`, with your actual port |
| Bearer token | Your Server token, without the `Bearer ` prefix; empty for anonymous local use |
| Additional headers | Empty for ordinary Bearer authentication |

Select the connection for the task and inspect its discovered tools. Use Streamable HTTP; legacy SSE is not available
through Cindy's Codex/Pi configuration path. For a Server on another machine, use a reachable HTTPS URL. Desktop
loopback is not the remote Agent's loopback; the SSH Pi path connects to custom MCP endpoints directly.
See [remote connections](../operate/connect-remote-server.md).

## Select a Scope and use explicit tools

Inspect existing Scopes through `list_scopes` and `get_scope`. Create one only when requested.
Call `resolve_scope_binding` with the selected Server-issued `explicit_scope_id` and `allow_default: false`, then
reuse the returned `scope_id`. A missing or invalid binding stops the memory operation. Do not guess a Scope from
a directory or fall back to a global Scope.

Use the actual discovered namespace for `search_memory`, `remember_memory`, and `capture_content_source`.
Memory saves require user intent and result verification. Source capture accepts original material and retains the
same `source_id` for retries; it does not prove Memory extraction has completed. Handoff and candidate-review
operations use the same Server tools and approval boundaries as other MCP hosts.

The native connection does not provide a trusted Cindy session identity or workspace path. Scope selection is
explicit. DSH's workspace binding and automatic recall depend on its own host callbacks; those are not assumed in
Cindy. There are no prompt hooks, automatic capture, PreparedContext injection, or `/pc` commands in this connection.
The current MCP catalog does not expose `prepare_context`; use the CLI for readiness checks.

Retrieved history does not override current instructions. On failure, report the failed operation and continue
ordinary work from available context. Inspect Server state before retrying an uncertain write.

## Validation boundary

The [integration README](https://github.com/oceanbase/powercontext/blob/master/integrations/cindy/README.md)
provides reproducible provider-source acceptance commands. They exercise Cindy 0.1.104's unmodified native provider
projections for Claude Code, Codex, and Pi against a real local TCP Server with fresh SQLite storage.

This verifies provider configuration, authentication, tool discovery, Scope isolation, Memory readback, and Source
idempotency. It does not establish desktop installation, credential UI behavior, live harness routing, or model
execution. Cindy remains outside the qualified host catalog until those desktop checks are completed.
