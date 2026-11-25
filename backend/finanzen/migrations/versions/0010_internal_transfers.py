"""split "Sparen & Umbuchungen" into savings and internal transfers (not counted)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE categories SET name = 'Sparen & Anlegen' WHERE name = 'Sparen & Umbuchungen' AND kind = 'transfer'"))
    exists = conn.execute(sa.text("SELECT count(*) FROM categories WHERE kind = 'internal'")).scalar()
    if not exists:
        sort = conn.execute(sa.text("SELECT coalesce(max(sort), 0) + 10 FROM categories WHERE sort < 1000")).scalar()
        conn.execute(sa.text("INSERT INTO categories (name, kind, sort) VALUES ('Umbuchungen', 'internal', :s)"), {"s": sort})


def downgrade() -> None:
    conn = op.get_bind()
    internal = conn.execute(sa.text("SELECT id FROM categories WHERE kind = 'internal' ORDER BY id LIMIT 1")).scalar()
    savings = conn.execute(sa.text("SELECT id FROM categories WHERE name = 'Sparen & Anlegen' AND kind = 'transfer'")).scalar()
    if internal and savings:
        conn.execute(sa.text("UPDATE recurring_payments SET category_id = :s WHERE category_id = :i"), {"s": savings, "i": internal})
        conn.execute(sa.text("UPDATE transactions SET category_id = :s WHERE category_id = :i"), {"s": savings, "i": internal})
    conn.execute(sa.text("DELETE FROM categories WHERE kind = 'internal'"))
    conn.execute(sa.text("UPDATE categories SET name = 'Sparen & Umbuchungen' WHERE name = 'Sparen & Anlegen' AND kind = 'transfer'"))
