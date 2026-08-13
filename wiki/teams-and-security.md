# Teams & security

Everything for running Petabyte with other people, safely. All of this is in **Console → Teams** and
**Console → Access**.

## Teams (shared wallet + budget)

Share one wallet across a lab or company and set a hard **budget cap** so a runaway job can never
overspend.

- Create a team, add people, remove them when they leave.
- **Roles:**
  - **admin** — manage members, funds & budget, and run compute.
  - **billing** — add funds & set the budget, and run compute.
  - **member** — run compute against the team wallet.
- A team always keeps at least one admin (you can't demote the last one).
- Team spending draws from the team wallet within the budget cap.

## IAM / access control

Beyond team roles, **API keys** give programmatic access for CI, scripts and your own tools:

- Create a key with a **label**, an **expiry**, and optional **scopes**.
- The full key is shown **once** at creation — store it then.
- Revoke any key at any time. Product scopes matter: a **data** key can't call the compute API and
  vice-versa (see [API & keys](api.md)).

## Two-factor authentication (2FA)

Protect sign-in with a time-based one-time code (Google Authenticator, Authy, 1Password):

1. **Console → Access → Two-factor authentication → Set up.** Scan the QR / add the secret.
2. Confirm a code to enable. You're shown **backup codes once** — save them.
3. After that, login requires your password **and** a 6-digit code.

Disabling requires the password **and** a current code (or a backup code), so a stolen password
alone can't strip the second factor.

## Audit log (who did what, when)

Every security-relevant action — logins, key create/revoke, role & team changes, spend, 2FA changes
— is written to an **immutable, hash-chained** audit log. Any edit or deletion is detectable, which
is what a security team / SOC 2 needs.

- **Your own trail:** Console → Access → *Audit log*.
- **Team trail (admins):** in the team detail view.
- The log reports its **integrity** (whether the hash chain still verifies).

## Good hygiene

- Turn on 2FA.
- Give each integration its **own** scoped, expiring API key; revoke on rotation.
- Use a team with a **budget cap** for shared spend.
- Review the audit log periodically.
