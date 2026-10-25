<!-- POWERCONTEXT-GUIDANCE:START -->
# Host binding

Use current-request PowerContext routing metadata and its Session binding. For an explicit workspace binding command, run `uv run --frozen --quiet --project "${PLUGIN_ROOT}" python "${PLUGIN_ROOT}/scripts/scope_binding.py" --cwd "$PWD"`. Its workspace result does not replace a current Session override.

Set PLUGIN_ROOT to the absolute plugin root, two directories above this installed Skill's directory, when a command needs it. Follow actual native tool schemas and host approval.
<!-- POWERCONTEXT-GUIDANCE:END -->
