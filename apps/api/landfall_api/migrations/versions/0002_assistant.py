"""Assistant chats: every question and answer on a product's recommendation, stored for audit.

Revision ID: app0002
Revises: app0001
"""
from alembic import op

revision = "app0002"
down_revision = "app0001"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE assistant_message (
            id serial PRIMARY KEY,
            product_id text NOT NULL REFERENCES product (id),
            recommendation_id text,
            question text NOT NULL,
            answer text NOT NULL,
            kind text NOT NULL,
            refused boolean NOT NULL DEFAULT false,
            refusal_reason text,
            model text,
            prompt_version text,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX assistant_message_product ON assistant_message (product_id, id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS assistant_message")
