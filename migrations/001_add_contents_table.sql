-- Migration 001: Add contents table and unit columns
-- 작품 마스터 테이블 추가 및 진행도 컬럼 추가

-- Step 1: contents 테이블 생성
CREATE TABLE IF NOT EXISTS contents (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    year_or_platform TEXT,
    creator TEXT,
    img_url TEXT,
    tmdb_id INTEGER,
    mangadex_id TEXT,
    naver_title_id TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(title, category)
);

-- Step 2: 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_contents_category ON contents(category);
CREATE INDEX IF NOT EXISTS idx_contents_tmdb ON contents(tmdb_id);

-- Step 3: 기존 reviews 데이터로 contents 테이블 채우기
INSERT INTO contents (title, category, year_or_platform, creator, img_url, created_at)
SELECT DISTINCT ON (movie_title, category)
    movie_title as title,
    category,
    movie_year as year_or_platform,
    director as creator,
    img_url,
    created_at
FROM reviews
WHERE movie_title IS NOT NULL
ORDER BY movie_title, category, created_at DESC
ON CONFLICT (title, category) DO NOTHING;

-- Step 4: reviews 테이블에 새 컬럼 추가
DO $$
BEGIN
    ALTER TABLE reviews ADD COLUMN IF NOT EXISTS content_id INTEGER;
    ALTER TABLE reviews ADD COLUMN IF NOT EXISTS unit_from INTEGER;
    ALTER TABLE reviews ADD COLUMN IF NOT EXISTS unit_to INTEGER;
    ALTER TABLE reviews ADD COLUMN IF NOT EXISTS latest_units INTEGER;
    ALTER TABLE reviews ADD COLUMN IF NOT EXISTS source_url TEXT;
EXCEPTION WHEN duplicate_column THEN
    RAISE NOTICE 'Columns already exist, skipping';
END $$;

-- Step 5: content_id 연결
UPDATE reviews r
SET content_id = c.id
FROM contents c
WHERE r.movie_title = c.title
  AND r.category = c.category
  AND r.content_id IS NULL;

-- Step 6: content_id 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_reviews_content ON reviews(content_id);

-- Step 7: 기존 데이터의 unit 값은 NULL로 유지 (전체 총평 취급)
-- 새 리뷰부터 진행도 사용 시작

-- Note: content_id NOT NULL 제약과 FK는 데이터 검증 후 수동으로 추가
-- ALTER TABLE reviews ALTER COLUMN content_id SET NOT NULL;
-- ALTER TABLE reviews ADD CONSTRAINT fk_reviews_content
--     FOREIGN KEY (content_id) REFERENCES contents(id) ON DELETE CASCADE;

-- Note: 구 컬럼 삭제는 최소 1주일 운영 후 수동으로 실행
-- ALTER TABLE reviews DROP COLUMN movie_title;
-- ALTER TABLE reviews DROP COLUMN movie_year;
-- ALTER TABLE reviews DROP COLUMN director;
-- ALTER TABLE reviews DROP COLUMN category;
-- ALTER TABLE reviews DROP COLUMN img_url;
