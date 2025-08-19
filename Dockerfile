# 1. 베이스 이미지 선택
FROM python:3.11-slim

# 2. 작업 디렉토리 설정
WORKDIR /app

# 3. 의존성 파일 먼저 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. [수정] 프로젝트 전체를 컨테이너 안으로 복사
# 이렇게 하면 컨테이너 내에 /app/app, /app/requirements.txt 등의 구조가 생성됩니다.
COPY . .

# 5. 서버 실행 명령어
# 이제 컨테이너 내의 경로가 /app/app/main.py로 올바르기 때문에
# 이 표준 명령어가 정상적으로 동작합니다.
CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "--bind", "0.0.0.0:8080"]