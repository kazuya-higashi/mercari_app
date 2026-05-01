import os
import re
import time
import json
import csv
import io
import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse  # ★画面を表示するための機能
from supabase import create_client, Client

# --- 環境設定 ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
PUBLIC_URL = "https://pub-8e4386156d26427f861486afe0381fb4.r2.dev"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ★スマホでアクセスしたときに index.html を表示する設定
@app.get("/")
def read_root():
    return FileResponse("index.html")

# --- AI・タイトル生成ロジック（GAS完全再現） ---
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

def build_description(intro, status, sz_input):
    return f"数ある商品の中からこちらのページをご覧頂きまして誠にありがとうございます(^w^)b\n\n{intro or ''}\n\n状態：{status}\n\n 　 ※あくまでも中古品、新品であっても保管品でございますので、微細なダメージの見落としが発生する可能性が高いです。予めご了承頂きたく願います。\n\nサイズ表記：{sz_input}\n【寸法データ未入力（後ほど計測します）】\n\n平置きの実寸採寸でございます。多少の誤差はお許し頂けましたら幸いです。\n\n送料：全アイテム送料込み、送料無料です！\n\n※佐川急便、ゆうパケット又はヤマト運輸宅急便、ネコポスの予定でございます。選択は不可でございます。\n\n\nスニーカー、ブーツ、ビンテージジーンズ、メンズウエア、アメカジウエア、ライダースジャケット、バイク用品、スポーツウエア、アイウエアetc……..\n超超超高価買取させて頂きます！！ご相談だけでもどうぞ気軽にお問い合わせくださいませ！！量が多い場合は出張買取も承ります！！業者様、古着店様からの買取依頼も大大大歓迎です！！"

def build_title(data, ai_data, gender_str, code):
    sz = str(data.get("sizeInput", ""))
    kw = str(data.get("keywords", ""))
    br = str(data.get("brand", "")).strip()
    cat = str(data.get("categoryText", ""))
    mat = str(data.get("materialText", "")).strip()

    prefix_arr = ["(^w^)b"]
    if "新品" in data.get("statusText", "") or "タグ付き" in kw: prefix_arr.insert(0, "新品未使用 タグ付き")
    is_big = sz.upper() in ["XL","2XL","3XL","4XL","5XL","XXL","XXXL","3L","4L"]
    if is_big: prefix_arr.insert(0, f"ビッグサイズ！{sz}サイズ")

    suffix_arr = []
    if mat: suffix_arr.append(mat)
    if ai_data.get("colors"): suffix_arr.append(str(ai_data["colors"]).replace("、", " ").replace(",", " "))
    if gender_str: suffix_arr.append(gender_str)
    if not is_big and "不明" not in sz and sz: suffix_arr.append(f"サイズ {sz}")
    suffix_arr.append(code)

    cat_parts = [p.strip() for p in re.split(r'⇒|＞|>|\||/', cat) if p.strip()]
    cat_str = cat_parts[-1] if cat_parts else ""

    mid_words = (kw + " " + str(ai_data.get("extraKeywords", "")) + " " + str(ai_data.get("shape", ""))).split()
    mid_words = [w for w in mid_words if w and w not in ["なし", "不明", "無地"]]
    
    raw = f"{' '.join(prefix_arr)} {br} {cat_str} {' '.join(mid_words)} {' '.join(suffix_arr)}"
    raw = re.sub(r'\s+', ' ', raw).strip()
    words = raw.split(" ")
    unique = []
    for w in words:
        if w not in unique: unique.append(w)
    return " ".join(unique)[:130]


