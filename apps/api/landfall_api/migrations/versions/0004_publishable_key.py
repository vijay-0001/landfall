"""A publishable key per shop: quote-only, safe to put in a web page (the checkout widget sends it). It is derived from the secret key, which stays secret.

Revision ID: app0004
Revises: app0003
"""
from alembic import op

revision = "app0004"
down_revision = "app0003"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE shop ADD COLUMN publishable_key text UNIQUE
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE shop DROP COLUMN IF EXISTS publishable_key")
