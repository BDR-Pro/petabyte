# Petabyte CLI & Dashboard

## CLI
```bash
pip install httpx
export PETABYTE_API_URL=http://localhost:8000     # or pass --api
python cli/petabyte.py register -u alice -p secret
python cli/petabyte.py login    -u alice -p secret
python cli/petabyte.py deposit 100
python cli/petabyte.py specs                       # a readable, cheapest-first GPU table
python cli/petabyte.py run hello.ipynb --gpu H100 --hours 1
python cli/petabyte.py wallet
python cli/petabyte.py doctor                       # check API URL, connectivity, sign-in
```
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
