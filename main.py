import os
import re
import datetime
import json
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from typing import List

# --- 環境設定 ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- データの型定義 ---
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

# --- タイトル生成アルゴリズム（GASからの完全移植） ---
def normalize_str(s: str) -> str:
    s = s.upper()
    return re.sub(r'[\s　・、。,\-\(\)（）]', '', s)

def build_final_title(item: ItemCreate, ai_data: dict, target_code: str) -> str:
    size_input = str(item.size_input or "")
    status_text = str(item.status_text or "")
    keywords = str(item.keywords or "")
    category_text = str(item.category_text or "")
    brand = str(item.brand or "").strip()
    material = str(item.material_text or "").strip()

    prefix_arr = ["(^w^)b"]
    if "新品" in status_text or "タグ付き" in keywords:
        prefix_arr.insert(0, "新品未使用 タグ付き")
    
    is_big_size = size_input.upper() in ["XL", "2XL", "3XL", "4XL", "5XL", "XXL", "XXXL", "3L", "4L"]
    if is_big_size:
        prefix_arr.insert(0, f"ビッグサイズ！{size_input}サイズ")

    brand_name_area = [brand] if brand and brand != "ブランド不明" else []
    gender_str = "メンズ" if "メンズ" in category_text else ("レディース" if "レディース" in category_text else "")

    suffix_arr = []
    if material: suffix_arr.append(material)
    if ai_data.get("colors"): suffix_arr.append(re.sub(r'[、：,:]', ' ', str(ai_data["colors"])).strip())
    if gender_str: suffix_arr.append(gender_str)
    if not is_big_size and "不明" not in size_input and size_input != "":
        suffix_arr.append(f"サイズ {size_input}")
    suffix_arr.append(target_code)

    orig_cat_parts = [s.strip() for s in re.split(r'⇒|＞|>|\||/', category_text) if s.strip()]
    has_jacket = len(orig_cat_parts) > 2 and "ジャケット" in orig_cat_parts[2]

    exclude_cats = ["ファッション", "メンズ", "レディース", "その他", "トップス", "ジャケット", "ジャケット・アウター", "アウター", "パンツ", "ボトムス", "スカート", "ワンピース", "サロペット・オーバーオール・オールインワン", "スーツ", "スーツ・フォーマル・ドレス", "セットアップ"]
    cat_parts = [s for s in orig_cat_parts if s not in exclude_cats]
    if len(cat_parts) > 2: cat_parts = cat_parts[-2:]
    cat_parts.reverse()

    redundant_suffixes = ["ウェア", "ウエア", "シャツ", "パンツ", "コート", "ニット", "アウター", "パーカー", "ジャケット", "ブルゾン", "スウェット"]
    cat_words = []
    for w in re.split(r'・|\s+', "・".join(cat_parts)):
        trimmed = w.strip()
        if not trimmed: continue
        is_dup = False
        for ew in cat_words:
            if trimmed in ew or ew in trimmed:
                is_dup = True; break
            for suf in redundant_suffixes:
                if ew.endswith(suf) and trimmed.endswith(suf):
                    is_dup = True; break
            if is_dup: break
        if not is_dup: cat_words.append(trimmed)
            
    category_str = " ".join(cat_words)
    if has_jacket and "ジャケット" not in category_str:
        if not any(w.endswith("ジャケット") for w in cat_words):
            category_str += (" " if category_str else "") + "ジャケット"

    mandatory_text_arr = prefix_arr + brand_name_area + [category_str] + suffix_arr
    mandatory_words_list = [normalize_str(w) for w in " ".join(mandatory_text_arr).split() if normalize_str(w)]
    for b in brand_name_area:
        norm_b = normalize_str(b)
        if norm_b: mandatory_words_list.append(norm_b)

    user_keywords = [w for w in re.split(r'\s+', re.sub(r'[、：,:]', ' ', keywords)) if w]
    is_lon_t = "七分・長袖カットソー" in category_text or ("Tシャツ・カットソー" in category_text and "長袖" in category_text)
    ron_t_str = "ロンT" if is_lon_t else ""

    ai_middle_words = []
    for k in ["shape", "pattern", "printedText", "synonyms", "season", "scene", "extraKeywords"]:
        if ai_data.get(k): ai_middle_words.extend([w for w in re.split(r'\s+', re.sub(r'[、：,:]', ' ', str(ai_data[k]))) if w])

    combined_middle = user_keywords + ai_middle_words
    all_words_string = " ".join(combined_middle)
    if re.search(r'空調|ファン|穴', all_words_string) or re.search(r'空調|ファン|穴', keywords):
        if re.search(r'ジャケット|ベスト', all_words_string) or re.search(r'ジャケット|ベスト', category_str):
            if "空調服・ファンウェア" not in combined_middle: combined_middle.append("空調服・ファンウェア")

    stop_words = ["なし", "無し", "不明", "特になし", "あり", "タグ付き", "無地", "薄手"]
    combined_middle.sort(key=len, reverse=True)
    accepted_words = []
    accepted_normalized = []

    for word in combined_middle:
        if not word or word in stop_words: continue
        norm_word = normalize_str(word)
        if not norm_word: continue
        is_duplicate = False
        is_short_alphanumeric = bool(re.match(r'^[A-Z0-9]{1,2}$', norm_word))

        for mw in mandatory_words_list:
            if mw == norm_word: is_duplicate = True; break
            if len(mw) >= 3 and len(norm_word) >= 3 and (norm_word in mw or mw in norm_word): is_duplicate = True; break
            if not is_short_alphanumeric:
                for suf in redundant_suffixes:
                    if mw.endswith(suf) and norm_word.endswith(suf): is_duplicate = True; break
            if is_duplicate: break
            
        if is_duplicate: continue

        for acc_norm in accepted_normalized:
            if is_short_alphanumeric:
                if acc_norm == norm_word: is_duplicate = True; break
            else:
                if norm_word in acc_norm or acc_norm in norm_word: is_duplicate = True; break
                for suf in redundant_suffixes:
                    if acc_norm.endswith(suf) and norm_word.endswith(suf): is_duplicate = True; break
                if is_duplicate: break
                
        if not is_duplicate:
            accepted_words.append(word)
            accepted_normalized.append(norm_word)

    prefix_str = " ".join(prefix_arr)
    brand_str = " ".join(brand_name_area)
    suffix_str = " ".join(suffix_arr)
    adj_str = " ".join(accepted_words)

    mandatory_len = len(prefix_str) + len(brand_str) + len(category_str) + len(suffix_str) + 4
    if ron_t_str: mandatory_len += len(ron_t_str) + 1
    max_adj_len = 130 - mandatory_len
    
    if len(adj_str) > max_adj_len and max_adj_len > 0:
        adj_str = adj_str[:max_adj_len]
        last_space = adj_str.rfind(" ")
        adj_str = adj_str[:last_space] if last_space != -1 else adj_str.strip()
    elif max_adj_len <= 0: adj_str = ""

    if ron_t_str: adj_str = ron_t_str + (" " + adj_str if adj_str else "")

    raw_title = f"{prefix_str} {brand_str} {category_str} {adj_str} {suffix_str}"
    raw_title = re.sub(r'\s+', ' ', raw_title).strip()
    
    final_words_array = raw_title.split(" ")
    unique_title_words = []
    for w in final_words_array:
        norm_w = normalize_str(w)
        if not norm_w: continue
        is_dup = False
        for ex in unique_title_words:
            norm_ex = normalize_str(ex)
            if norm_ex == norm_w: is_dup = True; break
            if len(norm_ex) >= 4 and len(norm_w) >= 4 and (norm_w in norm_ex or norm_ex in norm_w): is_dup = True; break
        
        if "QUIKSILVER" in norm_w or "QUICKSILVER" in norm_w:
            if any("QUIKSILVER" in normalize_str(ex) or "QUICKSILVER" in normalize_str(ex) for ex in unique_title_words): is_dup = True
                
        if not is_dup: unique_title_words.append(w)
            
    final_title = " ".join(unique_title_words)
    return final_title[:130].strip()

