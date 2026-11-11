"""Product images: the merchant's photo addresses (several per product) and what the model read in them. Only addresses and TEXT are kept, never the image itself.

Revision ID: app0006
Revises: app0005
"""
from alembic import op

revision = "app0006"
down_revision = "app0005"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE product ADD COLUMN images jsonb NOT NULL DEFAULT '[]'::jsonb;
        ALTER TABLE product ADD COLUMN image_reads jsonb NOT NULL DEFAULT '{}'::jsonb
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE product DROP COLUMN IF EXISTS image_reads, DROP COLUMN IF EXISTS images")
