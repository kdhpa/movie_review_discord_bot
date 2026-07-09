-- Migration 005: Remove album reviews after switching music reviews to track-only.

BEGIN;

DELETE FROM reviews r
USING contents c
WHERE r.content_id = c.id
  AND c.category = 'music_album';

DELETE FROM reviews
WHERE content_id IS NULL
  AND category = 'music_album';

DELETE FROM review_logs
WHERE category = 'music_album';

DELETE FROM contents c
WHERE c.category = 'music_album'
  AND NOT EXISTS (
    SELECT 1
    FROM reviews r
    WHERE r.content_id = c.id
  );

DROP INDEX IF EXISTS idx_contents_title_category_unique;
DROP INDEX IF EXISTS idx_contents_music_mbid_unique;
DROP INDEX IF EXISTS idx_contents_music_title_creator_unique;

CREATE UNIQUE INDEX IF NOT EXISTS idx_contents_title_category_unique
ON contents(title, category)
WHERE category NOT IN ('music_track', 'game');

CREATE UNIQUE INDEX IF NOT EXISTS idx_contents_music_mbid_unique
ON contents(musicbrainz_id, category)
WHERE musicbrainz_id IS NOT NULL
  AND category = 'music_track';

CREATE UNIQUE INDEX IF NOT EXISTS idx_contents_music_title_creator_unique
ON contents(title, category, COALESCE(creator, ''))
WHERE musicbrainz_id IS NULL
  AND category = 'music_track';

COMMIT;