# --- AI解析処理 ---
def analyze_image_with_gemini(base64_img: str, keywords: str):
    if not GEMINI_API_KEY: return {"intro": "※AIエラー: APIキーが設定されていません"}
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
    payload = {"contents": [{"parts": [{"text": prompt}, {"inlineData": {"mimeType": "image/jpeg", "data": base64_img}}]}]}
    try:
        res = requests.post(url, json=payload)
        res.raise_for_status()
        text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text.replace("```json", "").replace("```", "").strip())
    except Exception as e:
        return {"intro": f"※AIエラー発生: {str(e)}"}


# --- APIルート群 ---
@app.get("/")
def read_root():
    return {"status": "OK"}

@app.get("/api/reserve-code")
def reserve_code(batch_name: str = "OM10000HG"):
    temp_code = f"TMP-{int(datetime.datetime.now().timestamp())}"
    return {"code": temp_code, "status": "OK", "displayCount": "新規"}

# ダッシュボード用に全データを取得するAPIを追加！
@app.get("/api/items")
def get_items():
    if not supabase: return {"status": "error", "message": "DB未接続"}
    # 日付の古い順に1000件取得
    response = supabase.table("mercari_items").select("*").order("created_at").limit(1000).execute()
    return {"status": "OK", "data": response.data}

@app.post("/api/save-item")
def save_item(item: ItemCreate, target_code: str):
    if not supabase: raise HTTPException(status_code=500, detail="DB未接続")
        
    ai_data = {"intro": ""}
    # ★ リアルタイムAI生成！
    if item.thumb_base64 and item.thumb_base64 != "DUMMY":
        ai_data = analyze_image_with_gemini(item.thumb_base64, item.keywords)
        
    description = f"数ある商品の中からこちらのページをご覧頂きまして誠にありがとうございます(^w^)b\n\n{ai_data.get('intro', '')}\n\n状態：{item.status_text}\n\n 　 ※あくまでも中古品、新品であっても保管品でございますので、微細なダメージの見落としが発生する可能性が高いです。予めご了承頂きたく願います。\n\nサイズ表記：{item.size_input}\n【寸法データ未入力（後ほど計測します）】\n\n平置きの実寸採寸でございます。多少の誤差はお許し頂けましたら幸いです。\n\n送料：全アイテム送料込み、送料無料です！\n\n※佐川急便、ゆうパケット又はヤマト運輸宅急便、ネコポスの予定でございます。選択は不可でございます。\n\n\nスニーカー、ブーツ、ビンテージジーンズ、メンズウエア、アメカジウエア、ライダースジャケット、バイク用品、スポーツウエア、アイウエアetc……..\n超超超高価買取させて頂きます！！ご相談だけでもどうぞ気軽にお問い合わせくださいませ！！量が多い場合は出張買取も承ります！！業者様、古着店様からの買取依頼も大大大歓迎です！！"
    
    # ★ 移植した完全版タイトル生成アルゴリズム！
    title = build_final_title(item, ai_data, target_code)
    
    try:
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
        
        # 保存完了と同時に生成されたタイトルを返す
        return {
            "status": "OK", 
            "code": target_code,
            "generated_title": title
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存エラー: {str(e)}")
