import os
import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from typing import List

# 1. Supabaseの合鍵を読み込んで接続
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None

app = FastAPI()

# CORS設定（スマホのブラウザからの通信を許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- データの受け皿（型）の定義 ---
class ItemCreate(BaseModel):
    batch_name: str
    brand: str
    brand_id: str
    keywords: str
    material_text: str
    status_text: str
    size_input: str
    category_id: str
    category_text: str
    images: List[str]
    title: str
    description: str

# --- APIエンドポイント（URLの窓口） ---

@app.get("/")
def read_root():
    return {"status": "OK", "message": "Render上のPythonサーバーが本番稼働中です！"}

# ① 管理番号を発行するAPI（旧: reserveNewCode）
@app.get("/api/reserve-code")
def reserve_code():
    # 今回はシンプルに「TMP-日時」の形式で仮番号を即座に発行します
    now = datetime.datetime.now()
    temp_code = f"TMP-{int(now.timestamp())}"
    return {"code": temp_code, "status": "OK"}

# ② データをSupabaseに保存するAPI（旧: processHeavyData）
@app.post("/api/save-item")
def save_item(item: ItemCreate, target_code: str):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabaseの接続設定がありません")
        
    try:
        # データベースに書き込むデータの形に整える
        insert_data = {
            "batch_name": item.batch_name,
            "item_code": target_code,
            "brand": item.brand,
            "brand_id": item.brand_id,
            "keywords": item.keywords,
            "material": item.material_text,
            "status_text": item.status_text,
            "size_input": item.size_input,
            "category_id": item.category_id,
            "category_text": item.category_text,
            "title": item.title,
            "description": item.description,
            "images": item.images  # JSONBとして自動で保存されます
        }
        
        # Supabaseの「mercari_items」テーブルに挿入
        response = supabase.table("mercari_items").insert(insert_data).execute()
        
        return {"status": "OK", "message": "Supabaseへのデータ保存が完了しました！", "code": target_code}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存エラー: {str(e)}")
