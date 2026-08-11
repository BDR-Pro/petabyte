#!/usr/bin/env python3
"""verify_provisioning.py — prove the Petabyte dashboards are ACTUALLY provisioned.

The repo is the source of truth. This script exists because "Grafana /api/health is
healthy" does NOT mean the dashboards loaded — the classic failure is a Petabyte folder
that exists but is EMPTY. It runs in two complementary modes:

  STATIC (CI / local, offline) — from the committed JSON + compose + provider config:
    * discover every expected dashboard (uid, title) from observability/grafana/dashboards
    * reject malformed JSON, missing uid/title, duplicate uid, zero dashboards
    * assert the provider's options.path equals the compose bind-mount destination
      (so the files Grafana reads are the files we ship), and is NOT nested under the
      /var/lib/grafana named volume (which can mask them)
    * assert the provider folder is "Petabyte" and the provisioning dir is mounted

  LIVE (on the observability VM, against Grafana's local API) — with --grafana-url:
    * query Grafana and confirm EVERY expected uid exists AND lives in the Petabyte
      folder (folderUid 'petabyte'); confirm the folder itself exists with that uid
    * exit nonzero listing any missing/misfiled dashboard

Credentials (GRAFANA_VERIFY_USER/PASSWORD, else GF_SECURITY_ADMIN_USER/PASSWORD) come
from the environment and are NEVER printed. Only non-secret diagnostics are emitted.

Exit code is nonzero on ANY mismatch so a deploy can gate on it.

Usage:
  python verify_provisioning.py                          # static checks (default paths)
  python verify_provisioning.py --grafana-url http://127.0.0.1:3000   # + live checks
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DASH = os.path.join(HERE, "dashboards")
DEFAULT_COMPOSE = os.path.join(HERE, "..", "docker-compose.yml")
DEFAULT_PROVIDER = os.path.join(HERE, "provisioning", "dashboards", "petabyte.yaml")
EXPECTED_FOLDER = "Petabyte"
EXPECTED_FOLDER_UID = "petabyte"
# The canonical dashboards that MUST always be present (a floor on the auto-discovered set,
# so an accidental wipe of the JSON dir can't make "0 expected == 0 found" look healthy).
CANONICAL_UIDS = {
    "petabyte-executive", "petabyte-marketplace", "petabyte-settlement",
    "petabyte-seller-fleet", "petabyte-api", "petabyte-infra", "petabyte-security",
}


class VerifyError(Exception):
    pass


# --------------------------------------------------------------------------- source of truth
def expected_dashboards(dash_dir: str) -> dict:
    """{uid: {"title":..., "file":...}} discovered from committed JSON. Raises on any
    malformed/duplicate/missing-uid file, or if the canonical floor isn't met."""
    files = sorted(glob.glob(os.path.join(dash_dir, "*.json")))
    if not files:
        raise VerifyError(f"no dashboard JSON found in {dash_dir}")
    by_uid: dict = {}
    problems = []
    for f in files:
        name = os.path.basename(f)
        if os.path.getsize(f) == 0:
            problems.append(f"{name}: zero-byte file")
            continue
        try:
            d = json.load(open(f))
        except Exception as e:  # noqa: BLE001
            problems.append(f"{name}: invalid JSON: {e}")
            continue
        if "dashboard" in d and "panels" not in d:
            problems.append(f"{name}: looks like an API export wrapper "
                            "({{'dashboard':...}}) — provisioning needs the raw model")
            continue
        uid, title = d.get("uid"), d.get("title")
        if not uid:
            problems.append(f"{name}: missing uid")
            continue
        if not title:
            problems.append(f"{name}: missing title")
        if uid in by_uid:
            problems.append(f"{name}: duplicate uid '{uid}' (also {by_uid[uid]['file']})")
            continue
        by_uid[uid] = {"title": title, "file": name}
    if problems:
        raise VerifyError("committed dashboards are invalid:\n  - " + "\n  - ".join(problems))
    missing_canonical = CANONICAL_UIDS - set(by_uid)
    if missing_canonical:
        raise VerifyError(f"canonical dashboards missing from the repo: "
                          f"{sorted(missing_canonical)}")
    return by_uid


