-- Migration 003: Add review history metadata fields

ALTER TABLE reviews
    ADD COLUMN IF NOT EXISTS season INTEGER,
    ADD COLUMN IF NOT EXISTS latest_units INTEGER,
    ADD COLUMN IF NOT EXISTS source_url TEXT;

ALTER TABLE review_logs
    ADD COLUMN IF NOT EXISTS season INTEGER,
    ADD COLUMN IF NOT EXISTS unit_from INTEGER,
    ADD COLUMN IF NOT EXISTS unit_to INTEGER,
    ADD COLUMN IF NOT EXISTS latest_units INTEGER,
    ADD COLUMN IF NOT EXISTS source_url TEXT;
