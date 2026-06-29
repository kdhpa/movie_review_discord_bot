import psycopg2
from psycopg2.extras import RealDictCursor
# from db_config import DATABASE_URL
import os

DATABASE_URL = os.getenv("DATABASE_URL")

_NO_SEASON_FILTER = object()

def get_conn():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require"
    )


class Database:
    def __init__(self):
        self.conn = None
        self.connect()
        self.create_tables()

    def connect(self):
        """DB 연결"""
        try:
            self.conn = psycopg2.connect(DATABASE_URL)
            print("✅ Database connected successfully")
        except Exception as e:
            print(f"❌ Database connection failed: {e}")

    def create_tables(self):
        """테이블 생성"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reviews (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    movie_title TEXT NOT NULL,
                    movie_year TEXT,
                    director TEXT,
                    score REAL NOT NULL,
                    one_line_review TEXT NOT NULL,
                    additional_comment TEXT,
                    category TEXT DEFAULT 'movie',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')

            # 기존 테이블에 category 컬럼 추가 (이미 존재하면 무시)
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE reviews ADD COLUMN category TEXT DEFAULT 'movie';
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')

            # 기존 테이블에 img_url 컬럼 추가 (이미 존재하면 무시)
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE reviews ADD COLUMN img_url TEXT;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')

            # 기존 테이블에 message_id, channel_id 컬럼 추가 (이미 존재하면 무시)
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE reviews ADD COLUMN message_id BIGINT;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE reviews ADD COLUMN channel_id BIGINT;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')

            # 인덱스 생성 (이미 존재하면 무시됨)
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_id ON reviews(user_id)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_movie_title ON reviews(movie_title)
            ''')

            # review_logs 테이블 생성
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS review_logs (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    action TEXT NOT NULL,
                    movie_title TEXT NOT NULL,
                    category TEXT,
                    old_score REAL,
                    old_one_line_review TEXT,
                    old_additional_comment TEXT,
                    new_score REAL,
                    new_one_line_review TEXT,
                    new_additional_comment TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')

            # review_reactions 테이블 생성
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS review_reactions (
                    id SERIAL PRIMARY KEY,
                    review_id INTEGER NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    reaction_type TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(review_id, user_id)
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_reactions_review_id ON review_reactions(review_id)
            ''')

            # review_comments 테이블 생성
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS review_comments (
                    id SERIAL PRIMARY KEY,
                    review_id INTEGER NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    content TEXT NOT NULL,
                    thread_message_id BIGINT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_comments_review_id ON review_comments(review_id)
            ''')

            # 기존 테이블에 thread_message_id 컬럼 추가 (이미 존재하면 무시)
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE review_comments ADD COLUMN thread_message_id BIGINT;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')

            # 기존 테이블에 season 컬럼 추가 (이미 존재하면 무시)
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE reviews ADD COLUMN season INTEGER;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE review_logs ADD COLUMN season INTEGER;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')

            # contents 테이블 생성 (작품 마스터)
            cursor.execute('''
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
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_contents_category ON contents(category)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_contents_tmdb ON contents(tmdb_id)
            ''')

            # reviews 테이블에 content_id, unit 컬럼 추가
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE reviews ADD COLUMN content_id INTEGER;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE reviews ADD COLUMN unit_from INTEGER;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE reviews ADD COLUMN unit_to INTEGER;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE reviews ADD COLUMN latest_units INTEGER;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE reviews ADD COLUMN source_url TEXT;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_reviews_content ON reviews(content_id)
            ''')

            # review_logs 테이블에도 unit 컬럼 추가
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE review_logs ADD COLUMN unit_from INTEGER;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE review_logs ADD COLUMN unit_to INTEGER;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE review_logs ADD COLUMN latest_units INTEGER;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')
            cursor.execute('''
                DO $$
                BEGIN
                    ALTER TABLE review_logs ADD COLUMN source_url TEXT;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')

            self.conn.commit()
            cursor.close()
            print("✅ Tables created/verified successfully")
        except Exception as e:
            print(f"❌ Table creation failed: {e}")

    @staticmethod
    def _build_season_clause(season, column='r.season'):
        """season 값에 따른 SQL 조건과 파라미터 반환."""
        if season is _NO_SEASON_FILTER:
            return "", ()
        if season is None:
            return f" AND {column} IS NULL", ()
        return f" AND {column} = %s", (season,)

    def get_or_create_content(self, title, category, year_or_platform=None,
                              creator=None, img_url=None,
                              tmdb_id=None, mangadex_id=None, naver_title_id=None):
        """작품 조회 또는 생성 (UPSERT)"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    # 1. 기존 작품 조회 (title + category로 UNIQUE)
                    cursor.execute('''
                        SELECT id FROM contents
                        WHERE title = %s AND category = %s
                    ''', (title, category))

                    existing = cursor.fetchone()

                    if existing:
                        # 기존 작품이 있으면 ID 반환
                        return existing[0]
                    else:
                        # 없으면 새로 생성
                        cursor.execute('''
                            INSERT INTO contents
                            (title, category, year_or_platform, creator, img_url,
                             tmdb_id, mangadex_id, naver_title_id)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        ''', (title, category, year_or_platform, creator, img_url,
                              tmdb_id, mangadex_id, naver_title_id))

                        conn.commit()
                        return cursor.fetchone()[0]
        except Exception as e:
            print(f"❌ Failed to get_or_create_content: {e}")
            return None

    def save_review_v2(self, user_id, username, content_id, score,
                       one_line_review, additional_comment, unit_to=None,
                       message_id=None, channel_id=None, season=None,
                       latest_units=None, source_url=None):
        """리뷰 저장 (진행도 기반, v2)"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        SELECT title, category, year_or_platform, creator, img_url
                        FROM contents
                        WHERE id = %s
                    ''', (content_id,))
                    content = cursor.fetchone()
                    if not content:
                        return None

                    content_title, content_category, year_or_platform, creator, img_url = content

                    # unit_to가 있으면 unit_from 자동 계산
                    unit_from = None
                    if unit_to is not None:
                        season_clause, season_params = self._build_season_clause(season, 'season')
                        cursor.execute(f'''
                            SELECT MAX(unit_to) FROM reviews
                            WHERE user_id = %s AND content_id = %s
                            {season_clause}
                        ''', (user_id, content_id) + season_params)

                        max_unit = cursor.fetchone()[0]
                        unit_from = (max_unit + 1) if max_unit else 1

                    # 리뷰 저장
                    cursor.execute('''
                        INSERT INTO reviews
                        (user_id, username, movie_title, movie_year, director,
                         category, img_url, content_id, unit_from, unit_to,
                         score, one_line_review, additional_comment,
                         message_id, channel_id, season, latest_units, source_url)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    ''', (user_id, username, content_title, year_or_platform, creator,
                          content_category, img_url, content_id, unit_from, unit_to,
                          score, one_line_review, additional_comment, message_id,
                          channel_id, season, latest_units, source_url))

                    conn.commit()
                    return cursor.fetchone()[0]
        except Exception as e:
            print(f"❌ Failed to save review (v2): {e}")
            return None

    def has_review_v2(self, user_id, content_id, unit_to=None, season=None):
        """리뷰 중복/회고 검증 (진행도 기반, v2)"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    season_clause, season_params = self._build_season_clause(season, 'season')
                    if unit_to is None:
                        # 전체 총평: 이미 전체 총평이 있는지 확인
                        cursor.execute(f'''
                            SELECT id FROM reviews
                            WHERE user_id = %s AND content_id = %s
                              AND unit_from IS NULL AND unit_to IS NULL
                              {season_clause}
                        ''', (user_id, content_id) + season_params)
                        return cursor.fetchone() is not None
                    else:
                        # 구간 평: 기존 max(unit_to)보다 큰지 확인 (회고 차단)
                        cursor.execute(f'''
                            SELECT MAX(unit_to) FROM reviews
                            WHERE user_id = %s AND content_id = %s
                            {season_clause}
                        ''', (user_id, content_id) + season_params)

                        max_unit = cursor.fetchone()[0]
                        if max_unit and unit_to <= max_unit:
                            return True  # 회고 입력 차단
                        return False
        except Exception as e:
            print(f"❌ Failed to check review (v2): {e}")
            return False

    def update_message_id(self, review_id, message_id, channel_id):
        """리뷰의 message_id, channel_id 업데이트"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        UPDATE reviews
                        SET message_id = %s, channel_id = %s
                        WHERE id = %s
                    ''', (message_id, channel_id, review_id))
                    conn.commit()
                    return True
        except Exception as e:
            print(f"❌ Failed to update message_id: {e}")
            return False

    def get_user_reviews(self, user_id, limit=10, category=None):
        """유저별 최신 리뷰 조회. 진행 히스토리는 작품/기수별 최신 행만 반환."""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    category_clause = ""
                    params = [user_id]
                    if category:
                        category_clause = "AND (r.category = %s OR c.category = %s)"
                        params.extend([category, category])
                    params.append(limit)

                    cursor.execute(f'''
                        WITH joined_reviews AS (
                            SELECT
                                r.id,
                                r.user_id,
                                r.username,
                                COALESCE(c.title, r.movie_title) as movie_title,
                                COALESCE(c.category, r.category) as category,
                                COALESCE(c.year_or_platform, r.movie_year) as movie_year,
                                COALESCE(c.creator, r.director) as director,
                                r.score,
                                r.one_line_review,
                                r.additional_comment,
                                r.created_at,
                                COALESCE(c.img_url, r.img_url) as img_url,
                                r.message_id,
                                r.channel_id,
                                r.content_id,
                                r.unit_from,
                                r.unit_to,
                                r.latest_units,
                                r.source_url,
                                r.season,
                                c.title as content_title,
                                c.category as content_category,
                                c.year_or_platform,
                                c.creator,
                                c.img_url as content_img_url
                            FROM reviews r
                            LEFT JOIN contents c ON r.content_id = c.id
                            WHERE r.user_id = %s
                              {category_clause}
                        ),
                        latest_reviews AS (
                            SELECT
                                joined_reviews.*,
                                ROW_NUMBER() OVER (
                                    PARTITION BY
                                        COALESCE(content_id::text, movie_title || '|' || COALESCE(category, '')),
                                        COALESCE(season, 0)
                                    ORDER BY created_at DESC, id DESC
                                ) as rn
                            FROM joined_reviews
                        )
                        SELECT * FROM latest_reviews
                        WHERE rn = 1
                        ORDER BY created_at DESC, id DESC
                        LIMIT %s
                    ''', tuple(params))

                    return cursor.fetchall()
        except Exception as e:
            print(f"❌ Failed to get user reviews: {e}")
            return []

    def get_content_stats(self, title, category=None):
        """콘텐츠별 평점 통계. 사용자별 최신 히스토리 행을 대표 점수로 사용."""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    category_clause = ""
                    params = [title]
                    if category:
                        category_clause = "AND c.category = %s"
                        params.append(category)

                    cursor.execute(f'''
                        WITH latest_scores AS (
                            SELECT
                                r.user_id,
                                r.score,
                                ROW_NUMBER() OVER (
                                    PARTITION BY r.user_id
                                    ORDER BY r.created_at DESC, r.id DESC
                                ) as rn
                            FROM reviews r
                            JOIN contents c ON r.content_id = c.id
                            WHERE c.title = %s
                              {category_clause}
                        )
                        SELECT
                            COUNT(*) as review_count,
                            AVG(score) as avg_score,
                            MAX(score) as max_score,
                            MIN(score) as min_score
                        FROM latest_scores
                        WHERE rn = 1
                    ''', tuple(params))

                    stats = cursor.fetchone()
                    return stats
        except Exception as e:
            print(f"❌ Failed to get content stats: {e}")
            return None

    def delete_review(self, user_id, title, category=None, season=_NO_SEASON_FILTER):
        """유저의 특정 콘텐츠 리뷰 삭제 (v2 호환)"""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    # content_id 기반 삭제
                    season_clause, season_params = self._build_season_clause(season)
                    if category:
                        cursor.execute(f'''
                            WITH target AS (
                                SELECT r.id
                                FROM reviews r
                                JOIN contents c ON r.content_id = c.id
                                WHERE r.user_id = %s
                                  AND c.title = %s
                                  AND c.category = %s
                                  {season_clause}
                                ORDER BY r.created_at DESC, r.id DESC
                                LIMIT 1
                            )
                            DELETE FROM reviews r
                            USING target
                            WHERE r.id = target.id
                            RETURNING r.id
                        ''', (user_id, title, category) + season_params)
                    else:
                        cursor.execute(f'''
                            WITH target AS (
                                SELECT r.id
                                FROM reviews r
                                JOIN contents c ON r.content_id = c.id
                                WHERE r.user_id = %s
                                  AND c.title = %s
                                  {season_clause}
                                ORDER BY r.created_at DESC, r.id DESC
                                LIMIT 1
                            )
                            DELETE FROM reviews r
                            USING target
                            WHERE r.id = target.id
                            RETURNING r.id
                        ''', (user_id, title) + season_params)

                    deleted = cursor.fetchone()
                    conn.commit()
                    return deleted is not None
        except Exception as e:
            print(f"❌ Failed to delete review: {e}")
            return False

    def get_user_review(self, user_id, title, category=None, season=_NO_SEASON_FILTER):
        """사용자의 특정 작품 리뷰 조회 (v2 호환)"""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    # content_id 기반 조회 (JOIN)
                    season_clause, season_params = self._build_season_clause(season)
                    if category:
                        cursor.execute(f'''
                            SELECT
                                r.*,
                                COALESCE(c.title, r.movie_title) as movie_title,
                                COALESCE(c.category, r.category) as category,
                                COALESCE(c.year_or_platform, r.movie_year) as movie_year,
                                COALESCE(c.creator, r.director) as director,
                                COALESCE(c.img_url, r.img_url) as img_url,
                                c.title as content_title,
                                c.category as content_category
                            FROM reviews r
                            JOIN contents c ON r.content_id = c.id
                            WHERE r.user_id = %s AND c.title = %s AND c.category = %s
                              {season_clause}
                            ORDER BY r.created_at DESC
                            LIMIT 1
                        ''', (user_id, title, category) + season_params)
                    else:
                        cursor.execute(f'''
                            SELECT
                                r.*,
                                COALESCE(c.title, r.movie_title) as movie_title,
                                COALESCE(c.category, r.category) as category,
                                COALESCE(c.year_or_platform, r.movie_year) as movie_year,
                                COALESCE(c.creator, r.director) as director,
                                COALESCE(c.img_url, r.img_url) as img_url,
                                c.title as content_title,
                                c.category as content_category
                            FROM reviews r
                            JOIN contents c ON r.content_id = c.id
                            WHERE r.user_id = %s AND c.title = %s
                              {season_clause}
                            ORDER BY r.created_at DESC
                            LIMIT 1
                        ''', (user_id, title) + season_params)

                    return cursor.fetchone()
        except Exception as e:
            print(f"❌ Failed to get user review: {e}")
            return None

    def update_review(self, user_id, title, category, score, one_line_review, additional_comment,
                      img_url=None, season=_NO_SEASON_FILTER):
        """리뷰 수정 (v2 호환)"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    # content_id 기반 리뷰 ID 조회
                    season_clause, season_params = self._build_season_clause(season)
                    cursor.execute(f'''
                        SELECT r.id FROM reviews r
                        JOIN contents c ON r.content_id = c.id
                        WHERE r.user_id = %s AND c.title = %s AND c.category = %s
                          {season_clause}
                        ORDER BY r.created_at DESC
                        LIMIT 1
                    ''', (user_id, title, category) + season_params)

                    result = cursor.fetchone()
                    if not result:
                        return False

                    review_id = result[0]

                    # 리뷰 업데이트 (img_url은 무시, contents.img_url 사용)
                    cursor.execute('''
                        UPDATE reviews
                        SET score = %s, one_line_review = %s, additional_comment = %s
                        WHERE id = %s
                        RETURNING id
                    ''', (score, one_line_review, additional_comment, review_id))

                    updated = cursor.fetchone()
                    conn.commit()
                    return updated is not None
        except Exception as e:
            print(f"❌ Failed to update review: {e}")
            return False

    def log_review_action(self, user_id, username, action, movie_title, category,
                          old_score, old_one_line_review, old_additional_comment,
                          new_score=None, new_one_line_review=None, new_additional_comment=None,
                          season=None, unit_from=None, unit_to=None, latest_units=None,
                          source_url=None):
        """리뷰 수정/삭제 로그 기록"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        INSERT INTO review_logs
                        (user_id, username, action, movie_title, category,
                         old_score, old_one_line_review, old_additional_comment,
                         new_score, new_one_line_review, new_additional_comment,
                         season, unit_from, unit_to, latest_units, source_url)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        user_id, username, action, movie_title, category,
                        old_score, old_one_line_review, old_additional_comment,
                        new_score, new_one_line_review, new_additional_comment,
                        season, unit_from, unit_to, latest_units, source_url
                    ))
                    conn.commit()
                    print(f"✅ Review log saved: {action} - {movie_title}")
                    return True
        except Exception as e:
            print(f"❌ Failed to save review log: {e}")
            return False

    def get_review_history(self, user_id, title, category=None, season=_NO_SEASON_FILTER, limit=10):
        """특정 작품의 진행 리뷰 히스토리 조회."""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    season_clause, season_params = self._build_season_clause(season)
                    if category:
                        cursor.execute(f'''
                            SELECT
                                r.*,
                                COALESCE(c.title, r.movie_title) as movie_title,
                                COALESCE(c.category, r.category) as category,
                                COALESCE(c.year_or_platform, r.movie_year) as movie_year,
                                COALESCE(c.creator, r.director) as director,
                                COALESCE(c.img_url, r.img_url) as img_url
                            FROM reviews r
                            LEFT JOIN contents c ON r.content_id = c.id
                            WHERE r.user_id = %s
                              AND COALESCE(c.title, r.movie_title) = %s
                              AND COALESCE(c.category, r.category) = %s
                              {season_clause}
                            ORDER BY r.created_at DESC, r.id DESC
                            LIMIT %s
                        ''', (user_id, title, category) + season_params + (limit,))
                    else:
                        cursor.execute(f'''
                            SELECT
                                r.*,
                                COALESCE(c.title, r.movie_title) as movie_title,
                                COALESCE(c.category, r.category) as category,
                                COALESCE(c.year_or_platform, r.movie_year) as movie_year,
                                COALESCE(c.creator, r.director) as director,
                                COALESCE(c.img_url, r.img_url) as img_url
                            FROM reviews r
                            LEFT JOIN contents c ON r.content_id = c.id
                            WHERE r.user_id = %s
                              AND COALESCE(c.title, r.movie_title) = %s
                              {season_clause}
                            ORDER BY r.created_at DESC, r.id DESC
                            LIMIT %s
                        ''', (user_id, title) + season_params + (limit,))
                    return cursor.fetchall()
        except Exception as e:
            print(f"❌ Failed to get review history: {e}")
            return []

    def get_review_logs(self, user_id, title=None, category=None, season=_NO_SEASON_FILTER, limit=10):
        """리뷰 수정/삭제 로그 조회."""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    season_clause, season_params = self._build_season_clause(season, 'season')
                    filters = ["user_id = %s"]
                    params = [user_id]

                    if title:
                        filters.append("movie_title = %s")
                        params.append(title)
                    if category:
                        filters.append("category = %s")
                        params.append(category)

                    query = f'''
                        SELECT *
                        FROM review_logs
                        WHERE {' AND '.join(filters)}
                          {season_clause}
                        ORDER BY created_at DESC, id DESC
                        LIMIT %s
                    '''
                    cursor.execute(query, tuple(params) + season_params + (limit,))
                    return cursor.fetchall()
        except Exception as e:
            print(f"❌ Failed to get review logs: {e}")
            return []

    def get_user_reviews_for_title(self, user_id, title, category):
        """특정 제목에 대한 사용자의 모든 리뷰(시즌별 포함) 조회."""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute('''
                        SELECT
                            r.*,
                            COALESCE(c.title, r.movie_title) as movie_title,
                            COALESCE(c.category, r.category) as category,
                            COALESCE(c.year_or_platform, r.movie_year) as movie_year,
                            COALESCE(c.creator, r.director) as director,
                            COALESCE(c.img_url, r.img_url) as img_url,
                            c.title as content_title,
                            c.category as content_category
                        FROM reviews r
                        JOIN contents c ON r.content_id = c.id
                        WHERE r.user_id = %s AND c.title = %s AND c.category = %s
                        ORDER BY r.season ASC NULLS FIRST, r.created_at DESC
                    ''', (user_id, title, category))
                    return cursor.fetchall()
        except Exception as e:
            print(f"❌ Failed to get user reviews for title: {e}")
            return []

    def get_review_by_message_id(self, message_id):
        """message_id로 리뷰 조회"""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute('''
                        SELECT
                            r.*,
                            COALESCE(c.title, r.movie_title) as movie_title,
                            COALESCE(c.category, r.category) as category,
                            COALESCE(c.year_or_platform, r.movie_year) as movie_year,
                            COALESCE(c.creator, r.director) as director,
                            COALESCE(c.img_url, r.img_url) as img_url
                        FROM reviews r
                        LEFT JOIN contents c ON r.content_id = c.id
                        WHERE r.message_id = %s
                    ''', (message_id,))
                    return cursor.fetchone()
        except Exception as e:
            print(f"❌ Failed to get review by message_id: {e}")
            return None

    def toggle_reaction(self, review_id, user_id, username, reaction_type):
        """반응 토글: 같으면 삭제, 다르면 변경, 없으면 추가"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    # 기존 반응 조회
                    cursor.execute('''
                        SELECT reaction_type FROM review_reactions
                        WHERE review_id = %s AND user_id = %s
                    ''', (review_id, user_id))
                    existing = cursor.fetchone()

                    if existing:
                        if existing[0] == reaction_type:
                            # 같은 반응 → 삭제
                            cursor.execute('''
                                DELETE FROM review_reactions
                                WHERE review_id = %s AND user_id = %s
                            ''', (review_id, user_id))
                            conn.commit()
                            return ('removed', reaction_type)
                        else:
                            # 다른 반응 → 변경
                            old_type = existing[0]
                            cursor.execute('''
                                UPDATE review_reactions
                                SET reaction_type = %s, username = %s, created_at = NOW()
                                WHERE review_id = %s AND user_id = %s
                            ''', (reaction_type, username, review_id, user_id))
                            conn.commit()
                            return ('changed', old_type)
                    else:
                        # 새 반응 추가
                        cursor.execute('''
                            INSERT INTO review_reactions (review_id, user_id, username, reaction_type)
                            VALUES (%s, %s, %s, %s)
                        ''', (review_id, user_id, username, reaction_type))
                        conn.commit()
                        return ('added', reaction_type)
        except Exception as e:
            print(f"❌ Failed to toggle reaction: {e}")
            return (None, None)

    def ensure_reaction(self, review_id, user_id, username, reaction_type):
        """반응 확보: 없으면 추가, 다르면 변경, 같으면 유지 (삭제 안함)"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    # 기존 반응 조회
                    cursor.execute('''
                        SELECT reaction_type FROM review_reactions
                        WHERE review_id = %s AND user_id = %s
                    ''', (review_id, user_id))
                    existing = cursor.fetchone()

                    if existing:
                        if existing[0] == reaction_type:
                            # 같은 반응 → 그대로 유지 (삭제 안함)
                            return ('kept', reaction_type)
                        else:
                            # 다른 반응 → 변경
                            old_type = existing[0]
                            cursor.execute('''
                                UPDATE review_reactions
                                SET reaction_type = %s, username = %s, created_at = NOW()
                                WHERE review_id = %s AND user_id = %s
                            ''', (reaction_type, username, review_id, user_id))
                            conn.commit()
                            return ('changed', old_type)
                    else:
                        # 새 반응 추가
                        cursor.execute('''
                            INSERT INTO review_reactions (review_id, user_id, username, reaction_type)
                            VALUES (%s, %s, %s, %s)
                        ''', (review_id, user_id, username, reaction_type))
                        conn.commit()
                        return ('added', reaction_type)
        except Exception as e:
            print(f"❌ Failed to ensure reaction: {e}")
            return (None, None)

    def get_reaction_counts(self, review_id):
        """리뷰별 반응 카운트"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        SELECT reaction_type, COUNT(*) as cnt
                        FROM review_reactions
                        WHERE review_id = %s
                        GROUP BY reaction_type
                    ''', (review_id,))
                    return {row[0]: row[1] for row in cursor.fetchall()}
        except Exception as e:
            print(f"❌ Failed to get reaction counts: {e}")
            return {}

    def get_user_reaction(self, review_id, user_id):
        """유저의 특정 리뷰 반응 조회"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        SELECT reaction_type FROM review_reactions
                        WHERE review_id = %s AND user_id = %s
                    ''', (review_id, user_id))
                    result = cursor.fetchone()
                    return result[0] if result else None
        except Exception as e:
            print(f"❌ Failed to get user reaction: {e}")
            return None

    def add_comment(self, review_id, user_id, username, content, thread_message_id=None):
        """코멘트 추가"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        INSERT INTO review_comments (review_id, user_id, username, content, thread_message_id)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                    ''', (review_id, user_id, username, content, thread_message_id))
                    conn.commit()
                    return cursor.fetchone()[0]
        except Exception as e:
            print(f"❌ Failed to add comment: {e}")
            return None

    def get_user_comment_message_id(self, review_id, user_id):
        """사용자의 해당 리뷰 코멘트의 thread_message_id 조회"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        SELECT thread_message_id FROM review_comments
                        WHERE review_id = %s AND user_id = %s
                    ''', (review_id, user_id))
                    result = cursor.fetchone()
                    return result[0] if result else None
        except Exception as e:
            print(f"❌ Failed to get user comment message_id: {e}")
            return None

    def get_comments(self, review_id, limit=20):
        """리뷰 코멘트 조회"""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute('''
                        SELECT * FROM review_comments
                        WHERE review_id = %s
                        ORDER BY created_at ASC
                        LIMIT %s
                    ''', (review_id, limit))
                    return cursor.fetchall()
        except Exception as e:
            print(f"❌ Failed to get comments: {e}")
            return []

    def get_comment_count(self, review_id):
        """리뷰 코멘트 수"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        SELECT COUNT(*) FROM review_comments
                        WHERE review_id = %s
                    ''', (review_id,))
                    return cursor.fetchone()[0]
        except Exception as e:
            print(f"❌ Failed to get comment count: {e}")
            return 0

    def has_user_comment(self, review_id, user_id):
        """사용자가 해당 리뷰에 코멘트를 남겼는지 확인"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        SELECT id FROM review_comments
                        WHERE review_id = %s AND user_id = %s
                    ''', (review_id, user_id))
                    return cursor.fetchone() is not None
        except Exception as e:
            print(f"❌ Failed to check user comment: {e}")
            return False

    def delete_user_comment(self, review_id, user_id):
        """사용자의 해당 리뷰 코멘트 삭제"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        DELETE FROM review_comments
                        WHERE review_id = %s AND user_id = %s
                    ''', (review_id, user_id))
                    conn.commit()
                    return True
        except Exception as e:
            print(f"❌ Failed to delete user comment: {e}")
            return False

    def get_review_ranking(self, limit=10, category=None):
        """반응 많은 리뷰 랭킹"""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    if category:
                        cursor.execute('''
                            SELECT
                                r.*,
                                COALESCE(c.title, r.movie_title) as movie_title,
                                COALESCE(c.category, r.category) as category,
                                COALESCE(c.year_or_platform, r.movie_year) as movie_year,
                                COALESCE(c.creator, r.director) as director,
                                COALESCE(c.img_url, r.img_url) as img_url,
                                COUNT(rr.id) as reaction_count
                            FROM reviews r
                            LEFT JOIN contents c ON r.content_id = c.id
                            LEFT JOIN review_reactions rr ON r.id = rr.review_id
                            WHERE COALESCE(c.category, r.category) = %s
                            GROUP BY r.id, c.title, c.category, c.year_or_platform, c.creator, c.img_url
                            HAVING COUNT(rr.id) > 0
                            ORDER BY reaction_count DESC, r.created_at DESC
                            LIMIT %s
                        ''', (category, limit))
                    else:
                        cursor.execute('''
                            SELECT
                                r.*,
                                COALESCE(c.title, r.movie_title) as movie_title,
                                COALESCE(c.category, r.category) as category,
                                COALESCE(c.year_or_platform, r.movie_year) as movie_year,
                                COALESCE(c.creator, r.director) as director,
                                COALESCE(c.img_url, r.img_url) as img_url,
                                COUNT(rr.id) as reaction_count
                            FROM reviews r
                            LEFT JOIN contents c ON r.content_id = c.id
                            LEFT JOIN review_reactions rr ON r.id = rr.review_id
                            GROUP BY r.id, c.title, c.category, c.year_or_platform, c.creator, c.img_url
                            HAVING COUNT(rr.id) > 0
                            ORDER BY reaction_count DESC, r.created_at DESC
                            LIMIT %s
                        ''', (limit,))
                    return cursor.fetchall()
        except Exception as e:
            print(f"❌ Failed to get review ranking: {e}")
            return []

    def save_migrated_review(self, user_id, username, movie_title, movie_year, director,
                              score, one_line_review, category='movie', created_at=None,
                              message_id=None, channel_id=None, season=None):
        """마이그레이션된 리뷰 저장 (중복 체크 없이)"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    if created_at:
                        cursor.execute('''
                            INSERT INTO reviews
                            (user_id, username, movie_title, movie_year, director, score,
                             one_line_review, additional_comment, category,
                             message_id, channel_id, created_at, season)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        ''', (
                            user_id, username, movie_title, movie_year,
                            director, score, one_line_review, None,
                            category, message_id, channel_id, created_at, season
                        ))
                    else:
                        cursor.execute('''
                            INSERT INTO reviews
                            (user_id, username, movie_title, movie_year, director, score,
                             one_line_review, additional_comment, category,
                             message_id, channel_id, season)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        ''', (
                            user_id, username, movie_title, movie_year,
                            director, score, one_line_review, None,
                            category, message_id, channel_id, season
                        ))
                    conn.commit()
                    return cursor.fetchone()[0]
        except Exception as e:
            print(f"❌ Failed to save migrated review: {e}")
            return None
