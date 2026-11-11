"""App tables: shop, product, recommendation, decision, order, stamps, radar choices, rule proposals, audit log.

Separate Alembic history (version table alembic_version_app) so the register package stays reusable on its own.

Revision ID: app0001
Revises:
"""
from alembic import op

revision = "app0001"
down_revision = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE shop (
            id text PRIMARY KEY, name text NOT NULL, country text NOT NULL, city text NOT NULL,
            ioss_registered boolean NOT NULL DEFAULT false, paypal_merchant_id text
        );
        CREATE TABLE product (
            id text PRIMARY KEY, shop_id text NOT NULL REFERENCES shop (id), title text NOT NULL, description text NOT NULL,
            photo_url text, prices jsonb NOT NULL, category text, inputs_hash text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE fine_print (
            version text PRIMARY KEY, body text NOT NULL, published_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE recommendation (
            id text PRIMARY KEY, product_id text NOT NULL REFERENCES product (id), payload jsonb NOT NULL,
            band text NOT NULL, register_version integer NOT NULL, model text NOT NULL, prompt_version text NOT NULL,
            inputs_hash text NOT NULL, answers jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX recommendation_product ON recommendation (product_id, created_at DESC);
        CREATE TABLE decision (
            id text PRIMARY KEY, recommendation_id text NOT NULL REFERENCES recommendation (id),
            product_id text NOT NULL REFERENCES product (id),
            action text NOT NULL CHECK (action IN ('accepted', 'overridden')), code text NOT NULL, origin text NOT NULL,
            fine_print_version text NOT NULL REFERENCES fine_print (version), evidence_ref text, user_id text NOT NULL,
            at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX decision_product ON decision (product_id, at DESC);
        CREATE TABLE app_order (
            id text PRIMARY KEY, shop_id text NOT NULL REFERENCES shop (id), paypal_order_id text UNIQUE, capture_id text,
            destination text NOT NULL, currency text NOT NULL, item_total numeric(14, 2) NOT NULL, shipping numeric(14, 2) NOT NULL,
            duty_tax numeric(14, 2) NOT NULL, register_version integer NOT NULL, import_date date NOT NULL,
            status text NOT NULL, quote jsonb NOT NULL, capture jsonb, shipment jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE stamp (
            shop_id text NOT NULL REFERENCES shop (id), destination text NOT NULL, earned_at timestamptz NOT NULL DEFAULT now(),
            first_order_id text, PRIMARY KEY (shop_id, destination)
        );
        CREATE TABLE radar_choice (
            shop_id text NOT NULL REFERENCES shop (id), alert_key text NOT NULL, choice text NOT NULL CHECK (choice IN ('absorb', 'pass_on')),
            at timestamptz NOT NULL DEFAULT now(), scheduled jsonb, PRIMARY KEY (shop_id, alert_key)
        );
        CREATE TABLE rule_proposal (
            id text PRIMARY KEY, payload jsonb NOT NULL, status text NOT NULL DEFAULT 'pending',
            reviewer text, decided_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
            notice_doc_number text NOT NULL UNIQUE
        );
        CREATE TABLE audit_event (
            id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(), actor text NOT NULL, action text NOT NULL,
            entity text NOT NULL, entity_id text NOT NULL, payload jsonb NOT NULL DEFAULT '{}'::jsonb
        );
        CREATE FUNCTION audit_event_guard() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'audit_event is append-only'; END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER audit_event_guard BEFORE UPDATE OR DELETE ON audit_event FOR EACH ROW EXECUTE FUNCTION audit_event_guard();
        CREATE FUNCTION decision_guard() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'decision rows are never changed: record a new decision'; END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER decision_guard BEFORE UPDATE OR DELETE ON decision FOR EACH ROW EXECUTE FUNCTION decision_guard();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS audit_event, rule_proposal, radar_choice, stamp, app_order, decision, recommendation, fine_print, product, shop CASCADE"
    )
