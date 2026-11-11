"""Merchants: an API key per shop (only its hash is stored) and a SKU on each product, so a merchant's checkout can name products the way its store does.

Revision ID: app0003
Revises: app0002
"""
from alembic import op

revision = "app0003"
down_revision = "app0002"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE shop ADD COLUMN api_key_hash text UNIQUE;
        ALTER TABLE shop ADD COLUMN api_key_prefix text;
        ALTER TABLE shop ADD COLUMN feed_url text;
        ALTER TABLE shop ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
        ALTER TABLE product ADD COLUMN sku text;
        CREATE UNIQUE INDEX product_shop_sku ON product (shop_id, sku) WHERE sku IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS product_shop_sku;
        ALTER TABLE product DROP COLUMN IF EXISTS sku;
        ALTER TABLE shop DROP COLUMN IF EXISTS created_at, DROP COLUMN IF EXISTS feed_url, DROP COLUMN IF EXISTS api_key_prefix, DROP COLUMN IF EXISTS api_key_hash
        """
    )
