"""fx rates and app state

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fx_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("currency", sa.String(3), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.UniqueConstraint("currency", "date"),
    )
    op.create_table(
        "app_state",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("app_state")
    op.drop_table("fx_rates")
