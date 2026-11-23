"""categories and recurring payments

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

DEFAULT_CATEGORIES = [
    ("Wohnen & Nebenkosten", "expense"),
    ("Energie & Wasser", "expense"),
    ("Versicherungen", "expense"),
    ("Kredit & Finanzierung", "expense"),
    ("Telefon & Internet", "expense"),
    ("Abos & Medien", "expense"),
    ("Mobilität", "expense"),
    ("Gesundheit & Fitness", "expense"),
    ("Kinder & Familie", "expense"),
    ("Vereine & Spenden", "expense"),
    ("Steuern & Gebühren", "expense"),
    ("Sonstige Ausgaben", "expense"),
    ("Gehalt & Lohn", "income"),
    ("Zinsen & Dividenden", "income"),
    ("Kindergeld & Zuschüsse", "income"),
    ("Mieteinnahmen", "income"),
    ("Sonstige Einnahmen", "income"),
    ("Sparen & Umbuchungen", "transfer"),
]


def upgrade() -> None:
    categories = op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False, server_default="expense"),
        sa.Column("sort", sa.Integer, nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.bulk_insert(categories, [{"name": n, "kind": k, "sort": i * 10} for i, (n, k) in enumerate(DEFAULT_CATEGORIES)])
    op.create_table(
        "recurring_payments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("match_key", sa.String(200), nullable=False, index=True),
        sa.Column("direction", sa.String(3), nullable=False),
        sa.Column("amount_min", sa.Numeric(18, 2), nullable=True),
        sa.Column("amount_max", sa.Numeric(18, 2), nullable=True),
        sa.Column("interval", sa.String(12), nullable=False),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # Transactions had a placeholder category column; categories exist now.
    op.execute("UPDATE transactions SET category_id = NULL")
    op.create_foreign_key("transactions_category_id_fkey", "transactions", "categories", ["category_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_transactions_category_id", "transactions", ["category_id"])


def downgrade() -> None:
    op.drop_index("ix_transactions_category_id", "transactions")
    op.drop_constraint("transactions_category_id_fkey", "transactions", type_="foreignkey")
    op.drop_table("recurring_payments")
    op.drop_table("categories")
