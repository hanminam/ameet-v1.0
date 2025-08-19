# 1. 베이스 이미지 설정
FROM python:3.11-slim
WORKDIR /app

# 1. 변경이 거의 없는 requirements.txt를 먼저 복사
COPY requirements.txt .

# 2. 라이브러리 설치 레이어를 먼저 생성 (이 레이어는 거의 변경되지 않음)
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

# 6. src 폴더를 명시적으로 복사
COPY ./src /app/src

# 7. 서버가 사용할 포트 지정
EXPOSE 8080

# 8. 서버 실행 (프로덕션 명령어)
CMD ["gunicorn", "--chdir", "src", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "--bind", "0.0.0.0:8080"]