# --------------------------------------------------------------------------- static config
def _load_yaml(path: str):
    import yaml  # lazy: only CI/static mode needs it (VM live mode does not)
    with open(path) as f:
        return list(yaml.safe_load_all(f))


def provider_path_and_folder(provider_file: str):
    docs = _load_yaml(provider_file)
    prov = (docs[0] or {}).get("providers", []) if docs else []
    if not prov:
        raise VerifyError(f"{provider_file}: no providers defined")
    p = prov[0]
    return p.get("options", {}).get("path"), p.get("folder"), p.get("folderUid")


def compose_grafana_mounts(compose_file: str):
    docs = _load_yaml(compose_file)
    compose = docs[0] or {}
    g = (compose.get("services") or {}).get("grafana")
    if not g:
        raise VerifyError(f"{compose_file}: no grafana service")
    binds = {}                       # container_dest -> host_src (bind mounts only)
    named = set()                    # container_dest for named volumes
    for v in g.get("volumes", []):
        if not isinstance(v, str):
            continue
        parts = v.split(":")
        if len(parts) < 2:
            continue
        src, dest = parts[0], parts[1]
        if src.startswith("./") or src.startswith("/") or src.startswith("../"):
            binds[dest] = src
        else:
            named.add(dest)          # e.g. grafana-data:/var/lib/grafana
    return binds, named


def check_static(dash_dir, compose_file, provider_file):
    """Returns (expected_uids_dict, [problem strings])."""
    problems = []
    expected = expected_dashboards(dash_dir)       # raises on invalid JSON set
    path, folder, folder_uid = provider_path_and_folder(provider_file)
    binds, named = compose_grafana_mounts(compose_file)

    if folder != EXPECTED_FOLDER:
        problems.append(f"provider folder is {folder!r}, expected {EXPECTED_FOLDER!r}")
    if folder_uid != EXPECTED_FOLDER_UID:
        problems.append(f"provider folderUid is {folder_uid!r}, "
                        f"expected {EXPECTED_FOLDER_UID!r}")
    if not path:
        problems.append("provider options.path is empty")
    elif path not in binds:
        problems.append(f"provider path {path!r} is not a compose bind-mount destination "
                        f"(grafana bind mounts: {sorted(binds)})")
    # the dashboards path must not be nested under a named-volume mount (masking risk)
    for nv in named:
        if path and path != nv and path.startswith(nv.rstrip('/') + '/'):
            problems.append(f"provider path {path!r} is NESTED under named volume {nv!r} — "
                            "the volume can mask the dashboard files; mount them outside it")
    if "/etc/grafana/provisioning" not in binds:
        problems.append("compose does not bind-mount /etc/grafana/provisioning "
                        "(provider config would be absent in the container)")
    return expected, problems


# --------------------------------------------------------------------------- live Grafana
def _grafana_get(url, path, user, password, timeout=10):
    req = urllib.request.Request(url.rstrip("/") + path)
    if user is not None:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header("Authorization", "Basic " + token)   # never logged
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:  # noqa: BLE001  (connection refused etc.)
        return None, str(e)


