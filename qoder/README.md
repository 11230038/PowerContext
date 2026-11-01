# Qoder × PowerContext — native MCP integration acceptance

This directory is the Qoder ecosystem submission for PowerContext. It demonstrates a real
**Model Context Protocol** integration rather than copying memory into prompt files:

- PowerContext runs its native Streamable HTTP MCP endpoint;
- Qoder connects to that endpoint as an MCP client;
- explicit project guidance is persisted with `remember_memory` as Atomic Memory Artifacts;
- a later session retrieves it with `search_memory`;
- the exact persisted revision can be inspected with `get_artifact` and its ETag;
- the validation script checks the MCP tool surface, durable Artifact references, retrieval,
  and exact artifact reads.

## Directory

| Path | Purpose |
| --- | --- |
| `.mcp.json.example` | Minimal Qoder MCP server configuration example |
| `src/powercontext_client.py` | Small typed client for PowerContext's native MCP endpoint |
| `src/validate_qoder_mcp.py` | End-to-end acceptance runner and evidence generator |
| `samples/qoder-session.md` | Manual two-session Qoder conversation script |
| `tests/` | Offline unit tests for parsing and client behavior |
| `artifacts/` | Generated JSON and Markdown acceptance evidence |

## Architecture

```text
Qoder agent
   │  MCP tool discovery / calls
   ▼
PowerContext Server  http://127.0.0.1:8000/mcp/
   ├── create_scope       independent acceptance boundary (optional)
   ├── remember_memory    durable Atomic Memory Artifact
   ├── search_memory      focused cross-session retrieval
   └── get_artifact       exact revision plus current content ETag
            │
            ▼
     PowerContext persistence
```

The acceptance script creates a dedicated Scope only when `--scope-id` is omitted. In a normal
Qoder installation, reuse the host-selected/current Scope rather than creating a Scope from a
repository path or branch name.

## Requirements

- Python 3.11+
- a PowerContext checkout or installed package with the `server` extra
- the Python MCP SDK for the validation client
- Qoder with Streamable HTTP MCP server support

Install the acceptance client dependencies:

```bash
cd qoder
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 1. Start PowerContext Server

From the PowerContext repository root, run a local unauthenticated server on loopback:

```bash
powercontext server run --host 127.0.0.1 --port 8000 --no-env-file
```

The native MCP endpoint is:

```text
http://127.0.0.1:8000/mcp/
```

PowerContext uses persistent SQLite storage by default. To isolate a demonstration deployment,
set `POWERCONTEXT_SERVER_DATABASE` according to the PowerContext Server configuration used in
your environment.

## 2. Connect Qoder

Copy `.mcp.json.example` to the MCP configuration location supported by your Qoder release, or
add the equivalent server through Qoder's MCP settings UI:

```json
{
  "mcpServers": {
    "powercontext": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8000/mcp/"
    }
  }
}
```

Restart or reload Qoder, then confirm it discovers these tools:

- `remember_memory`
- `search_memory`
- `get_artifact`

Use the conversation in `samples/qoder-session.md` to demonstrate an explicit save in one Qoder
conversation and retrieval in a new conversation.

## 3. Run automated acceptance

With PowerContext Server running:

```bash
python src/validate_qoder_mcp.py --out artifacts
```

To reuse an existing Scope selected for the Qoder session:

```bash
python src/validate_qoder_mcp.py \
  --scope-id YOUR_SCOPE_ID \
  --out artifacts
```

The script performs five checks:

1. discovers the required native MCP tools;
2. selects or creates an independent validation Scope;
3. writes three explicit memories and verifies real `atomic-memory` Artifact references;
4. retrieves the workflow, API decision, and coding convention through `search_memory`;
5. reads one exact Atomic Memory Artifact and verifies its current ETag and content.

It writes:

- `artifacts/validation-<UTC timestamp>.json` — complete structured MCP evidence;
- `artifacts/validation-<UTC timestamp>.md` — human-readable checks and prepared context.

Exit code is zero only when all checks pass.

## 4. Run offline tests

```bash
pytest -q
```

These tests do not require a running PowerContext Server. They cover environment configuration,
search-result parsing, and structured MCP response handling.

## What proves the integration is real

- The client initializes an MCP session and calls tools by their native PowerContext names.
- `remember_memory` returns Atomic Memory records with `family`, `artifact_id`, and `revision`.
- The second retrieval is a server query, not a local file read or prompt replay.
- `get_artifact` returns the exact persisted content together with the current HTTP ETag.
- Evidence files retain the exact tool results needed to inspect the acceptance run.

## Boundaries

- The validation runner uses `mode: fts`, so it does not require an embedding model.
- Creating a Scope requires server-admin permission. Pass `--scope-id` when the deployment uses
  enforced access control or when Qoder already has a current Scope binding.
- Do not store secrets in `remember_memory`.
- Qoder release-specific UI labels and the exact MCP configuration file location may differ; the
  transport URL and PowerContext tool contract remain the acceptance boundary.
