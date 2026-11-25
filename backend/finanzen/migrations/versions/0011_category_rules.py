"""user-defined categorisation rules and more default spending categories

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

NEW_CATEGORIES = ["Lebensmittel & Drogerie", "Restaurant & Lieferdienst", "Einkaufen", "Bargeld"]


def upgrade() -> None:
    op.create_table(
        "category_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pattern", sa.String(120), nullable=False),
        sa.Column("field", sa.String(12), nullable=False, server_default="any"),
        sa.Column("direction", sa.String(3), nullable=False, server_default="any"),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort", sa.Integer, nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    conn = op.get_bind()
    sort = conn.execute(sa.text("SELECT coalesce(max(sort), 0) FROM categories WHERE kind = 'expense' AND sort < 1000")).scalar() or 0
    for i, name in enumerate(NEW_CATEGORIES):
        if not conn.execute(sa.text("SELECT count(*) FROM categories WHERE name = :n"), {"n": name}).scalar():
            conn.execute(sa.text("INSERT INTO categories (name, kind, sort) VALUES (:n, 'expense', :s)"), {"n": name, "s": sort + 1 + i})


def downgrade() -> None:
    op.drop_table("category_rules")
    conn = op.get_bind()
    for name in NEW_CATEGORIES:
        conn.execute(sa.text("DELETE FROM categories WHERE name = :n"), {"n": name})