def check_live(url, expected: dict):
    user = os.environ.get("GRAFANA_VERIFY_USER") or os.environ.get("GF_SECURITY_ADMIN_USER")
    password = (os.environ.get("GRAFANA_VERIFY_PASSWORD")
                or os.environ.get("GF_SECURITY_ADMIN_PASSWORD"))
    if not user or not password:
        raise VerifyError("live check needs GRAFANA_VERIFY_USER/PASSWORD "
                          "(or GF_SECURITY_ADMIN_USER/PASSWORD) in the environment")
    problems, observed = [], {}

    st, health = _grafana_get(url, "/api/health", user, password)
    if st != 200:
        raise VerifyError(f"Grafana API not reachable at {url} (/api/health -> {st})")

    # datasources must be provisioned — a dashboard whose datasource uid is missing renders
    # nothing, and the mandate gates success on datasource provisioning too.
    st, ds = _grafana_get(url, "/api/datasources", user, password)
    if st != 200 or not isinstance(ds, list):
        problems.append(f"datasources API returned status {st} (provisioning may have failed)")
    else:
        have = {d.get("uid") for d in ds}
        for need in ("prometheus", "loki", "tempo"):
            if need not in have:
                problems.append(f"datasource uid '{need}' is NOT provisioned")

    # folder must exist with the expected uid (catches a stale same-name folder, wrong uid)
    st, folder = _grafana_get(url, f"/api/folders/{EXPECTED_FOLDER_UID}", user, password)
    if st != 200 or not isinstance(folder, dict):
        problems.append(f"folder uid '{EXPECTED_FOLDER_UID}' not found via API (status {st}) — "
                        "a same-named folder with a different uid would cause this")
    elif folder.get("title") != EXPECTED_FOLDER:
        problems.append(f"folder '{EXPECTED_FOLDER_UID}' has title {folder.get('title')!r}, "
                        f"expected {EXPECTED_FOLDER!r}")

    for uid, meta in sorted(expected.items()):
        st, body = _grafana_get(url, f"/api/dashboards/uid/{uid}", user, password)
        if st != 200 or not isinstance(body, dict):
            problems.append(f"dashboard uid '{uid}' ({meta['title']}) NOT present (status {st})")
            continue
        m = body.get("meta", {})
        f_uid = m.get("folderUid")
        observed[uid] = m.get("folderTitle")
        if f_uid != EXPECTED_FOLDER_UID:
            problems.append(f"dashboard '{uid}' is in folder {m.get('folderTitle')!r} "
                            f"(uid {f_uid!r}), expected the {EXPECTED_FOLDER!r} folder")
    return observed, problems


# --------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dashboards-dir", default=DEFAULT_DASH)
    ap.add_argument("--compose", default=DEFAULT_COMPOSE)
    ap.add_argument("--provider", default=DEFAULT_PROVIDER)
    ap.add_argument("--grafana-url", default=os.environ.get("GRAFANA_URL"),
                    help="if set, ALSO verify the live Grafana has every dashboard")
    ap.add_argument("--skip-static-config", action="store_true",
                    help="only discover expected UIDs + do the live check (no yaml needed)")
    args = ap.parse_args(argv)

    fail = 0
    try:
        if args.skip_static_config:
            expected = expected_dashboards(args.dashboards_dir)
        else:
            expected, problems = check_static(args.dashboards_dir, args.compose, args.provider)
            for p in problems:
                print(f"FAIL  static: {p}")
            fail += len(problems)
    except VerifyError as e:
        print(f"FAIL  {e}")
        print("\n=== verify_provisioning: FAILED ===")
        return 1

    print(f"expected {len(expected)} dashboards from {os.path.relpath(args.dashboards_dir)}:")
    for uid, meta in sorted(expected.items()):
        print(f"  - {uid:28} {meta['title']}")

    if args.grafana_url:
        try:
            observed, problems = check_live(args.grafana_url, expected)
        except VerifyError as e:
            print(f"FAIL  live: {e}")
            print("\n=== verify_provisioning: FAILED ===")
            return 1
        for p in problems:
            print(f"FAIL  live: {p}")
        fail += len(problems)
        print(f"observed {len(observed)}/{len(expected)} expected dashboards present "
              f"in Grafana (folder '{EXPECTED_FOLDER}')")

    ok = fail == 0
    print(f"\n=== verify_provisioning: {'OK' if ok else str(fail) + ' FAILED'} ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
