#!/usr/bin/env python3
"""verify_provisioning_test.py — regression guard for the Grafana provisioning chain.

Covers the exact failure that left the Petabyte folder empty and the invariants that keep it
from recurring, using structured JSON/YAML parsing (never brittle text greps):

  * committed dashboards are found; count > 0; every JSON parses; each has uid + title; uids unique
  * the canonical dashboards are present
  * provider options.path == a compose bind-mount destination (Grafana reads what we ship)
  * provider path is NOT nested under the /var/lib/grafana named volume (the masking bug)
  * provider folder is Petabyte
  * compose bind-mounts BOTH the dashboards dir and the provisioning dir
  * the deploy workflow syncs the whole observability/ tree and self-verifies provisioning
  * live verification refuses zero dashboards, detects a missing UID, a wrong folder, and a
    missing datasource (mismatch => nonzero)

Run: python observability/grafana/verify_provisioning_test.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import verify_provisioning as vp   # noqa: E402
import yaml                        # noqa: E402

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def raises(fn):
    try:
        fn()
        return False
    except vp.VerifyError:
        return True


# ------------------------------------------------------------------ committed source of truth
exp = vp.expected_dashboards(vp.DEFAULT_DASH)
ok("committed dashboards are discovered", len(exp) > 0)
ok("expected dashboard count is sensible (>= canonical 7)", len(exp) >= 7)
ok("every dashboard has a uid and a title",
   all(u and m.get("title") for u, m in exp.items()))
ok("uids are unique (dict keys) and match file count",
   len(exp) == len([f for f in os.listdir(vp.DEFAULT_DASH) if f.endswith(".json")]))
ok("all canonical dashboards are present", vp.CANONICAL_UIDS <= set(exp))


def _tmp_dashdir(files):
    d = tempfile.mkdtemp(prefix="dash_")
    for name, obj in files.items():
        with open(os.path.join(d, name), "w") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))
    return d


ok("empty dashboards dir is REJECTED (refuses zero dashboards)",
   raises(lambda: vp.expected_dashboards(_tmp_dashdir({}))))
ok("malformed JSON is REJECTED",
   raises(lambda: vp.expected_dashboards(_tmp_dashdir({"bad.json": "{not json"}))))
ok("a dashboard missing its uid is REJECTED",
   raises(lambda: vp.expected_dashboards(_tmp_dashdir({"x.json": {"title": "t", "panels": []}}))))
ok("duplicate uids are REJECTED", raises(lambda: vp.expected_dashboards(_tmp_dashdir({
    "a.json": {"uid": "dup", "title": "A", "panels": []},
    "b.json": {"uid": "dup", "title": "B", "panels": []}}))))
ok("an API-export wrapper ({'dashboard':...}) is REJECTED",
   raises(lambda: vp.expected_dashboards(_tmp_dashdir(
       {"w.json": {"dashboard": {"uid": "w", "title": "W"}, "meta": {}}}))))


# ------------------------------------------------------------------ provider <-> compose (real)
_exp, problems = vp.check_static(vp.DEFAULT_DASH, vp.DEFAULT_COMPOSE, vp.DEFAULT_PROVIDER)
ok("real repo passes static config verification (no problems)", problems == [], )
if problems:
    for p in problems:
        print("     problem:", p)

path, folder, folder_uid = vp.provider_path_and_folder(vp.DEFAULT_PROVIDER)
binds, named = vp.compose_grafana_mounts(vp.DEFAULT_COMPOSE)
ok("provider folder is Petabyte", folder == "Petabyte")
ok("provider path is a compose bind-mount destination", path in binds)
ok("compose bind-mounts the provisioning dir", "/etc/grafana/provisioning" in binds)
ok("provider path is NOT nested under a named volume (masking guard)",
   not any(path != nv and path.startswith(nv.rstrip('/') + '/') for nv in named))


# ------------------------------------------------------------------ the guard catches the OLD bug
_bad_compose = tempfile.mktemp(suffix=".yml")
with open(_bad_compose, "w") as f:
    yaml.safe_dump({"services": {"grafana": {"volumes": [
        "./grafana/provisioning:/etc/grafana/provisioning:ro",
        "./grafana/dashboards:/var/lib/grafana/dashboards:ro",   # nested under the named vol
        "grafana-data:/var/lib/grafana",
    ]}}}, f)
_bad_provider = tempfile.mktemp(suffix=".yaml")
with open(_bad_provider, "w") as f:
    yaml.safe_dump({"apiVersion": 1, "providers": [
        {"name": "petabyte", "folder": "Petabyte", "folderUid": "petabyte", "type": "file",
         "options": {"path": "/var/lib/grafana/dashboards"}}]}, f)
_e, bad_problems = vp.check_static(vp.DEFAULT_DASH, _bad_compose, _bad_provider)
ok("static verification DETECTS the nested-under-named-volume masking bug",
   any("NESTED under named volume" in p for p in bad_problems))


# ------------------------------------------------------------------ deploy workflow structure
WF = os.path.join(REPO, ".github", "workflows", "deploy-observability.yml")
wf = yaml.safe_load(open(WF))
jobs = wf["jobs"]
val_steps = jobs["validate"]["steps"]
dep_steps = jobs["deploy"]["steps"]


def _step_runs(steps):
    return "\n".join(s.get("run", "") for s in steps)


ok("validate job runs static provisioning verification",
   "verify_provisioning.py" in _step_runs(val_steps))
rsync = _step_runs(dep_steps)
ok("deploy rsyncs the WHOLE observability/ tree to the remote dir",
   "observability/" in rsync and "$REMOTE_DIR/" in rsync)
ok("deploy runs the LIVE provisioning verification (not just /api/health)",
   "verify_provisioning.py" in rsync and "--grafana-url" in rsync)
ok("deploy force-recreates grafana so mount changes apply (not just restart)",
   "--force-recreate grafana" in rsync)
ok("deploy summary is gated on job success (no unconditional 'auto-provisioned' claim)",
   "job.status" in _step_runs([s for s in dep_steps if "summary" in (s.get('name', '').lower())]))


# ------------------------------------------------------------------ live check (fake Grafana)
os.environ["GF_SECURITY_ADMIN_USER"] = "admin"
os.environ["GF_SECURITY_ADMIN_PASSWORD"] = "x"        # never used against a real server here
_real_get = vp._grafana_get


def fake_grafana(present_uids, folder_uid="petabyte", datasources=("prometheus", "loki", "tempo")):
    def _get(url, path, user, password, timeout=10):
        if path == "/api/health":
            return 200, {"database": "ok"}
        if path == "/api/datasources":
            return 200, [{"uid": u} for u in datasources]
        if path.startswith("/api/folders/"):
            return 200, {"uid": "petabyte", "title": "Petabyte"}
        if path.startswith("/api/dashboards/uid/"):
            uid = path.rsplit("/", 1)[-1]
            if uid in present_uids:
                return 200, {"meta": {"folderUid": folder_uid, "folderTitle": "Petabyte"}}
            return 404, None
        return 404, None
    return _get


try:
    all_uids = set(exp)
    vp._grafana_get = fake_grafana(all_uids)
    _obs, live_ok = vp.check_live("http://x", exp)
    ok("live check PASSES when every dashboard is present", live_ok == [])

    vp._grafana_get = fake_grafana(all_uids - {"petabyte-executive"})
    _obs, live_missing = vp.check_live("http://x", exp)
    ok("live check DETECTS a missing expected UID",
       any("petabyte-executive" in p and "NOT present" in p for p in live_missing))

    vp._grafana_get = fake_grafana(all_uids, folder_uid="some-other-folder")
    _obs, live_folder = vp.check_live("http://x", exp)
    ok("live check DETECTS a dashboard filed under the WRONG folder",
       any("expected the 'Petabyte' folder" in p for p in live_folder))

    vp._grafana_get = fake_grafana(all_uids, datasources=("prometheus", "loki"))
    _obs, live_ds = vp.check_live("http://x", exp)
    ok("live check DETECTS a missing datasource",
       any("datasource uid 'tempo' is NOT provisioned" in p for p in live_ds))
finally:
    vp._grafana_get = _real_get


print(f"\n=== verify_provisioning_test: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
