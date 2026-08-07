# Petabyte — developer & investor-demo entry points.
# Cross-platform note: these targets shell out to bash + python3; on Windows use WSL.

API := lumaris_api

.PHONY: help investor-demo demo-reset demo-seed demo-test stripe-demo stripe-test reconcile audit-ledger payout-test payout-coverage email-test email-integration stripe-integration local-e2e test test-postgres install verify verify-series-a diligence-bundle

help:
	@echo "Petabyte make targets:"
	@echo "  make investor-demo   Seed labelled demo data + start the server, print accounts & URLs"
	@echo "  make demo-reset      Wipe and reseed the demo, then start the server"
	@echo "  make demo-seed       Seed the demo only (no server)"
	@echo "  make demo-test       Run the demo correctness/honesty test suite"
	@echo "  make stripe-demo     Narrated Stripe Connect flow (test mode, fake gateway)"
	@echo "  make stripe-test     Run the Stripe Connect test suite (offline assertions)"
	@echo "  make stripe-integration  Real Stripe TEST-mode integration (needs sk_test_; skips otherwise)"
	@echo "  make email-test      Run the Mailgun email suite (offline, mocked)"
	@echo "  make email-integration  Send a REAL Mailgun email (needs MAILGUN_API_KEY; skips otherwise)"
	@echo "  make local-e2e       Run the whole platform locally + a buyer/seller/admin flow (offline)"
	@echo "  make reconcile       Reconcile internal ledger + transactions vs Stripe (test mode)"
	@echo "  make audit-ledger    Ledger integrity + booking/payout cross-checks (read-only; fails on drift)"
	@echo "  make payout-test     Run the provider-neutral global payout routing suite"
	@echo "  make payout-coverage Print the honest seller-payout country coverage (fails <100)"
	@echo "  make test            Run smoke + adversarial + stripe + payout + gateway suites (SQLite)"
	@echo "  make test-postgres   Run the full suite against SQLite AND PostgreSQL"
	@echo "  make install         Install Python dependencies"
	@echo "  make verify          install + migrate check + full test + demo test"
	@echo "  make verify-series-a Run the release gates + write a machine-readable evidence bundle"
	@echo "  make diligence-bundle  Alias for verify-series-a (investor diligence evidence)"

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

# Opt-in integration test against REAL Stripe TEST mode (needs sk_test_/pk_test_).
# Skips cleanly when no STRIPE_SECRET_KEY is set. NEVER runs on a live key.
stripe-integration:
	cd $(API) && python3 stripe_integration_test.py

# Full buyer->seller->settlement flow against a locally-run server (fake Stripe
# gateway, SQLite, no GPU). Traces bugs; exits non-zero if any step misbehaves.
local-e2e:
	python3 scripts/e2e/local_e2e.py

# Mailgun transactional email: offline unit suite, and an opt-in real send.
email-test:
	cd $(API) && python3 email_test.py

# Sends a REAL email via Mailgun (needs MAILGUN_API_KEY + MAILGUN_DOMAIN). Skips otherwise.
email-integration:
	cd $(API) && python3 email_integration_test.py

# Financial reconciliation: internal ledger + ComputeTransactions vs Stripe (test mode).
reconcile:
	cd $(API) && python3 reconcile.py

# Ledger integrity + booking/payout cross-checks. Read-only; exits non-zero on any drift,
# so it can gate a release. Point DATABASE_URL at the DB you want to audit.
audit-ledger:
	python3 scripts/audit_ledger.py

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

# Release / diligence gate: runs the gates and writes a machine-readable evidence bundle to
# evidence/. Exits non-zero on any P0 failure. Add ARGS='--strict' to also fail on P0 skips
# (e.g. Postgres invariants), or ARGS='--quick' for the fast structural gates only.
verify-series-a:
	python3 scripts/verify_series_a.py $(ARGS)

diligence-bundle: verify-series-a

# Clean-DB migration/schema sanity + full tests + demo honesty tests.
verify: install
	cd $(API) && python3 -c "import os; os.environ.setdefault('DATABASE_URL','sqlite:///./_verify.db'); os.environ.setdefault('SECRET_KEY','x'); os.environ.setdefault('SERVER_PRIVATE_KEY','x'); import db; db.init_db(); print('schema builds from clean DB: OK')"
	cd $(API) && bash run_tests.sh
	cd $(API) && python3 demo_test.py
	@echo "verify: OK"
