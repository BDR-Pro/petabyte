#!/usr/bin/env python3
"""Attest this node at POST /prove using the agent's signing identity.

Run once after registering a spec, before serving jobs:
  PETABYTE_API_URL=... PETABYTE_API_JWT=<seller JWT> SPEC_ID=<id> python attest_node.py
"""
import os, time, base64, httpx, crypto


def main():
    api_url = os.environ["PETABYTE_API_URL"]
    jwt = os.environ["PETABYTE_API_JWT"]      # seller JWT (owner of the spec)
    spec_id = int(os.environ["SPEC_ID"])
    att = {"node": "petabyte-agent", "nonce": base64.b64encode(os.urandom(9)).decode(),
           "ts": int(time.time())}
    r = httpx.post(f"{api_url}/prove", headers={"Authorization": f"Bearer {jwt}"},
                   json={"spec_id": spec_id, "attestation": att,
                         "signature": crypto.sign_proof(att),
                         "pubkey": crypto.public_key_b64()}, timeout=15)
    print(r.status_code, r.text)


if __name__ == "__main__":
    main()
