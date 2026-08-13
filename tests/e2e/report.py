"""report.py — collect E2E results into a human-readable artifacts/e2e_browser_report.txt.

The report is the whole point of this suite: the operator does not run tests by hand — CI
does — and pastes this .txt back to Claude/ChatGPT when something fails. It must be readable,
secret-free, and generated even when tests fail. Populated from pytest outcomes (via the
conftest hook) + UX counters/bugs recorded by helpers.
"""
import os

ARTIFACTS = os.path.join(os.getcwd(), "artifacts")
REPORT_TXT = os.path.join(ARTIFACTS, "e2e_browser_report.txt")

# canonical section order in the report
SECTIONS = ["PERSONAS", "AUTHORIZATION", "WALLET", "UX/UI"]


class Reporter:
    def __init__(self):
        self.results = []          # {section, label, status in pass/fail/skip}
        self.bugs = []             # {id, page, severity, problem, evidence}
        self.counters = {"console_errors": 0, "failed_requests": 0, "overflow_failures": 0}
        self.meta = {"target": os.environ.get("E2E_BASE_URL", "https://test.petabyte.market"),
                     "commit": os.environ.get("GITHUB_SHA", os.environ.get("E2E_COMMIT", "local"))}

    # ---- recording -------------------------------------------------------------------
    def record(self, section, label, status):
        self.results.append({"section": section, "label": label, "status": status})

    def bug(self, page, severity, problem, evidence=""):
        bid = f"BUG-{len(self.bugs) + 1:03d}"
        self.bugs.append({"id": bid, "page": page, "severity": severity,
                          "problem": problem, "evidence": evidence})
        return bid

    def bump(self, counter, n=1):
        if counter in self.counters:
            self.counters[counter] += n

    # ---- rollups ---------------------------------------------------------------------
    def _by_section(self):
        out = {s: {} for s in SECTIONS}
        for r in self.results:
            sec = r["section"] if r["section"] in out else "UX/UI"
            cur = out[sec].get(r["label"])
            # a label is FAIL if any of its checks failed; else PASS if any passed; else SKIP
            order = {"fail": 2, "pass": 1, "skip": 0}
            if cur is None or order[r["status"]] > order[cur]:
                out[sec][r["label"]] = r["status"]
        return out

    def totals(self):
        t = {"pass": 0, "fail": 0, "skip": 0}
        for r in self.results:
            t[r["status"]] = t.get(r["status"], 0) + 1
        return t

    def overall(self):
        return "FAIL" if any(r["status"] == "fail" for r in self.results) else "PASS"

    # ---- render ----------------------------------------------------------------------
    def render(self):
        t = self.totals()
        L = []
        add = L.append
        bar = "=" * 50
        add(bar); add("PETABYTE BROWSER E2E REPORT"); add(bar); add("")
        add(f"Target:\n{self.meta['target']}\n")
        add(f"Commit:\n{self.meta['commit']}\n")
        add(f"Overall:\n{self.overall()}\n")
        add("Tests:")
        add(f"Passed: {t['pass']}")
        add(f"Failed: {t['fail']}")
        add(f"Skipped: {t['skip']}")
        add("")
        by = self._by_section()
        for sec in SECTIONS:
            add(sec)
            if not by[sec]:
                add("  (none run)")
            for label, status in by[sec].items():
                add(f"{label}:\n{status.upper()}")
            add("")
        add("UX SIGNALS")
        add(f"Console errors: {self.counters['console_errors']}")
        add(f"Critical failed browser requests: {self.counters['failed_requests']}")
        add(f"Horizontal overflow failures: {self.counters['overflow_failures']}")
        add("")
        add("BUGS FOUND")
        if not self.bugs:
            add("  (none)")
        for b in self.bugs:
            add("")
            add(b["id"])
            add(f"Page:\n{b['page']}")
            add(f"Severity:\n{b['severity']}")
            add(f"Problem:\n{b['problem']}")
            if b["evidence"]:
                add(f"Evidence:\n{b['evidence']}")
        add(""); add(bar)
        return "\n".join(L) + "\n"

    def write(self):
        os.makedirs(ARTIFACTS, exist_ok=True)
        text = self.render()
        with open(REPORT_TXT, "w", encoding="utf-8") as f:
            f.write(text)
        return text


REPORT = Reporter()
