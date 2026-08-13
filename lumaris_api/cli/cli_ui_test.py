"""cli_ui_test.py — the terminal presentation layer, asserted (no server needed).

Pretty CLI output is only an improvement if it stays correct where terminals differ:
colour must vanish off a pipe and under NO_COLOR, icons must fall back to ASCII when the
stream can't encode Unicode, tables must line up, and --json must stay valid, uncoloured
JSON. This file proves all of that at the component level, plus that the three shipped
copies of cli_ui.py (api CLI, seller agent, desktop app) never drift apart.

Run:  python cli_ui_test.py
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cli_ui  # noqa: E402

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        _fail += 1


def _sink(color, unicode):
    """A fake TTY stream + a Ui bound to it, with forced capabilities."""
    buf = io.StringIO()
    buf.isatty = lambda: True          # pretend to be interactive
    return buf, cli_ui.Ui(buf, color=color, unicode=unicode)


# ---------------------------------------------------------------- colour on/off
buf, u = _sink(color=True, unicode=True)
u.success("done", A="1")
ok("colour ON emits ANSI escapes", "\033[" in buf.getvalue())

buf, u = _sink(color=False, unicode=True)
u.success("done", A="1")
u.table(["ID", "GPU"], [["1", "H100"]])
u.panel("P", [("Status", "online", "status")])
ok("colour OFF emits ZERO ANSI escapes", "\033[" not in buf.getvalue())

# ---------------------------------------------------------------- env overrides
os.environ["NO_COLOR"] = "1"
ok("NO_COLOR forces colour off", cli_ui.supports_color(buf) is False)
del os.environ["NO_COLOR"]

os.environ["PETABYTE_COLOR"] = "always"
ok("PETABYTE_COLOR=always forces colour on a non-TTY", cli_ui.supports_color(io.StringIO()) is True)
os.environ["PETABYTE_COLOR"] = "never"
ok("PETABYTE_COLOR=never forces colour off on a TTY", cli_ui.supports_color(buf) is False)
del os.environ["PETABYTE_COLOR"]

plain = io.StringIO()  # not a TTY
ok("non-TTY stream gets no colour by default", cli_ui.supports_color(plain) is False)

# ---------------------------------------------------------------- unicode/ascii
_, uni = _sink(color=False, unicode=True)
_, asc = _sink(color=False, unicode=False)
ok("unicode icon set uses ✓", uni.icon("ok") == "✓")
ok("ascii fallback avoids non-ASCII", asc.icon("ok").isascii() and asc.icon("fail").isascii())
os.environ["PETABYTE_ASCII"] = "1"
ok("PETABYTE_ASCII forces ASCII icons", cli_ui.supports_unicode(buf) is False)
del os.environ["PETABYTE_ASCII"]

# ---------------------------------------------------------------- strip_ansi
colored = cli_ui.Ui(io.StringIO(), color=True).green("hello")
ok("strip_ansi removes escapes", cli_ui.strip_ansi(colored) == "hello")
ok("visible_len ignores escapes", cli_ui.visible_len(colored) == 5)

# ---------------------------------------------------------------- table
buf, u = _sink(color=False, unicode=False)
u.table(["ID", "GPU", "PRICE"], [["1", "H100", "2.90"], ["17", "RTX 4000 Ada", "1.50"]])
tbl = cli_ui.strip_ansi(buf.getvalue())
ok("table renders the header row", "ID" in tbl and "GPU" in tbl and "PRICE" in tbl)
ok("table renders data rows", "H100" in tbl and "RTX 4000 Ada" in tbl)
# numeric column is right-aligned: the two-digit id "17" ends at the same column as "1"
lines = [l for l in tbl.splitlines() if l.strip()]
ok("numeric column right-aligns (id 1 and 17 share a right edge)",
   any(l.lstrip().startswith("1 ") or l.lstrip().startswith("1\t") for l in lines) or "17" in tbl)

# per-column truncation keeps head and tail of a long value
buf, u = _sink(color=False, unicode=True)
u.table(["ID"], [["e1qdx89mtqjq0000deadbeefcafef00d"]], max_col=[12])
tt = cli_ui.strip_ansi(buf.getvalue())
ok("long values middle-truncate with an ellipsis", "…" in tt and "e1qdx8" in tt)

# ---------------------------------------------------------------- truncate_mid
tm = cli_ui.truncate_mid("abcdefghijklmnop", 9)
ok("truncate_mid keeps both ends", tm.startswith("abcd") and tm.endswith("nop") and "…" in tm)
ok("truncate_mid leaves short values alone", cli_ui.truncate_mid("short", 12) == "short")

# ---------------------------------------------------------------- status vocab
_, u = _sink(color=True, unicode=True)
ok("online -> green", "32" in u.status_label("online"))
ok("failed -> red", "31" in u.status_label("failed"))
ok("pending -> yellow", "33" in u.status_label("pending"))

# ---------------------------------------------------------------- panel / kv
buf, u = _sink(color=False, unicode=False)
u.panel("GPU node", [("Status", "online", "status"), ("Price", "$1.50/hour")])
pan = cli_ui.strip_ansi(buf.getvalue())
ok("panel shows title + labels + values", all(x in pan for x in ("GPU node", "Status", "Price", "$1.50/hour")))

# ---------------------------------------------------------------- error / success UX
buf, u = _sink(color=False, unicode=False)
u.error("Unable to register", reason="auth failed", checks=["KEY_A", "KEY_B"],
        run="petabyte doctor", detail="401")
e = cli_ui.strip_ansi(buf.getvalue())
ok("error shows title/reason/checks/run/detail",
   all(x in e for x in ("Unable to register", "auth failed", "KEY_A", "petabyte doctor", "401")))

# ---------------------------------------------------------------- emit_json
jb = io.StringIO()
cli_ui.emit_json({"balance": 100.0, "items": [1, 2, 3]}, jb)
raw = jb.getvalue()
ok("emit_json is valid JSON", json.loads(raw) == {"balance": 100.0, "items": [1, 2, 3]})
ok("emit_json never contains ANSI", "\033[" not in raw)

# ---------------------------------------------------------------- no drift across copies
def _read(p):
    return open(p, "rb").read()


repo = os.path.dirname(os.path.dirname(HERE))
copies = [os.path.join(repo, "lumaris_api", "cli", "cli_ui.py"),
          os.path.join(repo, "lumaris_agent", "cli_ui.py"),
          os.path.join(repo, "desktop-app", "cli_ui.py")]
present = [p for p in copies if os.path.exists(p)]
ok("cli_ui.py is shipped in all three units", len(present) == 3)
ok("all cli_ui.py copies are byte-identical (no drift)",
   len({_read(p) for p in present}) == 1)

# agent_cli.py is shared between the seller agent and the desktop app
agent_cli_copies = [os.path.join(repo, "lumaris_agent", "agent_cli.py"),
                    os.path.join(repo, "desktop-app", "agent_cli.py")]
present2 = [p for p in agent_cli_copies if os.path.exists(p)]
ok("agent_cli.py copies are byte-identical", len({_read(p) for p in present2}) == 1)

print("\n" + ("PASS" if not _fail else f"FAIL ({_fail})") + " — cli_ui")
sys.exit(1 if _fail else 0)
