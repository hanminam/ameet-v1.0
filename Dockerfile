# 1. 베이스 이미지 설정
FROM python:3.11-slim

# 2. 작업 디렉토리 설정
WORKDIR /app

# 3. 의존성 파일만 먼저 복사
COPY requirements.txt .

# 4. [수정] 의존성 설치를 먼저 실행
RUN pip install --no-cache-dir -r requirements.txt

# 5. [수정] 의존성 설치 후 Playwright 브라우저 설치
RUN playwright install chromium

# 6. src 폴더를 명시적으로 복사
COPY ./src /app/src

# 7. 서버가 사용할 포트 지정
EXPOSE 8080

# 8. 서버 실행 (프로덕션 명령어)
CMD ["gunicorn", "--chdir", "src", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "--bind", "0.0.0.0:8080"]