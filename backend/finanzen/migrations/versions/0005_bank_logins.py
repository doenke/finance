"""bank logins (FinTS)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bank_logins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("blz", sa.String(8), nullable=False),
        sa.Column("server_url", sa.String(255), nullable=False),
        sa.Column("username", sa.String(120), nullable=False),
        sa.Column("customer_id", sa.String(120), nullable=False, server_default=""),
        sa.Column("tan_mechanism", sa.String(10), nullable=True),
        sa.Column("tan_mechanism_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("tan_medium", sa.String(120), nullable=True),
        sa.Column("store_pin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pin_encrypted", sa.Text(), nullable=True),
        sa.Column("client_state", sa.Text(), nullable=True),
        sa.Column("auto_sync", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("needs_tan", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("accounts", sa.Column("bank_login_id", sa.Integer(), sa.ForeignKey("bank_logins.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "bank_login_id")
    op.drop_table("bank_logins")
