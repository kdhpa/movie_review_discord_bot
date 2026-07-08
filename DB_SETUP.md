# 데이터베이스 설정 가이드

## 1. Supabase 설정 (무료 PostgreSQL 호스팅)

### 1단계: Supabase 계정 생성
1. https://supabase.com 접속
2. "Start your project" 클릭 → GitHub 또는 이메일로 가입
3. 무료 플랜 선택

### 2단계: 프로젝트 생성
1. "New Project" 클릭
2. 프로젝트 정보 입력:
   - **Name**: 원하는 프로젝트 이름 (예: `discord-movie-reviews`)
   - **Database Password**: 강력한 비밀번호 입력 (안전하게 보관!)
   - **Region**: Northeast Asia (Seoul) 또는 가까운 지역 선택
3. "Create new project" 클릭 → 약 1-2분 대기

### 3단계: 연결 정보 가져오기
1. 프로젝트 대시보드에서 **Settings** (톱니바퀴 아이콘) 클릭
2. **Database** 메뉴 선택
3. **Connection string** 섹션에서 아래 정보 찾기:
   - URI 형식: `postgresql://postgres:[YOUR-PASSWORD]@db.xxx.supabase.co:5432/postgres`
   - `[YOUR-PASSWORD]` 부분을 2단계에서 설정한 비밀번호로 바꾸기

### 4단계: db_config.py 수정
프로젝트의 `db_config.py` 파일을 열어서 연결 정보 입력:

```python
DATABASE_URL = "postgresql://postgres:your_actual_password@db.xxx.supabase.co:5432/postgres"
```

**⚠️ 주의**: `db_config.py`는 절대 GitHub에 커밋하지 마세요! `.gitignore`에 추가하세요.

---

## 2. Python 라이브러리 설치

```bash
pip install psycopg2-binary
```

또는 `requirements.txt` 파일이 있다면:

```bash
pip install -r requirements.txt
```

---

## 3. 봇 실행 및 테이블 생성

봇을 처음 실행하면 자동으로 테이블이 생성됩니다:

```bash
python piacia.py
```

콘솔에 다음 메시지가 나오면 성공:
```
✅ Database connected successfully
✅ Tables created/verified successfully
Logged in as YourBot#1234
```

---

## 4. Supabase 웹에서 데이터 확인

1. Supabase 대시보드에서 **Table Editor** 클릭
2. `reviews` 테이블 선택
3. 리뷰가 저장되는 것을 실시간으로 확인 가능!

---

## 5. DB 구조

### `reviews` 테이블

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| id | SERIAL | 자동 증가 ID (Primary Key) |
| user_id | BIGINT | Discord 유저 ID |
| username | TEXT | Discord 유저 이름 |
| movie_title | TEXT | 영화 제목 |
| movie_year | TEXT | 개봉 연도 |
| director | TEXT | 감독 이름 |
| score | REAL | 별점 (0~10) |
| one_line_review | TEXT | 한줄평 |
| additional_comment | TEXT | 추가 코멘트 |
| poster_url | TEXT | 포스터 이미지 URL |
| created_at | TIMESTAMP | 작성 시간 (자동) |
| season | INTEGER | 시즌/기/부 번호 |
| unit_from | INTEGER | 진행 리뷰 시작 화/권 |
| unit_to | INTEGER | 진행 리뷰 종료/현재 화/권 |
| latest_units | INTEGER | 진행률 계산용 최신 공개 화/권 수 |
| source_url | TEXT | 작품 원본 링크 |
| message_id | BIGINT | Discord 리뷰 메시지 ID |
| channel_id | BIGINT | Discord 리뷰 채널 ID |

### `contents` 테이블

작품/콘텐츠 메타데이터를 저장합니다. 음악 평론은 `music_album`, `music_track` 카테고리를 사용하며 `musicbrainz_id`, `musicbrainz_type`으로 MusicBrainz 항목을 구분합니다.

### `review_logs` 테이블

수정/삭제 내역을 저장합니다. `season`, `unit_from`, `unit_to`, `latest_units`, `source_url`로 어느 기수/진행 구간의 리뷰가 수정 또는 삭제되었는지 구분합니다.

---

## 6. 사용 가능한 명령어

봇이 실행되면 Discord에서 다음 명령어 사용 가능:

### `/한줄평`
- 영화/드라마/애니/만화/웹툰/웹소설/앨범/곡 리뷰 작성
- `기수`, `최신화` 옵션으로 시즌/부와 진행률 표시 지원
- 웹소설은 `링크` 옵션으로 노벨피아/문피아/카카오페이지/시리즈/리디 링크 저장 및 메타데이터 크롤링 시도
- 앨범/곡은 `링크` 옵션으로 Spotify 트랙/앨범 또는 YouTube Music 곡 링크를 넣으면 제목/아티스트/커버를 채운 입력창을 바로 열고, 제목 입력 검색은 MusicBrainz를 fallback으로 사용합니다.
- DB에 자동 저장됨

### `/내리뷰`
- 자신이 작성한 최근 리뷰 5개 조회
- 작품/기수별 최신 히스토리 확인

### `/리뷰히스토리`
- 특정 작품의 진행 리뷰 히스토리와 수정/삭제 내역 조회
- 최신 히스토리, 진행 히스토리, 수정/삭제 로그를 함께 표시

### `/영화통계 [영화제목]`
- 특정 영화의 통계 조회
- 평균 평점, 리뷰 개수, 최고/최저 평점 표시

---

## 7. 다른 호스팅 플랫폼 옵션

### MongoDB Atlas (NoSQL 대안)
- 무료: 512MB
- URL: https://www.mongodb.com/atlas
- 장점: JSON 구조, 유연한 스키마
- 단점: SQL 쿼리 사용 불가

### PlanetScale (MySQL 대안)
- 무료: 5GB
- URL: https://planetscale.com
- 장점: MySQL 호환, Git-like workflow
- 단점: 무료 플랜 제한

### Neon (PostgreSQL 대안)
- 무료: 3GB
- URL: https://neon.tech
- 장점: Serverless PostgreSQL, Supabase와 유사
- 단점: 7일간 미사용 시 일시 중지

---

## 8. 보안 팁

1. **절대 커밋하지 말 것**:
   - `db_config.py`
   - `dico_token.py`
   - `.env` 파일

2. **.gitignore 추가**:
```
db_config.py
dico_token.py
*.pyc
__pycache__/
.env
```

3. **환경 변수 사용 (권장)**:
```python
import os
DATABASE_URL = os.getenv('DATABASE_URL')
```

호스팅 플랫폼(Railway, Oracle Cloud 등)에서 환경 변수로 설정하면 더 안전합니다!

---

## 문제 해결

### 연결 실패 시
- 비밀번호에 특수문자가 있다면 URL 인코딩 필요
- Supabase 프로젝트가 활성화되었는지 확인
- 방화벽 설정 확인

### 테이블이 안 보일 때
- Supabase Table Editor에서 Public 스키마 확인
- SQL Editor에서 수동 실행:
```sql
SELECT * FROM reviews;
```

### psycopg2 설치 오류 시
```bash
pip install psycopg2-binary
# 또는
pip install psycopg2
```
