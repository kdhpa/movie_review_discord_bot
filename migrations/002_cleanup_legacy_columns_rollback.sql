-- Rollback: 002_cleanup_legacy_columns.sql
-- ⚠️ 경고: 이 스크립트는 레거시 컬럼을 복원합니다.
-- DB 백업이 있는 경우 백업에서 복원하는 것을 권장합니다.

-- Step 1: FK 제약 제거
ALTER TABLE reviews DROP CONSTRAINT IF EXISTS fk_reviews_content;

-- Step 2: NOT NULL 제약 제거
ALTER TABLE reviews ALTER COLUMN content_id DROP NOT NULL;

-- Step 3: 레거시 컬럼 복원
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS movie_title TEXT;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS movie_year TEXT;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS director TEXT;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS category TEXT;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS img_url TEXT;

-- Step 4: 데이터 복구 (contents 테이블에서 역변환)
UPDATE reviews r
SET movie_title = c.title,
    category = c.category,
    movie_year = c.year_or_platform,
    director = c.creator,
    img_url = c.img_url
FROM contents c
WHERE r.content_id = c.id;

-- Step 5: 인덱스 복원
CREATE INDEX IF NOT EXISTS idx_movie_title ON reviews(movie_title);

-- 완료 메시지
DO $$
BEGIN
    RAISE NOTICE '✅ 레거시 컬럼 복원 완료!';
    RAISE NOTICE '⚠️ 주의: content_id = NULL인 리뷰는 복원되지 않았습니다.';
END $$;
