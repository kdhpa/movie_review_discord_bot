# 리뷰 DB 재설계 마이그레이션 가이드

## 📋 변경 사항 요약

### 새로운 테이블 구조
- **contents 테이블**: 작품 마스터 (중복 제거, 외부 ID 저장)
- **reviews 테이블**: `content_id` FK 추가, `unit_from/unit_to` 진행도 컬럼 추가

### 주요 변경 사항
1. ✅ 작품 메타 데이터 중복 제거 (`movie_title`, `movie_year`, `director`, `img_url` → `contents` 테이블로 이동)
2. ✅ 진행도 기반 리뷰 지원 (`unit_from`, `unit_to` 컬럼 추가)
3. ✅ 외부 ID 저장 (`tmdb_id`, `mangadex_id`, `naver_title_id`)
4. ✅ 같은 작품에 대해 여러 구간 리뷰 누적 가능
5. ✅ 음악 리뷰를 곡(`music_track`) 기준으로 정리하고 앨범 리뷰 제거

---

## 🚀 마이그레이션 실행 방법

### 1단계: 백업

**⚠️ 중요: 반드시 DB 백업을 먼저 수행하세요!**

```bash
# Supabase Dashboard에서 백업 또는
# pg_dump를 사용한 백업
```

### 2단계: 마이그레이션 SQL 실행

Supabase SQL Editor 또는 psql에서 실행:

```bash
# SQL 파일 실행
psql $DATABASE_URL < migrations/001_add_contents_table.sql
```

또는 Supabase Dashboard → SQL Editor:
```sql
-- migrations/001_add_contents_table.sql 내용 복사 후 실행
```

### 3단계: 데이터 검증

```sql
-- contents 테이블 확인
SELECT COUNT(*) FROM contents;
SELECT * FROM contents LIMIT 10;

-- reviews 테이블 content_id 연결 확인
SELECT COUNT(*) FROM reviews WHERE content_id IS NULL;
-- 결과: 0 (모든 리뷰가 content_id를 가져야 함)

-- content_id 연결 통계
SELECT
    c.category,
    COUNT(*) as review_count
FROM reviews r
JOIN contents c ON r.content_id = c.id
GROUP BY c.category;
```

### 4단계: 봇 재시작

```bash
# 봇 재시작 (새 코드 적용)
python piacia.py
```

---

## 📊 마이그레이션 후 동작 방식

### 신규 리뷰 작성 플로우

1. **작품 검색** → TMDB/MangaDex/Naver API 호출
2. **contents 테이블 UPSERT**
   - 기존 작품이 있으면 ID 반환
   - 없으면 INSERT 후 ID 반환
3. **reviews 테이블 INSERT**
   - `content_id` FK 연결
   - `unit_from/unit_to`는 NULL (진행도 미지원 단계)

### 기존 리뷰 조회

- `get_user_reviews()`: `LEFT JOIN contents` 사용
- 기존 리뷰 (`content_id = NULL`)는 레거시 컬럼 (`movie_title`, `category`) 사용
- 신규 리뷰는 `contents` 테이블에서 메타 데이터 조회

---

## ⚠️ 주의사항

### 마이그레이션 후 확인 사항

1. **모든 리뷰가 content_id를 가지는지 확인**
   ```sql
   SELECT COUNT(*) FROM reviews WHERE content_id IS NULL;
   ```
   → 0이어야 함

2. **중복 작품 확인**
   ```sql
   SELECT title, category, COUNT(*)
   FROM contents
   GROUP BY title, category
   HAVING COUNT(*) > 1;
   ```
   → 결과 없어야 함 (UNIQUE 제약)

3. **외래 키 제약 추가 (데이터 검증 후)**
   ```sql
   -- 모든 데이터가 정상이면 실행
   ALTER TABLE reviews
       ALTER COLUMN content_id SET NOT NULL,
       ADD CONSTRAINT fk_reviews_content
           FOREIGN KEY (content_id) REFERENCES contents(id) ON DELETE CASCADE;
   ```

### 구 컬럼 삭제 (1주일 이상 운영 후)

```sql
-- 최소 1주일 이상 정상 운영 후 실행
ALTER TABLE reviews
    DROP COLUMN movie_title,
    DROP COLUMN movie_year,
    DROP COLUMN director,
    DROP COLUMN img_url,
    DROP COLUMN category;
```

---

## 🔄 롤백 방법

마이그레이션에 문제가 있을 경우:

```sql
-- 1. content_id 컬럼 삭제
ALTER TABLE reviews DROP COLUMN content_id;
ALTER TABLE reviews DROP COLUMN unit_from;
ALTER TABLE reviews DROP COLUMN unit_to;

-- 2. contents 테이블 삭제
DROP TABLE contents;

-- 3. 백업 복원
-- (백업에서 복원)
```

---

## 📈 향후 단계 (Phase 2)

### 진행도 기반 리뷰 활성화

1. **UI 수정**: ReviewForm에 진행도 입력 필드 추가
2. **unit_from 자동 계산**: `save_review_v2()` 사용
3. **재미 곡선 시각화**: matplotlib 그래프 생성

### 구현 예정 기능

- `/재미곡선 제목:[..]`: 구간별 평점 라인 차트
- `/내리뷰상세 제목:[..]`: 작품별 모든 구간 리뷰 표시
- 진행도 입력 시 자동 알림: "💡 53~100화 평으로 등록되었습니다"

---

## 📞 문제 발생 시

1. Discord 서버 로그 확인
2. Supabase Dashboard → Logs 확인
3. `reviews` 테이블에서 `content_id IS NULL` 행 조사
4. 백업에서 복원 후 재시도

**문의**: GitHub Issues 또는 Discord 서버
