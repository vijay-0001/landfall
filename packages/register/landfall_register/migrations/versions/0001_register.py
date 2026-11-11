"""Bitemporal rate register.

Valid time: valid_from / valid_to (when the law says the rate applies).
Known time: recorded_in_version / superseded_in_version (when we learned it, by register version).
Rows are never updated in place: the only permitted change is closing a row by setting superseded_*.
An exclusion constraint makes overlapping validity for the same key impossible within the same known time.

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        CREATE TABLE register_version (
            id            serial PRIMARY KEY,
            label         text NOT NULL UNIQUE,
            published_at  timestamptz NOT NULL DEFAULT now(),
            published_by  text NOT NULL,
            source_runs   jsonb NOT NULL DEFAULT '[]'::jsonb,
            note          text
        )
        """
    )
    op.execute(
        """
        CREATE TABLE rate_row (
            id                     bigserial PRIMARY KEY,
            destination            text NOT NULL CHECK (destination IN ('US', 'EU', 'GB')),
            code                   text NOT NULL,
            origin_scope           text NOT NULL,
            measure                text NOT NULL,
            variant                text NOT NULL DEFAULT '',
            rate_kind              text NOT NULL CHECK (rate_kind IN ('percent', 'fixed', 'per_unit', 'none')),
            rate                   numeric(14, 4),
            currency               text,
            params                 jsonb NOT NULL DEFAULT '{}'::jsonb,
            valid_from             date NOT NULL,
            valid_to               date,
            recorded_in_version    integer NOT NULL REFERENCES register_version (id),
            superseded_in_version  integer REFERENCES register_version (id),
            recorded_at            timestamptz NOT NULL DEFAULT now(),
            superseded_at          timestamptz,
            source_ref             text NOT NULL,
            source_url             text,
            note                   text,
            rate_key text GENERATED ALWAYS AS
                (destination || '|' || code || '|' || origin_scope || '|' || measure || '|' || variant) STORED,
            CONSTRAINT rate_nonneg CHECK (rate IS NULL OR rate >= 0),
            CONSTRAINT valid_order CHECK (valid_to IS NULL OR valid_to > valid_from),
            CONSTRAINT known_order CHECK (superseded_in_version IS NULL OR superseded_in_version > recorded_in_version),
            CONSTRAINT no_overlap EXCLUDE USING gist (
                rate_key WITH =,
                daterange(valid_from, valid_to, '[)') WITH &&,
                int4range(recorded_in_version, COALESCE(superseded_in_version, 2147483647), '[)') WITH &&
            )
        )
        """
    )
    op.execute("CREATE INDEX rate_row_lookup ON rate_row (destination, code)")
    op.execute(
        """
        CREATE FUNCTION rate_row_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'rate_row is append-only: rows are never deleted';
            END IF;
            IF OLD.superseded_in_version IS NOT NULL THEN
                RAISE EXCEPTION 'rate_row % is already superseded and cannot change', OLD.id;
            END IF;
            IF (NEW.destination, NEW.code, NEW.origin_scope, NEW.measure, NEW.variant, NEW.rate_kind, NEW.rate, NEW.currency,
                NEW.params, NEW.valid_from, NEW.valid_to, NEW.recorded_in_version, NEW.source_ref, NEW.source_url, NEW.note)
               IS DISTINCT FROM
               (OLD.destination, OLD.code, OLD.origin_scope, OLD.measure, OLD.variant, OLD.rate_kind, OLD.rate, OLD.currency,
                OLD.params, OLD.valid_from, OLD.valid_to, OLD.recorded_in_version, OLD.source_ref, OLD.source_url, OLD.note) THEN
                RAISE EXCEPTION 'rate_row % is not updated in place: close it and add a new row', OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER rate_row_guard BEFORE UPDATE OR DELETE ON rate_row FOR EACH ROW EXECUTE FUNCTION rate_row_guard()"
    )
    op.execute(
        """
        CREATE TABLE source_run (
            id          bigserial PRIMARY KEY,
            source      text NOT NULL,
            started_at  timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            ok          boolean NOT NULL DEFAULT false,
            rows_changed integer NOT NULL DEFAULT 0,
            future_dated integer NOT NULL DEFAULT 0,
            publish     text NOT NULL DEFAULT 'automatic' CHECK (publish IN ('automatic', 'needs_review')),
            detail      text,
            raw_ref     text
        )
        """
    )
    op.execute("CREATE INDEX source_run_source ON source_run (source, started_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS source_run")
    op.execute("DROP TRIGGER IF EXISTS rate_row_guard ON rate_row")
    op.execute("DROP FUNCTION IF EXISTS rate_row_guard()")
    op.execute("DROP TABLE IF EXISTS rate_row")
    op.execute("DROP TABLE IF EXISTS register_version")
