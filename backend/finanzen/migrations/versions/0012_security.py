"""server-side sessions, locked users and the audit log

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("disabled", sa.Boolean, nullable=False, server_default=sa.false()))
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_agent", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("actor", sa.String(255), nullable=False, server_default=""),
        sa.Column("via", sa.String(10), nullable=False, server_default="app"),
        sa.Column("client", sa.String(200), nullable=False, server_default=""),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("target", sa.String(255), nullable=False, server_default=""),
        sa.Column("detail", sa.String(500), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("sessions")
    op.drop_column("users", "disabled")
