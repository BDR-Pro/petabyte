# Petabyte CLI & Dashboard

## CLI
```bash
pip install httpx
export PETABYTE_API_URL=http://localhost:8000     # or pass --api
python cli/petabyte.py register -u alice -p secret
python cli/petabyte.py login    -u alice -p secret
python cli/petabyte.py deposit 100
python cli/petabyte.py specs
python cli/petabyte.py run hello.ipynb --gpu H100 --hours 1
python cli/petabyte.py wallet
```
`run` books the cheapest matching GPU, escrows funds, dispatches the notebook,
polls, and prints the result. `.ipynb` (code cells) and `.py` files are supported.

## Dashboard
Served by the API at `/` (same-origin, no CORS setup). Start the API and open
`http://localhost:8000/` — live nodes/jobs/GMV stats, wallet + deposit, the GPU
inventory with a live $/hr-vs-AWS savings column, and one-click job runs.

Both need an attested, online seller node (run the agent) to actually execute jobs.
