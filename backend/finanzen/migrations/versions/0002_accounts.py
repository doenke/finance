"""accounts, owners, balances, transactions, instruments, prices, trades, valuations

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(18, 2)


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("asset_class", sa.String(30), nullable=False),
        sa.Column("institution", sa.String(120), nullable=False, server_default=""),
        sa.Column("iban", sa.String(34), nullable=False, server_default=""),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("opened_on", sa.Date(), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("details", JSONB(), nullable=False, server_default="{}"),
        sa.Column("settlement_account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "account_owners",
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("persons.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("share", sa.Numeric(7, 6), nullable=False),
    )
    op.create_table(
        "balances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.UniqueConstraint("account_id", "date"),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("booking_date", sa.Date(), nullable=False, index=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="other"),
        sa.Column("counterparty", sa.String(255), nullable=False, server_default=""),
        sa.Column("purpose", sa.Text(), nullable=False, server_default=""),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("transfer_account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("import_batch_id", sa.Integer(), nullable=True),
        sa.Column("raw", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_transactions_external", "transactions", ["account_id", "external_id"])
    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("isin", sa.String(12), nullable=True, unique=True),
        sa.Column("wkn", sa.String(6), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("unit", sa.String(10), nullable=False, server_default="piece"),
        sa.Column("price_source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("price_symbol", sa.String(40), nullable=True),
        sa.Column("details", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(24, 10), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.UniqueConstraint("instrument_id", "date"),
    )
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=True, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("price", sa.Numeric(24, 10), nullable=True),
        sa.Column("amount", MONEY, nullable=False, server_default="0"),
        sa.Column("fees", MONEY, nullable=False, server_default="0"),
        sa.Column("taxes", MONEY, nullable=False, server_default="0"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("import_batch_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "valuations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", MONEY, nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("account_id", "date"),
    )


def downgrade() -> None:
    for table in ["valuations", "trades", "prices", "instruments", "transactions", "balances", "account_owners", "accounts"]:
        op.drop_table(table)
