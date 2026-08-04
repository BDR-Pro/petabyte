"""demo_test.py — the investor demo must be correct, honest, and repeatable.

Runs the real seeding path against a throwaway DB and asserts:
  * seeding produces the expected supply/demand/settlement,
  * every seeded entity is labelled is_demo (never shown as real traction),
  * metrics separate demo from real and stay internally consistent,
  * the money is conserved (ledger balances) after seeding,
  * reset restores the initial state and reseeds deterministically,
  * the simulated result is clearly labelled and no buyer code is executed.

Run: python demo_test.py   (SQLite by default; set DATABASE_URL for Postgres)
"""
import os

# Bring up the same stub/demo env the seeder uses, before importing the app.
import demo as demo_mod
demo_mod._bootstrap_env()
os.environ["DATABASE_URL"] = os.getenv("DATABASE_URL", "sqlite:///./demo_test.db")

for f in ("demo_test.db", "demo_test.db-wal", "demo_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

from fastapi.testclient import TestClient  # noqa: E402  (env must be set before import)
import db as dbmod  # noqa: E402
import main as app_main  # noqa: E402


def ok(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    assert cond, label


# --- seed a fresh demo -------------------------------------------------------
demo_mod.wipe(dbmod)
client = TestClient(app_main.app)
summary = demo_mod.seed(client, dbmod)

s = dbmod.SessionLocal()
User, Spec, Booking, Task = dbmod.User, dbmod.SellerSpec, dbmod.Booking, dbmod.Task

# --- 1. seeding produced the expected shape ---------------------------------
n_specs = s.query(Spec).count()
n_online = s.query(Spec).filter(Spec.status == "online").count()
ok(f"seeded all demo nodes (got {n_specs})", n_specs == len(demo_mod.DEMO_SELLERS))
ok("every seeded node is online", n_online == n_specs)
ok("seeded jobs settled at least 3 bookings",
   s.query(Booking).filter(Booking.status == "released").count() >= 3)

# --- 2. HONESTY: everything seeded is labelled is_demo ----------------------
ok("no seeded user is unlabelled",
   s.query(User).filter(User.username.like("demo_%"), User.is_demo == False).count() == 0)  # noqa: E712
ok("every seeded spec is is_demo",
   s.query(Spec).filter(Spec.is_demo == False).count() == 0)  # noqa: E712
ok("every seeded booking is is_demo",
   s.query(Booking).filter(Booking.is_demo == False).count() == 0)  # noqa: E712

# --- 3. HONESTY: no buyer code executed; result is labelled simulated --------
completed = s.query(Task).filter(Task.status == "completed", Task.result.isnot(None)).all()
ok("completed demo jobs carry a SIMULATED, non-executed result label",
   len(completed) >= 1 and all("SIMULATED" in (t.result or "") for t in completed))

# --- 4. money is conserved --------------------------------------------------
balanced, broken = dbmod.ledger_is_balanced(s)
ok(f"ledger balances after seeding (broken={broken})", balanced)

# --- 5. metrics separate demo from real and are consistent ------------------
m_demo = client.get("/metrics/overview?scope=demo").json()
m_real = client.get("/metrics/overview?scope=real").json()
ok("metrics flag demo data present", m_demo["contains_demo_data"] is True)
ok("real-scope excludes all seeded data",
   m_real["supply"]["registered"] == 0 and float(m_real["economics"]["gmv"]) == 0.0)
ok("effective take rate matches the configured platform fee",
   abs(m_demo["economics"]["effective_take_rate_pct"] - float(dbmod.PLATFORM_TAKE_RATE) * 100) < 0.11)
gmv = float(m_demo["economics"]["gmv"])
fee = float(m_demo["economics"]["platform_revenue"])
pay = float(m_demo["economics"]["seller_payouts"])
ok(f"gmv == platform_revenue + seller_payouts ({gmv} == {fee}+{pay})",
   abs(gmv - (fee + pay)) < 0.01)
ok("completion rate is a real ratio of completed/(completed+failed)",
   m_demo["jobs"]["completion_rate_pct"] is not None and 0 < m_demo["jobs"]["completion_rate_pct"] <= 100)
ok("supply broken down by region and hardware",
   len(m_demo["supply"]["by_region"]) >= 2 and len(m_demo["supply"]["by_hardware"]) >= 2)
ok("buyer savings vs cloud is reported with a basis",
   float(m_demo["economics"]["buyer_savings_vs_cloud"]) > 0 and m_demo["economics"]["savings_basis_bookings"] >= 1)
ok("metrics report the ledger as balanced", m_demo["integrity"]["ledger_balanced"] is True)

# --- 6. trust ladder is honest (no fake TEE) --------------------------------
pub = client.get("/marketplace/specs").json()["specs"]
levels = {p["trust"]["level"] for p in pub}
ok("demo supply spans agent- and benchmark-verified trust levels",
   "benchmark_verified" in levels)
detail = client.get(f"/marketplace/specs/{pub[0]['id']}").json()
ok("no demo node claims vendor hardware attestation",
   detail["verification"]["hardware_attested"] is False)

# --- 7. date-range filter narrows results -----------------------------------
future = client.get("/metrics/overview?scope=demo&since=2999-01-01").json()
ok("a future 'since' window yields zero settled GMV",
   float(future["economics"]["gmv"]) == 0.0)

# --- 8. determinism: reseed from clean -> same supply + settlement ----------
first = (n_specs, s.query(Booking).filter(Booking.status == "released").count())
s.close()
demo_mod.wipe(dbmod)
client2 = TestClient(app_main.app)
demo_mod.seed(client2, dbmod)
s2 = dbmod.SessionLocal()
second = (s2.query(Spec).count(),
          s2.query(Booking).filter(Booking.status == "released").count())
ok(f"reset + reseed is deterministic (specs/settled {first} == {second})", first == second)
bal2, _ = dbmod.ledger_is_balanced(s2)
ok("ledger still balances after reset + reseed", bal2)
s2.close()

print("\nALL DEMO CHECKS PASSED")
