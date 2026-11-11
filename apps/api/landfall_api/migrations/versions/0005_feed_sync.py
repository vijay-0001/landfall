"""Scheduled feed sync: when a product's listing last changed (an earlier seller decision then no longer applies), whether it is still in the feed, and when the shop was last synced.

Revision ID: app0005
Revises: app0004
"""
from alembic import op

revision = "app0005"
down_revision = "app0004"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE product ADD COLUMN changed_at timestamptz;
        ALTER TABLE product ADD COLUMN active boolean NOT NULL DEFAULT true;
        ALTER TABLE shop ADD COLUMN last_synced_at timestamptz;
        ALTER TABLE shop ADD COLUMN feed_currency text
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE shop DROP COLUMN IF EXISTS feed_currency, DROP COLUMN IF EXISTS last_synced_at;
        ALTER TABLE product DROP COLUMN IF EXISTS active, DROP COLUMN IF EXISTS changed_at
        """
    )
