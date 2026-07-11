"""Payout rails as swappable adapters. USD is the unit of account; each provider
turns a USD payout into a real transfer. The STUB is used for tests/sandbox; the
real adapters are the seams to fill.

  gift_card -> Tremendous / Tango (BHN): POST an order for $amount to an email;
               recipient picks Amazon/Visa/PayPal/etc. Lightest compliance.
  usdc      -> Circle / Coinbase: send USDC on a low-fee chain (Base/Polygon/Solana)
               to a verified wallet; low fees, global.
  bank      -> Stripe Connect / Wise: ACH/SEPA to a bank account.

Before ANY send: KYC on the seller + OFAC/sanctions screening on the destination
(Persona/Sumsub + Chainalysis/TRM or the provider's built-in). Wire that into
`screen()` below.
"""
import os


def screen(method_kind: str, destination: str) -> bool:
    """Sanctions/AML screen the destination. STUB passes; wire a real screen here."""
    if os.getenv("PAYOUT_STUB", "").lower() == "true":
        return True
    # e.g. return chainalysis.screen(destination) / trm.screen(destination)
    return True


class PayoutProvider:
    def send(self, payout: dict) -> dict:
        raise NotImplementedError


# TODO(stub): simulated payouts — wire Tremendous/Circle/Stripe + real AML screen (stub.md #2)
class StubProvider(PayoutProvider):
    """Deterministic, no external calls. Confirms immediately."""
    def send(self, payout: dict) -> dict:
        return {"status": "confirmed", "ref": f"stub-{payout['kind']}-{payout['id']}"}


# --- functional adapters (real API calls; need credentials in env to run) ---
import httpx


class TremendousProvider(PayoutProvider):     # gift_card
    def send(self, payout: dict) -> dict:
        token = os.environ["TREMENDOUS_API_KEY"]
        base = os.getenv("TREMENDOUS_API", "https://api.tremendous.com/api/v2")
        r = httpx.post(f"{base}/orders", timeout=30,
                       headers={"Authorization": f"Bearer {token}",
                                "Content-Type": "application/json"},
                       json={"payment": {"funding_source_id": os.environ["TREMENDOUS_FUNDING_ID"]},
                             "reward": {"value": {"denomination": payout["amount_usd"],
                                                  "currency_code": "USD"},
                                        "delivery": {"method": "EMAIL"},
                                        "recipient": {"email": payout["destination"]},
                                        "products": [os.getenv("TREMENDOUS_PRODUCT_ID", "")]}})
        r.raise_for_status()
        return {"status": "confirmed", "ref": r.json().get("order", {}).get("id", "tremendous")}


class CircleUSDCProvider(PayoutProvider):     # usdc
    def send(self, payout: dict) -> dict:
        token = os.environ["CIRCLE_API_KEY"]
        base = os.getenv("CIRCLE_API", "https://api.circle.com/v1")
        import uuid as _u
        r = httpx.post(f"{base}/transfers", timeout=30,
                       headers={"Authorization": f"Bearer {token}",
                                "Content-Type": "application/json"},
                       json={"idempotencyKey": str(_u.uuid4()),
                             "source": {"type": "wallet",
                                        "id": os.environ["CIRCLE_WALLET_ID"]},
                             "destination": {"type": "blockchain",
                                             "chain": os.getenv("USDC_CHAIN", "MATIC"),
                                             "address": payout["destination"]},
                             "amount": {"amount": f'{payout["amount_usd"]:.2f}',
                                        "currency": "USD"}})
        r.raise_for_status()
        return {"status": "sent", "ref": r.json().get("data", {}).get("id", "circle")}


class StripeBankProvider(PayoutProvider):     # bank
    def send(self, payout: dict) -> dict:
        import stripe
        stripe.api_key = os.environ["STRIPE_API_KEY"]
        tr = stripe.Transfer.create(amount=int(round(payout["amount_usd"] * 100)),
                                    currency="usd", destination=payout["destination"])
        return {"status": "sent", "ref": tr.get("id", "stripe")}


def get_provider(kind: str) -> PayoutProvider:
    if os.getenv("PAYOUT_STUB", "").lower() == "true":
        return StubProvider()
    return {"gift_card": TremendousProvider, "usdc": CircleUSDCProvider,
            "bank": StripeBankProvider}.get(kind, StubProvider)()


def process_payouts(db, pending, set_status, methods_by_id, on_status=None) -> int:
    """Send each requested payout via its provider; mark confirmed or failed."""
    done = 0
    for p in pending:
        method = methods_by_id(p.method_id)
        if not method or not screen(p.kind, method.destination):
            set_status(db, p, "failed", reason="screening failed")
            if on_status:
                on_status(db, p, "failed", None, "screening failed")
            continue
        try:
            res = get_provider(p.kind).send(
                {"id": p.id, "kind": p.kind, "amount_usd": p.amount_usd,
                 "destination": method.destination})
            st = res.get("status", "sent")
            set_status(db, p, st, provider_ref=res.get("ref"))
            if on_status:
                on_status(db, p, st, res.get("ref"), None)
            done += 1
        except Exception as e:                              # noqa: BLE001
            set_status(db, p, "failed", reason=str(e)[:200])
            if on_status:
                on_status(db, p, "failed", None, str(e)[:200])
    return done
