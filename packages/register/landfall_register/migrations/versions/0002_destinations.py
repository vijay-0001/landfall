"""Allow Australia and Canada as destinations.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.execute("ALTER TABLE rate_row DROP CONSTRAINT IF EXISTS rate_row_destination_check")
    op.execute("ALTER TABLE rate_row ADD CONSTRAINT rate_row_destination_check CHECK (destination IN ('US', 'EU', 'GB', 'AU', 'CA'))")


def downgrade() -> None:
    op.execute("ALTER TABLE rate_row DROP CONSTRAINT IF EXISTS rate_row_destination_check")
    op.execute("ALTER TABLE rate_row ADD CONSTRAINT rate_row_destination_check CHECK (destination IN ('US', 'EU', 'GB'))")
