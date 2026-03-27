# 가벼운 베이스 이미지
FROM python:3.11-slim

# 작업 디렉토리
WORKDIR /app

# 시스템 의존성 (psycopg2-binary용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 설치 (캐시 활용)
COPY requirements.txt .

# pip 메모리 최적화 옵션
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY . .

# 실행
CMD ["python", "piacia.py"]
