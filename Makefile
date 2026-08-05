# Petabyte — developer & investor-demo entry points.
# Cross-platform note: these targets shell out to bash + python3; on Windows use WSL.

API := lumaris_api

.PHONY: help investor-demo demo-reset demo-seed demo-test stripe-demo stripe-test reconcile payout-test payout-coverage test test-postgres install verify

help:
	@echo "Petabyte make targets:"
	@echo "  make investor-demo   Seed labelled demo data + start the server, print accounts & URLs"
	@echo "  make demo-reset      Wipe and reseed the demo, then start the server"
	@echo "  make demo-seed       Seed the demo only (no server)"
	@echo "  make demo-test       Run the demo correctness/honesty test suite"
	@echo "  make stripe-demo     Narrated Stripe Connect flow (test mode, fake gateway)"
	@echo "  make stripe-test     Run the Stripe Connect test suite (offline assertions)"
	@echo "  make reconcile       Reconcile internal ledger + transactions vs Stripe (test mode)"
	@echo "  make payout-test     Run the provider-neutral global payout routing suite"
	@echo "  make payout-coverage Print the honest seller-payout country coverage (fails <100)"
	@echo "  make test            Run smoke + adversarial + stripe + payout + gateway suites (SQLite)"
	@echo "  make test-postgres   Run the full suite against SQLite AND PostgreSQL"
	@echo "  make install         Install Python dependencies"
	@echo "  make verify          install + migrate check + full test + demo test"

install:
	pip install -r $(API)/requirements.txt

# The single command for a five-minute investor demonstration.
investor-demo:
	cd $(API) && bash demo_run.sh

demo-reset:
	cd $(API) && bash demo_run.sh reset

demo-seed:
	cd $(API) && bash demo_run.sh seed

demo-test:
	cd $(API) && python3 demo_test.py

# The deterministic Stripe Connect walkthrough (test mode, offline fake gateway).
stripe-demo:
	cd $(API) && python3 stripe_demo.py

stripe-test:
	cd $(API) && python3 stripe_test.py

# Financial reconciliation: internal ledger + ComputeTransactions vs Stripe (test mode).
reconcile:
	cd $(API) && python3 reconcile.py

# Provider-neutral payout routing/aggregation suite (offline, deterministic).
payout-test:
	cd $(API) && python3 payout_test.py

# Honest seller-payout country coverage. Exits non-zero while below the 100-country
# target — coverage grows ONLY via real provider approvals + implemented rails.
payout-coverage:
	python3 scripts/verify_payout_country_coverage.py

test:
	cd $(API) && bash run_tests.sh

test-postgres:
	cd $(API) && bash run_tests.sh --postgres

# Clean-DB migration/schema sanity + full tests + demo honesty tests.
verify: install
	cd $(API) && python3 -c "import os; os.environ.setdefault('DATABASE_URL','sqlite:///./_verify.db'); os.environ.setdefault('SECRET_KEY','x'); os.environ.setdefault('SERVER_PRIVATE_KEY','x'); import db; db.init_db(); print('schema builds from clean DB: OK')"
	cd $(API) && bash run_tests.sh
	cd $(API) && python3 demo_test.py
	@echo "verify: OK"
