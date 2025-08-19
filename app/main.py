# app/main.py (이 상태를 유지)

from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def read_root():
    return {"status": "ok", "message": "It works!"}