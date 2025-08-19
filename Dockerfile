# 1. 베이스 이미지 설정
FROM python:3.11-slim

# 2. 작업 디렉토리 설정
WORKDIR /app

# 3. Playwright 브라우저 설치 (PDF 변환에 필수)
# requirements.txt 설치 전에 배치하여 Docker 빌드 캐시 효율성 증대
RUN playwright install chromium

# 4. [수정] 의존성 파일만 먼저 복사하여 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. [수정] src 폴더를 명시적으로 복사
COPY ./src /app/src

# 6. 서버가 사용할 포트 지정
EXPOSE 8080

# 7. 서버 실행 (src 폴더 구조에 맞춤)
CMD ["gunicorn", "--chdir", "src", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "--bind", "0.0.0.0:8080"]