import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client

# 1. Renderに登録した環境変数（合鍵）を読み込む
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# 2. Supabaseへの接続クライアントを作成
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

# CORSの設定（スマホやHTMLからアクセスできるようにする）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 基本の接続テスト
@app.get("/")
def read_root():
    return {"status": "OK", "message": "Render上のPythonサーバーが稼働中です！"}

# ★新規：Supabaseとのデータベース接続テスト
@app.get("/test-db")
def test_db():
    if not supabase:
        return {"status": "error", "message": "鍵が設定されていません。環境変数を確認してください。"}
    
    try:
        # 先ほど作った mercari_items テーブルにアクセスしてみる
        response = supabase.table("mercari_items").select("*").limit(1).execute()
        return {
            "status": "OK", 
            "message": "大成功！Supabaseのデータベースと完璧に接続できました！", 
            "data": response.data
        }
    except Exception as e:
        return {"status": "error", "message": f"接続エラー: {str(e)}"}