"""db_invariants_test.py — money-impossible states are rejected at the DATABASE layer.

The double-entry ledger and balances are protected by application logic (post(), guarded
debits), but a stray write, a migration, or raw SQL could bypass that. These DB-level CHECK
constraints make the impossible states un-writable regardless of the code path:

  * a ledger leg's amount is ALWAYS > 0 (money can't be created/destroyed by a 0/negative leg);
  * a ledger leg's direction is a closed set ('debit'|'credit'), never a typo;
  * a user's balance and earnings can NEVER go negative.

Offline only: forced SQLite (which enforces CHECK constraints). Run: python db_invariants_test.py
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./db_invariants_test.db"
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = __import__(
    "cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["WG_PUBLIC_KEY"] = "x"; os.environ["WG_ENDPOINT"] = "y"

for _f in ("db_invariants_test.db", "db_invariants_test.db-wal", "db_invariants_test.db-shm"):
    if os.path.exists(_f):
        os.remove(_f)

from decimal import Decimal  # noqa: E402

from sqlalchemy.exc import IntegrityError  # noqa: E402

import db as dbmod  # noqa: E402

dbmod.init_db()
# SQLite honours CHECK constraints, but ONLY on a connection with them declared at CREATE TABLE
# time (create_all did that here). Belt-and-suspenders: ensure enforcement is on.
with dbmod.engine.begin() as _c:
    _c.exec_driver_sql("PRAGMA foreign_keys=ON")

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def rejects(label, make_row):
    """Assert inserting make_row() violates a DB constraint (IntegrityError)."""
    s = dbmod.SessionLocal()
    raised = False
    try:
        s.add(make_row()); s.commit()
    except IntegrityError:
        raised = True
    except Exception:  # noqa: BLE001 — any DB-level rejection counts as "blocked"
        raised = True
    finally:
        s.rollback(); s.close()
    ok(label, raised)


def accepts(label, make_row):
    s = dbmod.SessionLocal()
    good = False
    try:
        s.add(make_row()); s.commit(); good = True
    except Exception:  # noqa: BLE001
        good = False
    finally:
        s.rollback(); s.close()
    ok(label, good)


# ---- ledger leg amount must be > 0 ----
rejects("DB rejects a NEGATIVE ledger amount (money cannot be destroyed)",
        lambda: dbmod.LedgerEntry(account="x:1", direction="debit",
                                  amount=Decimal(-5), entry_type="t"))
rejects("DB rejects a ZERO ledger amount",
        lambda: dbmod.LedgerEntry(account="x:1", direction="credit",
                                  amount=Decimal(0), entry_type="t"))
# ---- ledger direction is a closed set (and NEVER null) ----
rejects("DB rejects an invalid ledger direction (typo/garbage)",
        lambda: dbmod.LedgerEntry(account="x:1", direction="sideways",
                                  amount=Decimal(10), entry_type="t"))
rejects("DB rejects a NULL ledger direction (a leg must be debit or credit)",
        lambda: dbmod.LedgerEntry(account="x:1", direction=None,
                                  amount=Decimal(10), entry_type="t"))
accepts("DB accepts a valid positive debit leg",
        lambda: dbmod.LedgerEntry(account="x:1", direction="debit",
                                  amount=Decimal(10), entry_type="t"))
accepts("DB accepts a valid positive credit leg",
        lambda: dbmod.LedgerEntry(account="x:1", direction="credit",
                                  amount=Decimal(10), entry_type="t"))

# ---- user balance / earnings can never be negative ----
rejects("DB rejects a NEGATIVE user balance",
        lambda: dbmod.User(username="neg_bal", password="x", balance=Decimal(-1)))
rejects("DB rejects NEGATIVE user earnings",
        lambda: dbmod.User(username="neg_earn", password="x", earnings=Decimal(-1)))
accepts("DB accepts a user with zero balance/earnings",
        lambda: dbmod.User(username="ok_user", password="x",
                           balance=Decimal(0), earnings=Decimal(0)))

s = dbmod.SessionLocal()
for _f in ("db_invariants_test.db", "db_invariants_test.db-wal", "db_invariants_test.db-shm"):
    pass
s.close()
for _f in ("db_invariants_test.db", "db_invariants_test.db-wal", "db_invariants_test.db-shm"):
    try:
        os.remove(_f)
    except OSError:
        pass

print(f"\n=== db_invariants: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
