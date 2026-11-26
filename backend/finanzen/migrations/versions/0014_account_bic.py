"""BIC as master data of an account (needed for FinTS)

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("bic", sa.String(11), nullable=False, server_default=""))
    # take over BICs the bank sync already remembered
    op.execute("UPDATE accounts SET bic = UPPER(details->'fints'->>'bic') WHERE COALESCE(details->'fints'->>'bic', '') <> ''")


def downgrade() -> None:
    op.drop_column("accounts", "bic")
