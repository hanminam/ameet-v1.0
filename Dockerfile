# 1. 베이스 이미지 선택
FROM python:3.11-slim

# 2. 작업 디렉토리 설정
WORKDIR /app

# 3. 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. 소스 코드 복사
COPY ./app /app

# [수정 1] PYTHONPATH 환경 변수 설정
# 파이썬에게 우리 코드가 /app 폴더에 있다고 명시적으로 알려줍니다.
ENV PYTHONPATH "${PYTHONPATH}:/app"

# [수정 2] 서버 실행 명령어
# PYTHONPATH가 설정되었으므로, 다시 표준 경로인 app.main:app을 사용합니다.
CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "--bind", "0.0.0.0:8080"]