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

            # 인덱스 생성 (이미 존재하면 무시됨)
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_id ON reviews(user_id)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_movie_title ON reviews(movie_title)
            ''')

            self.conn.commit()
            cursor.close()
            print("✅ Tables created/verified successfully")
        except Exception as e:
            print(f"❌ Table creation failed: {e}")

    def save_review(self, user_id, username, movie_title, movie_year, director,
                   score, one_line_review, additional_comment, category='movie'):
        """리뷰 저장"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('''
                        INSERT INTO reviews
                        (user_id, username, movie_title, movie_year, director, score,
                         one_line_review, additional_comment, category)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    ''', (
                        user_id, username, movie_title, movie_year,
                        director, score, one_line_review, additional_comment,
                        category
                    ))

                    return cursor.fetchone()[0]
        except Exception as e:
            print(f"❌ Failed to save review: {e}")
            return None

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

    def get_all_reviews(self, limit=50):
        """전체 리뷰 히스토리"""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor = self.conn.cursor(cursor_factory=RealDictCursor)
                    cursor.execute('''
                        SELECT * FROM reviews
                        ORDER BY created_at DESC
                        LIMIT %s
                    ''', (limit,))

                    reviews = cursor.fetchall()
                    return reviews
        except Exception as e:
            print(f"❌ Failed to get all reviews: {e}")
            return []
        
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

    def close(self):
        """DB 연결 종료"""
        if self.conn:
            self.conn.close()
            print("Database connection closed")
