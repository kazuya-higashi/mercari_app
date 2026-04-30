from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# どのサイトからの通信も許可する設定（CORS）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# テスト用のアクセス口
@app.get("/")
def read_root():
    return {"status": "OK", "message": "Render上のPythonバックエンドが正常に起動しています！"}