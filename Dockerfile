# 1. 베이스 이미지 선택: 파이썬 3.11 버전의 가벼운(slim) 리눅스 환경에서 시작합니다.
FROM python:3.11-slim

# 2. 작업 디렉토리 설정: 컨테이너 안에서 코드를 저장하고 실행할 기본 폴더를 만듭니다.
WORKDIR /app

# 3. 의존성 파일 복사 및 설치: 먼저 라이브러리 목록을 복사해서 설치합니다.
#    이렇게 하면 코드가 바뀔 때마다 매번 라이브러리를 새로 설치하지 않아 효율적입니다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. 소스 코드 복사: 로컬의 app 폴더에 있는 모든 코드를 컨테이너의 /app 폴더로 복사합니다.
COPY ./app /app

# 5. 서버 실행 명령어: 컨테이너가 시작될 때 이 명령어를 실행합니다.
#    Cloud Run은 기본적으로 8080 포트를 사용하므로, uvicorn을 8080 포트에서 실행하도록 설정합니다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]