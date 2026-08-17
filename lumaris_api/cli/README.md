# Petabyte CLI & Dashboard

## CLI
Installed from PyPI, the `petabyte` command is a thin client (only needs `httpx` — it just talks
to the API over HTTPS, so it never pulls in the server):
```bash
pip install petabyte
export PETABYTE_API_URL=https://petabyte.market     # default; or pass --api / omit for localhost
petabyte register -u alice -p secret
petabyte login    -u alice -p secret
petabyte deposit 100
petabyte specs                                       # a readable, cheapest-first GPU table
petabyte launch ollama --hours 2                     # one-click app: cheapest verified GPU, started
petabyte run hello.ipynb --gpu H100 --hours 1        # run a notebook/.py on a rented GPU
petabyte wallet
petabyte doctor                                      # check API URL, connectivity, sign-in
```
The package is built from this directory (repo-root `pyproject.toml`, `name = "petabyte"`). From a
source checkout you can still run it directly with `python cli/petabyte.py <cmd>`, or install the
current tree with `pip install .` from the repo root. The model-hub subcommands (`model`, `pull`)
need the fuller server checkout and aren't in the thin PyPI client yet — they simply aren't offered
there.
`run` books the cheapest matching GPU, escrows funds, dispatches the notebook,
polls, and prints the result. `.ipynb` (code cells) and `.py` files are supported.

### Output modes
- **Human (default):** semantic colour (green=ok, yellow=pending, red=error, cyan=info),
  aligned tables and key/value panels. Colour turns **off** automatically when stdout is a
  pipe or `NO_COLOR` is set — safe for scripts and CI.
- **Machine-readable:** add `--json` to any command for stable JSON on stdout (no colour,
  no log noise). `PETABYTE_JSON=1` does the same globally.
- `petabyte doctor` exits non-zero when the API is unreachable, so it works as a health gate.
- `PETABYTE_CONFIG=/path/cli.json` isolates the saved token/API (handy in CI or tests).

The presentation layer lives in `cli/cli_ui.py` (pure stdlib, no dependencies) and is
shared verbatim with the seller agent and the desktop app so every surface looks the same.
It is covered by `cli/cli_ui_test.py` and `cli/cli_petabyte_test.py`.

## Dashboard
Served by the API at `/` (same-origin, no CORS setup). Start the API and open
`http://localhost:8000/` — live nodes/jobs/GMV stats, wallet + deposit, the GPU
inventory with a live $/hr-vs-AWS savings column, and one-click job runs.

Both need an attested, online seller node (run the agent) to actually execute jobs.
