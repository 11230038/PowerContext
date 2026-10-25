<!-- POWERCONTEXT-GUIDANCE:START -->
# Host binding

Run `${POWERCONTEXT_PYTHON} ${POWERCONTEXT_SCOPE_BINDING_SCRIPT} --cwd "$PWD"` before the first data operation and reuse its Scope. The installer binds these paths to the installed interpreter and hooks.

Set PLUGIN_ROOT to the absolute plugin root, two directories above this installed Skill's directory, when a command needs it. Follow actual native tool schemas and host approval.
<!-- POWERCONTEXT-GUIDANCE:END -->
