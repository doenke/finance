"""mark credited interest on bank accounts as interest (it counts as return, not as a deposit)

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from finanzen.services.txkind import guess_kind

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, counterparty, purpose, amount FROM transactions WHERE kind = 'other' AND amount > 0")).all()
    ids = [r.id for r in rows if guess_kind(r.counterparty or "", r.purpose or "", r.amount) == "interest"]
    if ids:
        conn.execute(sa.text("UPDATE transactions SET kind = 'interest' WHERE id = ANY(:ids)"), {"ids": ids})


def downgrade() -> None:
    pass
