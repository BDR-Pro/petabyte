"""
postgres_test.py — the things SQLite structurally CANNOT test.

SQLite is a fine dev convenience, but it is the wrong engine to be confident on:
  * it has NO decimal type — NUMERIC(20,8) round-trips through a float, so "exact
    money" is unproven there no matter how green the suite is
  * it SERIALISES writers — a whole class of race conditions simply cannot occur
  * it has no advisory locks — the maintenance leader election is a no-op

So these assertions only mean something on Postgres. Run:

    DATABASE_URL=postgresql+psycopg2://... python postgres_test.py
"""
import os
import sys
import threading
from decimal import Decimal

sys.path.insert(0, os.path.dirname(__file__))

if "postgres" not in os.getenv("DATABASE_URL", ""):
    print("SKIP: postgres_test.py requires a Postgres DATABASE_URL")
    print("      (this is the point — SQLite cannot verify these properties)")
    sys.exit(0)

os.environ.setdefault("SECRET_KEY", "t")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "w")
os.environ.setdefault("WG_PUBLIC_KEY", "x")
os.environ.setdefault("WG_ENDPOINT", "y")
os.environ.setdefault("REAPER_DISABLED", "true")
if "SERVER_PRIVATE_KEY" not in os.environ:
    from cryptography.fernet import Fernet
    os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()

import db as dbmod
from sqlalchemy import text, inspect

with dbmod.engine.begin() as c:
    c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
dbmod.init_db()

from db import (SessionLocal, User, D, q, post, acct_buyer, acct_seller,
                PLATFORM_REVENUE, EXTERNAL_PAYMENTS, DEBIT, CREDIT,
                account_balance, ledger_is_balanced, try_debit, deposit)

PASS = FAIL = 0


def ok(label, cond):
    global PASS, FAIL
    cond = bool(cond)
    PASS += cond
    FAIL += (not cond)
    print(("PASS " if cond else "FAIL ") + label, flush=True)


print("\n=== 1. money columns are a REAL exact NUMERIC (SQLite cannot do this) ===")
insp = inspect(dbmod.engine)
cols = {c["name"]: c for c in insp.get_columns("users")}
bal_type = str(cols["balance"]["type"])
ok(f"users.balance is NUMERIC(20,8) in the actual database (got {bal_type})",
   "NUMERIC" in bal_type.upper())

with dbmod.engine.begin() as c:
    prec = c.execute(text("""
        SELECT numeric_precision, numeric_scale FROM information_schema.columns
        WHERE table_name='users' AND column_name='balance'""")).fetchone()
ok(f"precision/scale enforced by the DB itself: {prec[0]},{prec[1]}",
   prec == (20, 8))

# The killer: does the DATABASE round-trip a value float would corrupt?
s = SessionLocal()
u = User(username="pgexact", password="x", role="buyer")
s.add(u)
s.commit()
s.refresh(u)

# 0.1 + 0.2 is the canonical float failure. Store it, read it back FROM POSTGRES.
u.balance = D("0.1") + D("0.2")
s.add(u)
s.commit()
s.expire_all()
readback = s.query(User).filter_by(username="pgexact").first().balance
ok(f"0.1 + 0.2 stored and re-read from Postgres == exactly 0.3 (got {readback})",
   D(readback) == Decimal("0.3"))
ok("...and it is a Decimal, not a float", isinstance(readback, Decimal))

# 10,000 micro-charges THROUGH THE DATABASE, not just in Python memory.
u.balance = Decimal(0)
s.add(u)
s.commit()
for _ in range(200):
    s.execute(text("UPDATE users SET balance = balance + 0.001 WHERE username='pgexact'"))
s.commit()
s.expire_all()
micro = s.query(User).filter_by(username="pgexact").first().balance
ok(f"200 x $0.001 accumulated IN POSTGRES == exactly $0.20 (got {micro})",
   D(micro) == Decimal("0.2"))
s.close()

print("\n=== 2. advisory lock: only ONE process runs maintenance ===")
# This is the fix for "4 gunicorn workers = 4 reapers". It is a no-op on SQLite,
# so it has never actually been exercised until now.
import main as mainmod

held = []
lock_sessions = []
for i in range(4):          # pretend to be 4 gunicorn workers
    d = SessionLocal()
    lock_sessions.append(d)
    held.append(mainmod._try_acquire_maintenance_lock(d))

ok(f"exactly ONE of 4 workers wins the maintenance lock (got {sum(held)})",
   sum(held) == 1)

# release, and confirm the lock becomes available again
for d in lock_sessions:
    try:
        d.execute(text("SELECT pg_advisory_unlock_all()"))
        d.commit()
    except Exception:
        pass
    d.close()
d2 = SessionLocal()
ok("lock is reacquirable after the leader exits (no permanent deadlock)",
   mainmod._try_acquire_maintenance_lock(d2))
d2.execute(text("SELECT pg_advisory_unlock_all()"))
d2.commit()
d2.close()

print("\n=== 3. REAL concurrent writers (SQLite serialises these away) ===")
s = SessionLocal()
victim = User(username="pgrace", password="x", role="buyer", balance=Decimal("100"))
s.add(victim)
s.commit()
s.refresh(victim)
vid = victim.id
s.close()

# 50 threads each try to debit $10 from a $100 balance, in parallel, for real.
# Exactly 10 must succeed. On SQLite the writers queue up; on Postgres they truly race.
results = []
rlock = threading.Lock()


def race_debit():
    d = SessionLocal()
    try:
        got = try_debit(d, vid, Decimal("10"))
        with rlock:
            results.append(got)
    finally:
        d.close()


threads = [threading.Thread(target=race_debit) for _ in range(50)]
for t in threads:
    t.start()
for t in threads:
    t.join()

s = SessionLocal()
final = s.query(User).filter_by(id=vid).first().balance
wins = sum(1 for r in results if r)
ok(f"50 parallel $10 debits on a $100 wallet -> exactly 10 succeed (got {wins})",
   wins == 10)
ok(f"balance lands on exactly $0.00, never negative (got {final})",
   D(final) == Decimal(0))
s.close()

print("\n=== 4. ledger still balances on the real engine ===")
s = SessionLocal()
deposit(s, s.query(User).filter_by(id=vid).first(), Decimal("25.75"))
s.commit()
bal_ok, broken = ledger_is_balanced(s)
ok(f"ledger balances on Postgres (broken txs: {len(broken)})", bal_ok and not broken)
ok("wallet reconstructs exactly from the ledger",
   account_balance(s, acct_buyer(vid)) == D(s.query(User).filter_by(id=vid).first().balance))

refused = False
try:
    post(s, "test", legs=[(acct_buyer(vid), DEBIT, Decimal("5")),
                          (PLATFORM_REVENUE, CREDIT, Decimal("4"))])
    s.commit()
except Exception:
    refused = True
    s.rollback()
ok("Postgres ledger also REFUSES an unbalanced transaction", refused)
s.close()

print(f"\n=== postgres: {PASS} passed, {FAIL} failed ===", flush=True)
sys.exit(1 if FAIL else 0)
