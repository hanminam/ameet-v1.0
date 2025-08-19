# 1. 베이스 이미지 선택
FROM python:3.11-slim

# 2. 작업 디렉토리 설정
WORKDIR /app

# 3. 의존성 파일 먼저 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. [수정] src 폴더를 컨테이너 안으로 복사
# 이제 컨테이너 안에는 /app/src/app/... 구조가 생성됩니다.
COPY src .

# 5. [수정] PYTHONPATH에 /app/src 를 추가
# 파이썬에게 /app/src 폴더에서 패키지를 찾으라고 명시적으로 알려줍니다.
ENV PYTHONPATH "${PYTHONPATH}:/app/src"

# 6. 서버 실행 명령어
# 6. 서버가 사용할 포트 지정 (Cloud Run 기본 포트)
EXPOSE 8080

# 7. [수정] 서버 실행 (Gunicorn을 사용한 프로덕션 방식)
# Cloud Run이 주입하는 PORT 환경 변수를 사용하도록 수정
CMD ["gunicorn", "--chdir", "src", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "--bind", "0.0.0.0:8080"]