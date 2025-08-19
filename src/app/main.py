from fastapi import FastAPI
from .core.config import settings

app = FastAPI(title=settings.APP_TITLE)

@app.get("/")
def read_root():
    return {"message": "AMEET v1.0 API Server is running!"}

@app.get("/api/v1/health-check")
def health_check():
    return {"status": "ok", "message": "Server is healthy."}