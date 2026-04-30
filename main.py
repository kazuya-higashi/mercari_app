import os
import datetime
import json
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from typing import List

# 1. 環境変数（合鍵）の読み込み
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None

app = FastAPI()

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- データの受け皿 ---
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
    thumb_base64: str = ""

# --- APIエンドポイント ---
@app.get("/")
def read_root():
    return {"status": "OK", "message": "Render上のPythonサーバーが本番稼働中です！"}

@app.get("/api/reserve-code")
def reserve_code(batch_name: str = "OM10000HG"):
    # 本格的な連番機能はダッシュボード実装時に追加するため、まずは仮番号を発行します
    now = datetime.datetime.now()
    temp_code = f"TMP-{int(now.timestamp())}"
    return {"code": temp_code, "status": "OK", "displayCount": "新規"}

def analyze_image_with_gemini(base64_img: str, keywords: str):
    if not GEMINI_API_KEY:
        return {"intro": "※AIエラー: APIキーが設定されていません"}
    
    prompt = f"""メルカリShops用SEOエキスパート。画像1枚とキーワード[{keywords}]から情報を抽出しJSONで回答。性別(メンズ,レディース)やブランド名自体は不要。該当しない項目は必ず空文字""にすること。
【絶対ルール】
・画像から確実に読み取れない情報は絶対に記述しないこと。
・ジャケットやベスト等で背部にファン用の穴が開いている場合は、必ず"extraKeywords"に「空調服・ファンウェア」と記載すること。
・「無地」「薄手」という単語は絶対に使用禁止。
・「ブルゾン」「ジャンパー」「パンツ」「シャツ」「パーカー」「ウェア」などのカテゴリー名や同じ名詞・語尾を絶対に何度も繰り返して出力しないこと。
・「スポーツ」「アウトドア」「カジュアル」等のシーン・用途の単語には、不要な「〜ウェア」という語尾をつけないこと。
・アロハシャツ系の場合は必ず"extraKeywords"に「ワイシャツ」「かりゆし」を追加すること。

{{"colors":"カラー カタカナ 漢字","shape":"特徴","pattern":"柄","printedText":"英字","synonyms":"カテゴリーの別称や略称(1つのみ)","season":"季節","scene":"シーン(例: アウトドア カジュアル)","intro":"150〜200文字程度の簡潔で自然なアパレル商品紹介文","type":"tops/bottoms","extraKeywords":"関連検索語をスペース区切りで"}}"""
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": "image/jpeg", "data": base64_img}}
            ]
        }]
    }
    
    try:
        res = requests.post(url, json=payload)
        res.raise_for_status()
        text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        return {"intro": f"※AIエラー発生: {str(e)}"}

@app.post("/api/save-item")
def save_item(item: ItemCreate, target_code: str):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabaseの接続設定がありません")
        
    # Geminiで画像解析
    ai_data = {"intro": ""}
    if item.thumb_base64 and item.thumb_base64 != "DUMMY":
        ai_data = analyze_image_with_gemini(item.thumb_base64, item.keywords)
        
    # 商品説明の生成
    description = f"数ある商品の中からこちらのページをご覧頂きまして誠にありがとうございます(^w^)b\n\n{ai_data.get('intro', '')}\n\n状態：{item.status_text}\n\n 　 ※あくまでも中古品、新品であっても保管品でございますので、微細なダメージの見落としが発生する可能性が高いです。予めご了承頂きたく願います。\n\nサイズ表記：{item.size_input}\n【寸法データ未入力（後ほど計測します）】\n\n平置きの実寸採寸でございます。多少の誤差はお許し頂けましたら幸いです。\n\n送料：全アイテム送料込み、送料無料です！\n\n※佐川急便、ゆうパケット又はヤマト運輸宅急便、ネコポスの予定でございます。選択は不可でございます。\n\n\nスニーカー、ブーツ、ビンテージジーンズ、メンズウエア、アメカジウエア、ライダースジャケット、バイク用品、スポーツウエア、アイウエアetc……..\n超超超高価買取させて頂きます！！ご相談だけでもどうぞ気軽にお問い合わせくださいませ！！量が多い場合は出張買取も承ります！！業者様、古着店様からの買取依頼も大大大歓迎です！！"
    
    # タイトルの生成（※完全な130文字制御は後日実装し、まずは保存テスト用の簡易タイトルとします）
    title = f"{item.brand} {item.category_text.split('>')[-1]} {target_code}" 
    if len(title) > 130:
        title = title[:130]
    
    try:
        # Supabaseへ書き込み
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
            "title": title,
            "description": description,
            "images": item.images
        }
        
        supabase.table("mercari_items").insert(insert_data).execute()
        return {"status": "OK", "message": "Supabaseへの本番データ保存が完了しました！", "code": target_code}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存エラー: {str(e)}")
