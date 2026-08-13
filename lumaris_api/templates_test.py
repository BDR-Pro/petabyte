"""templates_test.py — every launch template maps to a REAL, runnable Docker container.

No placeholders, no do-nothing tiles. Guards (pure, offline):
  * every template names a non-empty, anonymously-PULLABLE image (no NGC-gated nvcr.io that a
    stock seller node can't pull);
  * every template publishes a real service port (> 0) — no `-p 127.0.0.1:0:0` batch stubs in
    the one-click catalog;
  * a serving-LLM template that can't boot without a model carries a default_model so a bare
    one-click launch actually starts;
  * the removed do-nothing entries (pytorch base / ffmpeg / tensorrt-llm) stay gone;
  * the public catalog exposes exactly the runnable templates.

Run: python templates_test.py
"""
import templates_registry as tr

_fail = 0
_VALID_EGRESS = {"none", "limited", "open"}
# LLM-server templates that will NOT boot without a model must ship a default.
_NEEDS_MODEL = {"vllm"}
_REMOVED = {"pytorch", "ffmpeg", "tensorrt-llm"}


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


ok("there is at least one template", len(tr.TEMPLATES) >= 5)

for key, t in tr.TEMPLATES.items():
    img = t.get("image", "")
    ok(f"[{key}] names a Docker image", isinstance(img, str) and "/" in img and img.strip() != "")
    ok(f"[{key}] image is anonymously pullable (not NGC/nvcr.io-gated)", not img.startswith("nvcr.io/"))
    ok(f"[{key}] publishes a real service port (>0, no :0:0 stub)",
       isinstance(t.get("port"), int) and t["port"] > 0)
    ok(f"[{key}] declares a valid egress policy", t.get("egress") in _VALID_EGRESS)
    ok(f"[{key}] declares a gpu boolean", isinstance(t.get("gpu"), bool))
    if key in _NEEDS_MODEL:
        ok(f"[{key}] ships a default_model so a bare launch boots",
           bool(t.get("default_model")))

# no do-nothing placeholders survive
for k in _REMOVED:
    ok(f"removed placeholder template '{k}' is gone", k not in tr.TEMPLATES)

# public catalog matches the runnable templates 1:1
cat = tr.public_catalog()
ok("public_catalog exposes exactly the runnable templates",
   {c["name"] for c in cat} == set(tr.TEMPLATES) and len(cat) == len(tr.TEMPLATES))
ok("every catalog entry carries a real port + egress",
   all(c["port"] > 0 and c["egress"] in _VALID_EGRESS for c in cat))

print(f"\n=== templates: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
