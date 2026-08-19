"""legacy type hygiene — exact fx_rate + prunable revocation denylist

Two changes for databases that PREDATE the current models:

  * ``payout_batches.fx_rate`` was ``Float`` in earlier models. Money-adjacent values must be
    exact, so legacy columns are converted to ``Numeric(20, 8)`` (the current model type).
    ``init_db``'s ``_ensure_columns`` adds missing columns but never alters existing types,
    so without this revision a pre-split database keeps float FX rates forever.
  * ``revoked_api_keys.expires_at`` records the revoked token's own expiry so maintenance can
    prune rows that no longer protect anything (the denylist is checked on every
    authenticated request).

``0001_baseline`` builds the CURRENT models (init_db), so a fresh database already has both —
every operation below is inspector-guarded and only fires on a legacy database. That guard is
REQUIRED while the baseline is dynamic: an unconditional add/alter would collide with what the
baseline just created.

Revision ID: 0002_type_hygiene
Revises: 0001_baseline
Create Date: 2026-08-19
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_type_hygiene"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _fx_column(insp):
    for c in insp.get_columns("payout_batches"):
        if c["name"] == "fx_rate":
            return c
    return None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    fx = _fx_column(insp)
    # sa.Float subclasses sa.Numeric, so test for the FLOAT family explicitly.
    if fx is not None and isinstance(fx["type"], sa.Float):
        with op.batch_alter_table("payout_batches") as batch:
            batch.alter_column("fx_rate", type_=sa.Numeric(20, 8),
                               existing_type=fx["type"],
                               existing_nullable=fx.get("nullable", True))

    rcols = {c["name"] for c in insp.get_columns("revoked_api_keys")}
    if "expires_at" not in rcols:
        op.add_column("revoked_api_keys", sa.Column("expires_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())

    fx = _fx_column(insp)
    if fx is not None and isinstance(fx["type"], sa.Numeric) and not isinstance(fx["type"], sa.Float):
        with op.batch_alter_table("payout_batches") as batch:
            batch.alter_column("fx_rate", type_=sa.Float(),
                               existing_type=fx["type"],
                               existing_nullable=fx.get("nullable", True))

    rcols = {c["name"] for c in insp.get_columns("revoked_api_keys")}
    if "expires_at" in rcols:
        op.drop_column("revoked_api_keys", "expires_at")
