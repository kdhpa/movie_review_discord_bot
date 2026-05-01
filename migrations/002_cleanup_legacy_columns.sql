-- Migration 002: Remove legacy columns from reviews table
-- ⚠️ 경고: 이 스크립트는 reviews 테이블의 컬럼을 삭제합니다.
-- 반드시 백업 후 실행하세요!

-- Step 1: content_id NULL 체크
DO $$
DECLARE
    null_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO null_count FROM reviews WHERE content_id IS NULL;

    IF null_count > 0 THEN
        RAISE EXCEPTION '❌ content_id가 NULL인 리뷰가 %개 있습니다. 먼저 마이그레이션하세요.', null_count;
    END IF;

    RAISE NOTICE '✅ 모든 리뷰가 content_id를 가지고 있습니다.';
END $$;

-- Step 2: content_id NOT NULL 제약 추가
ALTER TABLE reviews ALTER COLUMN content_id SET NOT NULL;

-- Step 3: FK 제약 추가
ALTER TABLE reviews ADD CONSTRAINT fk_reviews_content
    FOREIGN KEY (content_id) REFERENCES contents(id) ON DELETE CASCADE;

-- Step 4: 레거시 컬럼 삭제
ALTER TABLE reviews DROP COLUMN IF EXISTS movie_title;
ALTER TABLE reviews DROP COLUMN IF EXISTS movie_year;
ALTER TABLE reviews DROP COLUMN IF EXISTS director;
ALTER TABLE reviews DROP COLUMN IF EXISTS category;
ALTER TABLE reviews DROP COLUMN IF EXISTS img_url;

-- Step 5: 불필요한 인덱스 삭제
DROP INDEX IF EXISTS idx_movie_title;

-- 완료 메시지
DO $$
BEGIN
    RAISE NOTICE '✅ 레거시 컬럼 삭제 완료!';
END $$;
