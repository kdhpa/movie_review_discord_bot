import psycopg2
from psycopg2.extras import RealDictCursor
# from db_config import DATABASE_URL
import os

DATABASE_URL = os.getenv("DATABASE_URL")

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

            self.conn.commit()
            cursor.close()
            print("✅ Tables created/verified successfully")
        except Exception as e:
            print(f"❌ Table creation failed: {e}")

    def save_review(self, user_id, username, movie_title, movie_year, director,
                   score, one_line_review, additional_comment, category='movie', img_url=None,
                   message_id=None, channel_id=None):
        """리뷰 저장"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        INSERT INTO reviews
                        (user_id, username, movie_title, movie_year, director, score,
                         one_line_review, additional_comment, category, img_url,
                         message_id, channel_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    ''', (
                        user_id, username, movie_title, movie_year,
                        director, score, one_line_review, additional_comment,
                        category, img_url, message_id, channel_id
                    ))

                    return cursor.fetchone()[0]
        except Exception as e:
            print(f"❌ Failed to save review: {e}")
            return None

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

    def has_review(self, user_id, movie_title, category='movie'):
        """유저가 해당 콘텐츠에 리뷰를 작성했는지 확인"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        SELECT id FROM reviews
                        WHERE user_id = %s AND movie_title = %s AND category = %s
                    ''', (user_id, movie_title, category))

                    result = cursor.fetchone()
                    return result is not None
        except Exception as e:
            print(f"❌ Failed to check review: {e}")
            return False

    def get_user_reviews(self, user_id, limit=10, category=None):
        """유저별 리뷰 조회"""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    if category:
                        cursor.execute('''
                            SELECT * FROM reviews
                            WHERE user_id = %s AND category = %s
                            ORDER BY created_at DESC
                            LIMIT %s
                        ''', (user_id, category, limit))
                    else:
                        cursor.execute('''
                            SELECT * FROM reviews
                            WHERE user_id = %s
                            ORDER BY created_at DESC
                            LIMIT %s
                        ''', (user_id, limit))

                    return cursor.fetchall()
        except Exception as e:
            print(f"❌ Failed to get user reviews: {e}")
            return []

    def get_content_stats(self, title, category=None):
        """콘텐츠별 평점 통계"""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    if category:
                        cursor.execute('''
                            SELECT
                                COUNT(*) as review_count,
                                AVG(score) as avg_score,
                                MAX(score) as max_score,
                                MIN(score) as min_score
                            FROM reviews
                            WHERE movie_title = %s AND category = %s
                        ''', (title, category))
                    else:
                        cursor.execute('''
                            SELECT
                                COUNT(*) as review_count,
                                AVG(score) as avg_score,
                                MAX(score) as max_score,
                                MIN(score) as min_score
                            FROM reviews
                            WHERE movie_title = %s
                        ''', (title,))

                    stats = cursor.fetchone()
                    return stats
        except Exception as e:
            print(f"❌ Failed to get content stats: {e}")
            return None

    def delete_review(self, user_id, title, category=None):
        """유저의 특정 콘텐츠 리뷰 삭제"""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    if category:
                        cursor.execute('''
                            DELETE FROM reviews
                            WHERE user_id = %s AND movie_title = %s AND category = %s
                            RETURNING id
                        ''', (user_id, title, category))
                    else:
                        cursor.execute('''
                            DELETE FROM reviews
                            WHERE user_id = %s AND movie_title = %s
                            RETURNING id
                        ''', (user_id, title))

                    deleted = cursor.fetchone()
                    conn.commit()
                    return deleted is not None
        except Exception as e:
            print(f"❌ Failed to delete review: {e}")
            return False

    def get_user_review(self, user_id, title, category=None):
        """사용자의 특정 작품 리뷰 조회"""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    if category:
                        cursor.execute('''
                            SELECT id, movie_title, movie_year, director, score,
                                   one_line_review, additional_comment, category, img_url,
                                   message_id, channel_id
                            FROM reviews
                            WHERE user_id = %s AND movie_title = %s AND category = %s
                        ''', (user_id, title, category))
                    else:
                        cursor.execute('''
                            SELECT id, movie_title, movie_year, director, score,
                                   one_line_review, additional_comment, category, img_url,
                                   message_id, channel_id
                            FROM reviews
                            WHERE user_id = %s AND movie_title = %s
                        ''', (user_id, title))

                    return cursor.fetchone()
        except Exception as e:
            print(f"❌ Failed to get user review: {e}")
            return None

    def update_review(self, user_id, title, category, score, one_line_review, additional_comment, img_url=None):
        """리뷰 수정"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    if img_url:
                        cursor.execute('''
                            UPDATE reviews
                            SET score = %s, one_line_review = %s, additional_comment = %s, img_url = %s
                            WHERE user_id = %s AND movie_title = %s AND category = %s
                            RETURNING id
                        ''', (score, one_line_review, additional_comment, img_url, user_id, title, category))
                    else:
                        cursor.execute('''
                            UPDATE reviews
                            SET score = %s, one_line_review = %s, additional_comment = %s
                            WHERE user_id = %s AND movie_title = %s AND category = %s
                            RETURNING id
                        ''', (score, one_line_review, additional_comment, user_id, title, category))

                    updated = cursor.fetchone()
                    conn.commit()
                    return updated is not None
        except Exception as e:
            print(f"❌ Failed to update review: {e}")
            return False

    def log_review_action(self, user_id, username, action, movie_title, category,
                          old_score, old_one_line_review, old_additional_comment,
                          new_score=None, new_one_line_review=None, new_additional_comment=None):
        """리뷰 수정/삭제 로그 기록"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        INSERT INTO review_logs
                        (user_id, username, action, movie_title, category,
                         old_score, old_one_line_review, old_additional_comment,
                         new_score, new_one_line_review, new_additional_comment)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        user_id, username, action, movie_title, category,
                        old_score, old_one_line_review, old_additional_comment,
                        new_score, new_one_line_review, new_additional_comment
                    ))
                    conn.commit()
                    print(f"✅ Review log saved: {action} - {movie_title}")
                    return True
        except Exception as e:
            print(f"❌ Failed to save review log: {e}")
            return False

    def get_review_by_message_id(self, message_id):
        """message_id로 리뷰 조회"""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute('''
                        SELECT * FROM reviews WHERE message_id = %s
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
                            SELECT r.*, COUNT(rr.id) as reaction_count
                            FROM reviews r
                            LEFT JOIN review_reactions rr ON r.id = rr.review_id
                            WHERE r.category = %s
                            GROUP BY r.id
                            HAVING COUNT(rr.id) > 0
                            ORDER BY reaction_count DESC, r.created_at DESC
                            LIMIT %s
                        ''', (category, limit))
                    else:
                        cursor.execute('''
                            SELECT r.*, COUNT(rr.id) as reaction_count
                            FROM reviews r
                            LEFT JOIN review_reactions rr ON r.id = rr.review_id
                            GROUP BY r.id
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
                              message_id=None, channel_id=None):
        """마이그레이션된 리뷰 저장 (중복 체크 없이)"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    if created_at:
                        cursor.execute('''
                            INSERT INTO reviews
                            (user_id, username, movie_title, movie_year, director, score,
                             one_line_review, additional_comment, category,
                             message_id, channel_id, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        ''', (
                            user_id, username, movie_title, movie_year,
                            director, score, one_line_review, None,
                            category, message_id, channel_id, created_at
                        ))
                    else:
                        cursor.execute('''
                            INSERT INTO reviews
                            (user_id, username, movie_title, movie_year, director, score,
                             one_line_review, additional_comment, category,
                             message_id, channel_id)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        ''', (
                            user_id, username, movie_title, movie_year,
                            director, score, one_line_review, None,
                            category, message_id, channel_id
                        ))
                    conn.commit()
                    return cursor.fetchone()[0]
        except Exception as e:
            print(f"❌ Failed to save migrated review: {e}")
            return None
