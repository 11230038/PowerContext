# Complete Server source baselines

Each resource records the complete `sqlite_schema` inventory produced by a
specific installed public wheel. Inventories include indexes, constraints,
triggers, virtual tables, and their SQLite shadow tables. They contain schema
definitions and artifact provenance, with no business rows or deployment paths.

Recognition identifies a source schema. It does not validate its business data,
adopt a schema revision, authorize writes, establish Server readiness, or promise
an executable upgrade path. The maintenance runner keeps an identified source
blocked until the registered migration chain covers that complete source and its
domain preconditions.

## SQLite 1.3.0

`1.3.0/sqlite.json` was captured from the public
`powercontext-1.3.0-py3-none-any.whl`, SHA-256
`8da7983763f3a6ab80b413c770a4973a46c557a54e1a1fa675099e58d47305e5`.
The wheel was installed with its `cli,server` extras in an isolated environment.
A real Server initialized a new file with enforced Access, all Processing roles,
and no model or embedding provider. Public HTTP operations created Scopes,
Atomic Memory, a Source, pending and approved Candidates, and an Access binding
with idempotency receipts. After stopping the Server, SQLite's backup API
produced the database used for schema capture.

The resource records the Python, SQLite, and SQLAlchemy capture versions. Its
94 explicit objects comprise 81 tables, 10 indexes, and 3 triggers. The complete
schema fingerprint is
`11e8770068a5fe32dfb25681564dbbe586ba0fd0238ed01adf1b09dde8a49f22`.
This shape differs from the historical four-table migration prototype.

The recognizer uses exact definitions. A different dependency version, optional
feature, missing FTS helper, manually altered constraint, or extra persistent
object may produce an unregistered shape. Such a shape remains unknown; a
semantically similar subset is never sufficient for adoption. Additional source
shapes require their own installed-release capture and review.
