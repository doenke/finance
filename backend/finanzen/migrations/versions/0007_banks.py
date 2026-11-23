"""split bank logins into shared banks and personal logins

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "banks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("blz", sa.String(8), nullable=False),
        sa.Column("server_url", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("bank_logins", sa.Column("bank_id", sa.Integer, nullable=True))
    op.add_column("bank_logins", sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    conn = op.get_bind()
    # One bank per distinct BLZ + address; the first login's name becomes the bank name.
    rows = conn.execute(sa.text("SELECT id, name, blz, server_url FROM bank_logins ORDER BY id")).all()
    banks: dict[tuple[str, str], int] = {}
    for login_id, name, blz, url in rows:
        key = (blz, url.rstrip("/"))
        if key not in banks:
            banks[key] = conn.execute(
                sa.text("INSERT INTO banks (name, blz, server_url) VALUES (:n, :b, :u) RETURNING id"), {"n": name, "b": blz, "u": url}
            ).scalar_one()
        conn.execute(sa.text("UPDATE bank_logins SET bank_id = :b WHERE id = :i"), {"b": banks[key], "i": login_id})
    # Existing logins were created before ownership existed: give them to the first admin (else the first user).
    owner = conn.execute(sa.text("SELECT id FROM users ORDER BY is_admin DESC, id LIMIT 1")).scalar()
    if owner is not None:
        conn.execute(sa.text("UPDATE bank_logins SET user_id = :u"), {"u": owner})
    op.alter_column("bank_logins", "bank_id", nullable=False)
    op.create_foreign_key("bank_logins_bank_id_fkey", "bank_logins", "banks", ["bank_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_bank_logins_user_id", "bank_logins", ["user_id"])
    op.drop_column("bank_logins", "name")
    op.drop_column("bank_logins", "blz")
    op.drop_column("bank_logins", "server_url")


def downgrade() -> None:
    op.add_column("bank_logins", sa.Column("name", sa.String(120), nullable=True))
    op.add_column("bank_logins", sa.Column("blz", sa.String(8), nullable=True))
    op.add_column("bank_logins", sa.Column("server_url", sa.String(255), nullable=True))
    op.execute("UPDATE bank_logins l SET name = b.name, blz = b.blz, server_url = b.server_url FROM banks b WHERE b.id = l.bank_id")
    op.drop_index("ix_bank_logins_user_id", "bank_logins")
    op.drop_constraint("bank_logins_bank_id_fkey", "bank_logins", type_="foreignkey")
    op.drop_column("bank_logins", "user_id")
    op.drop_column("bank_logins", "bank_id")
    op.drop_table("banks")
