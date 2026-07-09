# Petabyte Desktop Agent

Native desktop packaging of the Petabyte node agent — for sellers who prefer a
double-clickable app over the WSL2 service. Runs the agent (heartbeat, job polling,
Ed25519 attestation, idle-fallback) plus a local NiceHash-style dashboard.

- Entry point: `petabyte_desktop.py`
- Build to `.exe`: see `BUILD.md`
- Config: `.env` (see `.env.example`) or paste API key + Spec ID in the dashboard
- Points at `https://petabyte.market` by default

The agent modules (`task_fetcher.py`, `crypto.py`, `vm.py`, `notebook.py`,
`provision.py`, `attest_node.py`) are the same code path as `../lumaris_agent`.
