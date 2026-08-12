"""affiliates.py — partner links shown in the ROI calculator's "gear & tools" section.

Beyond the per-GPU buy links (hardware_reference.py), sellers spend money on adjacent things:
cloud storage for datasets/outputs, an exchange to cash out USDC, a parts planner, power/backup.
Each partner here is a PLAIN, genuinely-useful link by default; when the founder pastes their
affiliate/referral URL into that partner's env var, the monetised link is used instead and a
commission may be earned (FTC disclosure is shown on the page). Nothing is monetised until
configured, so the feature degrades honestly — same principle as the hardware buy links.
"""
import os

# key, name, category, blurb, env (holds the founder's affiliate/referral URL), default plain URL
PARTNERS = [
    {"key": "backblaze", "name": "Backblaze B2", "category": "Cloud storage",
     "env": "AFFILIATE_BACKBLAZE_URL", "default_url": "https://www.backblaze.com/cloud-storage",
     "blurb": "Cheap S3-compatible storage for datasets and job outputs."},
    {"key": "wasabi", "name": "Wasabi", "category": "Cloud storage",
     "env": "AFFILIATE_WASABI_URL", "default_url": "https://wasabi.com/",
     "blurb": "Flat-rate hot storage with no egress fees."},
    {"key": "coinbase", "name": "Coinbase", "category": "Cash out USDC",
     "env": "AFFILIATE_COINBASE_URL", "default_url": "https://www.coinbase.com/",
     "blurb": "Convert USDC payouts to your bank."},
    {"key": "pcpartpicker", "name": "PCPartPicker", "category": "Plan your build",
     "env": "AFFILIATE_PCPARTPICKER_URL", "default_url": "https://pcpartpicker.com/",
     "blurb": "Spec a compatible rig and compare part prices."},
    {"key": "ecoflow", "name": "EcoFlow", "category": "Power & backup",
     "env": "AFFILIATE_ECOFLOW_URL", "default_url": "https://www.ecoflow.com/",
     "blurb": "Solar generators and battery backup to cut or hedge your power bill."},
]


def partners():
    """Resolved partner list. Each entry uses the configured affiliate URL when its env var is
    set, otherwise the plain default; `affiliate` says which happened."""
    out = []
    for p in PARTNERS:
        url = (os.getenv(p["env"], "") or "").strip()
        out.append({
            "key": p["key"], "name": p["name"], "category": p["category"],
            "blurb": p["blurb"], "url": url or p["default_url"], "affiliate": bool(url),
        })
    return out


def any_affiliate():
    return any(p["affiliate"] for p in partners())