# --- バックエンド通信口（RPC） ---
@app.post("/api/rpc")
async def rpc_endpoint(req: Request):
    payload = await req.json()
    method = payload.get("method")
    args = payload.get("args", [])
    
    try:
        # 1. 新規出品用の仮番号発行
        if method == "reserveNewCode":
            code = f"TMP-{int(time.time())}"
            return {"data": {"code": code, "displayCount": "新規", "error": None}}
            
        # 2. ブランド一覧（Supabaseにマスタが無ければ空リストを返す）
        elif method == "getBrandList":
            return {"data": []}
            
        # 3. 新規出品のAI生成と保存
        elif method == "processHeavyData":
            code = args[0]
            d = args[1]
            b64 = d["images"][0]["data"] if d.get("images") and d["images"][0]["data"] != "DUMMY" else ""
            
            ai_data = {}
            if b64: ai_data = analyze_image_with_gemini(b64, d.get("keywords", ""))
            
            gender = "メンズ" if "メンズ" in d.get("categoryText", "") else "レディース" if "レディース" in d.get("categoryText", "") else ""
            title = build_title(d, ai_data, gender, code)
            desc = build_description(ai_data.get("intro", ""), d.get("statusText", ""), d.get("sizeInput", ""))
            
            # 画像ファイル名の構築（最大20枚）
            images = [f"{code}-{i+1}.jpg" for i in range(20) if i < len(d.get("images", []))]
            
            supabase.table("mercari_items").insert({
                "item_code": code, "brand": d.get("brand", ""), "keywords": d.get("keywords", ""),
                "material": d.get("materialText", ""), "status_text": d.get("statusText", ""),
                "size_input": d.get("sizeInput", ""), "category_text": d.get("categoryText", ""),
                "title": title, "description": desc, "images": images,
                "pack_status": "", "packing_photo": ""
            }).execute()
            
            return {"data": {"code": code, "error": None}}

        # 4. 未採寸リストの取得
        elif method == "getPendingMeasurements":
            res = supabase.table("mercari_items").select("*").execute()
            items = []
            for r in res.data:
                if r.get("item_code", "").startswith("TMP-") or "【寸法データ未入力" in r.get("description", ""):
                    img = r.get("images", [])
                    thumb = img[0] if img else ""
                    items.append({
                        "code": r["item_code"], "brand": r.get("brand", ""), 
                        "thumbUrl": f"{PUBLIC_URL}/{thumb}" if thumb else "", 
                        "categoryText": r.get("category_text", "")
                    })
            return {"data": items}
            
        # 5. 採寸データの保存（ラグラン・パンツ対応）
        elif method == "saveMeasurement":
            code = args[0]
            dims = args[1]
            res = supabase.table("mercari_items").select("*").eq("item_code", code).execute()
            if not res.data: raise Exception("アイテムが見つかりません")
            target = res.data[0]
            
            cat = target.get("category_text", "")
            old_desc = target.get("description", "")
            
            is_raglan = dims.startswith("R ")
            clean_dims = dims[2:].strip() if is_raglan else dims
            d_arr = clean_dims.replace(",", " ").replace("/", " ").split()
            
            formatted = ""
            if "パンツ" in cat or "ボトムス" in cat:
                formatted = f"ウエスト：{d_arr[0] if len(d_arr)>0 else ''}cm\n全長：{d_arr[1] if len(d_arr)>1 else ''}cm\n股下：{d_arr[2] if len(d_arr)>2 else ''}cm\n裾幅：{d_arr[3] if len(d_arr)>3 else ''}cm\nわたり幅：{d_arr[4] if len(d_arr)>4 else '-'}cm"
            elif is_raglan:
                formatted = f"肩幅：0cm ※ラグランスリーブ\n着丈：{d_arr[0] if len(d_arr)>0 else ''}cm\n身幅：{d_arr[1] if len(d_arr)>1 else ''}cm\n裄丈：{d_arr[2] if len(d_arr)>2 else ''}cm"
            else:
                formatted = f"肩幅：{d_arr[0] if len(d_arr)>0 else ''}cm\n着丈：{d_arr[1] if len(d_arr)>1 else ''}cm\n身幅：{d_arr[2] if len(d_arr)>2 else ''}cm\n袖丈：{d_arr[3] if len(d_arr)>3 else ''}cm"
                
            new_desc = old_desc.replace("【寸法データ未入力（後ほど計測します）】", formatted)
            if old_desc == new_desc:
                new_desc = f"【実寸サイズ】\n{formatted}\n\n{old_desc}"
                
            supabase.table("mercari_items").update({"description": new_desc}).eq("item_code", code).execute()
            return {"data": "OK"}
            
        # 6. 未梱包リストの取得
        elif method == "getPendingPackings":
            res = supabase.table("mercari_items").select("*").neq("pack_status", "梱包完了").execute()
            items = []
            for r in res.data:
                # 採寸済み（寸法データ未入力が消えている）ものをリストアップ
                if not r.get("item_code", "").startswith("TMP-") and "【寸法データ未入力" not in r.get("description", ""):
                    img = r.get("images", [])
                    thumb = img[0] if img else ""
                    items.append({
                        "code": r["item_code"], "brand": r.get("brand", ""), 
                        "thumbUrl": f"{PUBLIC_URL}/{thumb}" if thumb else "", 
                        "categoryText": r.get("category_text", "")
                    })
            return {"data": items}
            
        # 7. 梱包画像の保存とOM番号の正式付与
        elif method == "savePackingPhotoAndAssignCode":
            code = args[0]
            res = supabase.table("mercari_items").select("*").eq("item_code", code).execute()
            if not res.data: raise Exception("アイテムが見つかりません")
            target = res.data[0]
            
            final_code = code
            is_new = False
            
            if code.startswith("TMP-"):
                # Supabaseから現在のOM番号の最大値を探して+1する
                all_om = supabase.table("mercari_items").select("item_code").like("item_code", "OM%HG").execute()
                nums = [int(re.search(r'\d+', c["item_code"]).group()) for c in all_om.data if re.search(r'\d+', c["item_code"])]
                next_num = max(nums) + 1 if nums else 10000
                final_code = f"OM{next_num}HG"
                is_new = True
                
                new_title = target.get("title", "").replace(code, final_code)
                new_images = [img.replace(code, final_code) if type(img)==str else img for img in target.get("images", [])]
                
                supabase.table("mercari_items").update({
                    "item_code": final_code, "title": new_title, "images": new_images, "pack_status": "梱包完了"
                }).eq("item_code", code).execute()
            else:
                supabase.table("mercari_items").update({"pack_status": "梱包完了"}).eq("item_code", code).execute()
            
            return {"data": {"status": "OK", "finalCode": final_code, "isNewlyAssigned": is_new}}

        # 8. ダッシュボード管理データの取得
        elif method == "getAdminData":
            res = supabase.table("mercari_items").select("*").order("created_at").execute()
            item_map = {}
            for r in res.data:
                c = r["item_code"]
                img = r.get("images", [])
                thumb = img[0] if img else ""
                item_map[c] = {
                    "count": 1, "row": 0, "status": "出品完了", "dims": "測定済" if "【実寸" in r.get("description", "") else "",
                    "brand": r.get("brand", ""), "statusText": r.get("status_text", ""),
                    "title": r.get("title", ""), "desc": r.get("description", ""),
                    "thumbUrl": f"{PUBLIC_URL}/{thumb}" if thumb else "",
                    "packStatus": r.get("pack_status", ""), "shipStatus": "",
                    "missingImages": [], "hasMissingImage": False
                }
            return {"data": {"config": {"sheetName": "DB"}, "itemMap": item_map, "allSheets": ["DB"], "currentViewSheet": "DB"}}

        # 9. CSV＆ZIP一括ダウンロード用データの構築
        elif method == "getBatchDownloadData":
            res = supabase.table("mercari_items").select("*").execute()
            
            output = io.StringIO()
            writer = csv.writer(output, quoting=csv.QUOTE_ALL)
            writer.writerow(["商品画像名_1","商品画像名_2","商品画像名_3","商品画像名_4","商品画像名_5","商品画像名_6","商品画像名_7","商品画像名_8","商品画像名_9","商品画像名_10","商品画像名_11","商品画像名_12","商品画像名_13","商品画像名_14","商品画像名_15","商品画像名_16","商品画像名_17","商品画像名_18","商品画像名_19","商品画像名_20","商品名","商品説明","SKU1_種類","SKU1_在庫数","SKU1_商品管理コード","SKU1_JANコード","ブランドID","販売価格","カテゴリID","商品の状態","配送方法","発送元の地域","発送までの日数","商品ステータス"])
            
            images_to_download = []
            for r in res.data:
                if r.get("item_code", "").startswith("TMP-"): continue
                
                imgs = r.get("images", [])
                row_imgs = [imgs[i] if i < len(imgs) else "" for i in range(20)]
                for img in imgs:
                    if img: images_to_download.append(img)
                
                status_map = { "新品、未使用": "1", "未使用に近い": "2", "目立った傷や汚れなし": "3", "やや傷や汚れあり": "4", "傷や汚れあり": "5", "全体的に状態が悪い": "6" }
                status_id = status_map.get(r.get("status_text", ""), "3")
                
                row_data = row_imgs + [
                    r.get("title", ""), r.get("description", ""), r.get("size_input", "").strip(), "1",
                    r.get("item_code", ""), "", r.get("brand_id", ""), "5999", r.get("category_id", ""),
                    status_id, "1", "jp07", "1", "1"
                ]
                writer.writerow(row_data)
                
            return {"data": {"csvString": output.getvalue(), "images": images_to_download}}

        # 10. 管理画面用：画像一覧の取得
        elif method == "getItemImagesForAdmin":
            code = args[1]
            res = supabase.table("mercari_items").select("images").eq("item_code", code).execute()
            images = []
            if res.data:
                for img in res.data[0].get("images", []):
                    images.append({"name": img, "url": f"{PUBLIC_URL}/{img}"})
            return {"data": {"images": images}}

        # 11. データの強制修正など（簡易対応）
        elif method in ["updateItemTextData", "deleteItemData"]:
            return {"data": "OK"}
            
        else:
            return {"data": "OK"}
            
    except Exception as e:
        return {"error": str(e)}
