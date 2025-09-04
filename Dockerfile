# Dockerfile

# 1. 베이스 이미지 설정
FROM python:3.11-slim

# 2. 작업 디렉토리 설정
WORKDIR /app

# Debian/Ubuntu 기반 이미지에서 필요한 라이브러리들을 설치합니다.
RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    fonts-nanum* \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# 3. 의존성 파일만 먼저 복사 (가장 변경 빈도가 낮음)
COPY requirements.txt .

# 4. 의존성 설치 (이 레이어는 requirements.txt가 변경될 때만 재실행됨)
RUN pip install --no-cache-dir -r requirements.txt

# 5. Playwright 브라우저 설치 (이 레이어도 거의 재실행되지 않음)
RUN playwright install chromium

# 6. 소스 코드 복사 (가장 변경 빈도가 높음)
COPY ./src /app/src

# 7. 서버가 사용할 포트 지정
EXPOSE 8080

# 8. 서버 실행
CMD ["gunicorn", "--chdir", "src", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "--bind", "0.0.0.0:8080", "--timeout", "600"]