-- Migration 004: Add music review metadata support

ALTER TABLE contents
    ADD COLUMN IF NOT EXISTS musicbrainz_id TEXT,
    ADD COLUMN IF NOT EXISTS musicbrainz_type TEXT;

ALTER TABLE contents DROP CONSTRAINT IF EXISTS contents_title_category_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_contents_title_category_unique
ON contents(title, category)
WHERE category NOT IN ('music_album', 'music_track');

CREATE UNIQUE INDEX IF NOT EXISTS idx_contents_music_mbid_unique
ON contents(musicbrainz_id, category)
WHERE musicbrainz_id IS NOT NULL
  AND category IN ('music_album', 'music_track');

CREATE UNIQUE INDEX IF NOT EXISTS idx_contents_music_title_creator_unique
ON contents(title, category, COALESCE(creator, ''))
WHERE musicbrainz_id IS NULL
  AND category IN ('music_album', 'music_track');

CREATE INDEX IF NOT EXISTS idx_contents_musicbrainz
ON contents(musicbrainz_id);
