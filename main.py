import os
import re
import time
import json
import csv
import io
import base64
import requests
import unicodedata
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from supabase import create_client, Client

# --- 環境設定 ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
# ★追加：APIキーを裏側に直接埋め込みました！これで環境変数漏れでも絶対に動きます。
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyA3oxQCe8OAiU571mhSWr6FZuE26rVxZ74")
PUBLIC_URL = "https://pub-8e4386156d26427f861486afe0381fb4.r2.dev"

# ★GASからブランドマスタを引っ張ってくるための設定（ご指定のURLに更新済です）
SPREADSHEET_ID = '1kpKObKqse7sfcG_VByhF1uWeMRTdFYPAu4VS0eqh6PU'
GAS_API_URL = "https://script.google.com/macros/s/AKfycbwX3CsxVEfZ1OUa5ytPkBmsElpihy6hKrm_vzW_KOlyX25Xim6jLNmW3fEflUF16B37/exec"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return FileResponse("index.html")

# ==========================================
# 共通機能・設定管理
# ==========================================
def normalize_str(s):
    return unicodedata.normalize('NFKC', str(s)).strip() if s else ""

def get_batch_settings():
    try:
        res = supabase.table("mercari_items").select("description").eq("item_code", "SYSTEM_SETTINGS").execute()
        if res.data and res.data[0].get("description"):
            return json.loads(res.data[0]["description"])
    except:
        pass
    return {
        "sheetName": "シート1",
        "prefix": "OM",
        "start": 10000,
        "end": 19999,
        "suffix": "HG"
    }

def save_batch_settings(data):
    try:
        res = supabase.table("mercari_items").select("item_code").eq("item_code", "SYSTEM_SETTINGS").execute()
        if res.data:
            supabase.table("mercari_items").update({"description": json.dumps(data)}).eq("item_code", "SYSTEM_SETTINGS").execute()
        else:
            supabase.table("mercari_items").insert({
                "item_code": "SYSTEM_SETTINGS", "title": "SYSTEM",
                "description": json.dumps(data), "batch_name": "SYSTEM"
            }).execute()
    except:
        pass

def assign_real_code_internal(sheetName, oldCode):
    config = get_batch_settings()
    prefix = config.get("prefix", "OM")
    suffix = config.get("suffix", "HG")
    start = int(config.get("start", 10000))
    end = int(config.get("end", 19999))
    
    norm_sheet = normalize_str(sheetName)
    m = re.match(r'^([A-Za-z]+)(\d+)([A-Za-z]+)[〜～\-]+([A-Za-z]+)(\d+)([A-Za-z]+)$', norm_sheet)
    if m:
        prefix = m.group(1)
        start = int(m.group(2))
        suffix = m.group(3)
        end = int(m.group(5))
        
    res = supabase.table("mercari_items").select("item_code").eq("batch_name", sheetName).execute()
    existingNumbers = set()
    for r in res.data:
        c = r["item_code"]
        if str(c).startswith(prefix) and str(c).endswith(suffix):
            numMatch = re.search(r'\d+', str(c))
            if numMatch:
                existingNumbers.add(int(numMatch.group(0)))
                
    nextNum = -1
    for i in range(start, end + 1):
        if i not in existingNumbers:
            nextNum = i
            break
            
    if nextNum == -1:
        raise Exception("設定された範囲を完全に使い切りました。")
        
    return f"{prefix}{nextNum}{suffix}"

# --- AI・タイトル生成ロジック ---
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
        # ★修正：AIが答えるまでの猶予を60秒に延長し、どんな返事が来ても「文章」だけを確実に抜き取るように頑丈化
        res = requests.post(url, json=payload, timeout=60)
        res.raise_for_status()
        data = res.json()
        if "candidates" not in data or not data["candidates"]:
            return {"intro": "※AIエラー: 生成結果が空です。"}
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        
        text = text.replace("```json", "").replace("```", "").strip()
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            text = m.group(0)
            
        try:
            return json.loads(text)
        except Exception as e:
            return {"intro": f"※AIパースエラー: {str(e)} / AIの返答: {text[:50]}..."}
    except Exception as e:
        return {"intro": f"※AI通信エラー: {str(e)}"}

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
        # 1. バッチ作成
        if method == "saveBatchSettings":
            d = args[0]
            save_batch_settings(d)
            return {"data": "OK"}

        # 2. 空き枠の確認
        elif method == "checkBatchFull":
            targetSheetName = args[0] if args and args[0] else None
            config = get_batch_settings()
            sheetName = targetSheetName if targetSheetName else config.get("sheetName", "シート1")
            
            start = int(config.get("start", 10000))
            end = int(config.get("end", 19999))
            
            norm_sheet = normalize_str(sheetName)
            m = re.match(r'^([A-Za-z]+)(\d+)([A-Za-z]+)[〜～\-]+([A-Za-z]+)(\d+)([A-Za-z]+)$', norm_sheet)
            if m:
                start = int(m.group(2))
                end = int(m.group(5))
                
            maxItems = end - start + 1
            
            res = supabase.table("mercari_items").select("item_code").eq("batch_name", sheetName).execute()
            valid_items = [r for r in res.data if r["item_code"] != "SYSTEM_SETTINGS" and not str(r["item_code"]).startswith("BATCH-")]
            currentItems = len(valid_items)
            
            return {"data": currentItems >= maxItems}

        # 3. 新規出品用の仮番号発行
        elif method == "reserveNewCode":
            targetSheetName = args[0] if args and args[0] else None
            config = get_batch_settings()
            sheetName = targetSheetName if targetSheetName else config.get("sheetName", "シート1")
            
            if not sheetName:
                return {"data": {"code": None, "error": "対象のタブが存在しません。管理画面から設定してください。"}}
                
            start = int(config.get("start", 10000))
            end = int(config.get("end", 19999))
            
            norm_sheet = normalize_str(sheetName)
            m = re.match(r'^([A-Za-z]+)(\d+)([A-Za-z]+)[〜～\-]+([A-Za-z]+)(\d+)([A-Za-z]+)$', norm_sheet)
            if m:
                start = int(m.group(2))
                end = int(m.group(5))
                
            maxItems = end - start + 1
            
            res = supabase.table("mercari_items").select("item_code").eq("batch_name", sheetName).execute()
            valid_items = [r for r in res.data if r["item_code"] != "SYSTEM_SETTINGS" and not str(r["item_code"]).startswith("BATCH-")]
            currentItems = len(valid_items)
            
            if currentItems >= maxItems:
                return {"data": {"code": None, "error": "設定の上限数を超えているため新たに枠を作ってください"}}
                
            tempCode = f"TMP-{int(time.time() * 1000)}"
            count = currentItems + 2
            return {"data": {"code": tempCode, "displayCount": count, "error": None}}
            
        # 4. ブランド一覧（GASから直接取得）
        elif method == "getBrandList":
            try:
                response = requests.get(f"{GAS_API_URL}?method=getBrandList")
                response.raise_for_status()
                brand_data = response.json()
                return {"data": brand_data.get("data", [])}
            except Exception as e:
                print(f"Brand list fetch error: {e}")
                return {"data": []}
            
        # 5. 新規出品のAI生成と保存
        elif method == "processHeavyData":
            code = args[0]
            d = args[1]
            targetSheetName = args[2] if len(args) > 2 and args[2] else None
            config = get_batch_settings()
            sheetName = targetSheetName if targetSheetName else config.get("sheetName", "シート1")
            
            b64 = d["images"][0]["data"] if d.get("images") and d["images"][0]["data"] != "DUMMY" else ""
            
            ai_data = {}
            if b64: 
                try:
                    ai_data = analyze_image_with_gemini(b64, d.get("keywords", ""))
                except Exception as e:
                    ai_data = {"intro": f"※AI内部エラー: {str(e)}"}
            else:
                ai_data = {"intro": "※画像が空のためAI生成をスキップしました"}
            
            gender = "メンズ" if "メンズ" in d.get("categoryText", "") else "レディース" if "レディース" in d.get("categoryText", "") else ""
            title = build_title(d, ai_data, gender, code)
            desc = build_description(ai_data.get("intro", ""), d.get("statusText", ""), d.get("sizeInput", ""))
            
            images = [f"{code}-{i+1}.jpg" for i in range(20) if i < len(d.get("images", []))]
            
            supabase.table("mercari_items").upsert({
                "batch_name": sheetName,
                "item_code": code, "brand": d.get("brand", ""), "keywords": d.get("keywords", ""),
                "material": d.get("materialText", ""), "status_text": d.get("statusText", ""),
                "size_input": d.get("sizeInput", ""), "category_text": d.get("categoryText", ""),
                "title": title, "description": desc, "images": images,
                "pack_status": "", "packing_photo": ""
            }).execute()
            
            return {"data": {"code": code, "error": None}}

        # 6. 未採寸リストの取得
        elif method == "getPendingMeasurements":
            targetSheetName = args[0] if args and args[0] else None
            config = get_batch_settings()
            sheetName = targetSheetName if targetSheetName else config.get("sheetName", "シート1")
            
            query = supabase.table("mercari_items").select("*").eq("batch_name", sheetName)
            res = query.execute()
            
            items = []
            for r in res.data:
                c = str(r.get("item_code", ""))
                if c == "SYSTEM_SETTINGS" or c.startswith("BATCH-"): continue
                if c.startswith("TMP-") or "【寸法データ未入力" in str(r.get("description", "")):
                    img = r.get("images", [])
                    thumb = img[0] if img else ""
                    items.append({
                        "code": c, "brand": r.get("brand", ""), 
                        "thumbUrl": f"{PUBLIC_URL}/{thumb}" if thumb else "", 
                        "categoryText": r.get("category_text", "")
                    })
            return {"data": items}
            
        # 7. 採寸データの保存
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
            
        # 8. 未梱包リストの取得
        elif method == "getPendingPackings":
            targetSheetName = args[0] if args and args[0] else None
            config = get_batch_settings()
            sheetName = targetSheetName if targetSheetName else config.get("sheetName", "シート1")
            
            query = supabase.table("mercari_items").select("*").eq("batch_name", sheetName).neq("pack_status", "梱包完了")
            res = query.execute()
            
            items = []
            for r in res.data:
                c = str(r.get("item_code", ""))
                if c == "SYSTEM_SETTINGS" or c.startswith("BATCH-"): continue
                if not c.startswith("TMP-") and "【寸法データ未入力" not in str(r.get("description", "")):
                    img = r.get("images", [])
                    thumb = img[0] if img else ""
                    items.append({
                        "code": c, "brand": r.get("brand", ""), 
                        "thumbUrl": f"{PUBLIC_URL}/{thumb}" if thumb else "", 
                        "categoryText": r.get("category_text", "")
                    })
            return {"data": items}
            
        # 9. 梱包画像の保存とOM番号の正式付与
        elif method == "savePackingPhotoAndAssignCode":
            code = args[0]
            targetSheetName = args[2] if len(args) > 2 and args[2] else None
            config = get_batch_settings()
            sheetName = targetSheetName if targetSheetName else config.get("sheetName", "シート1")
            
            res = supabase.table("mercari_items").select("*").eq("item_code", code).execute()
            if not res.data: raise Exception("アイテムが見つかりません")
            target = res.data[0]
            
            final_code = code
            is_new = False
            
            if code.startswith("TMP-"):
                final_code = assign_real_code_internal(sheetName, code)
                is_new = True
                
                new_title = str(target.get("title", "")).replace(code, final_code)
                new_images = [str(img).replace(code, final_code) for img in target.get("images", [])]
                
                supabase.table("mercari_items").update({
                    "item_code": final_code, "title": new_title, "images": new_images, "pack_status": "梱包完了"
                }).eq("item_code", code).execute()
            else:
                supabase.table("mercari_items").update({"pack_status": "梱包完了"}).eq("item_code", code).execute()
            
            return {"data": {"status": "OK", "finalCode": final_code, "isNewlyAssigned": is_new}}

        # 10. ダッシュボード管理データの取得
        elif method == "getAdminData":
            targetSheetName = args[0] if args and args[0] else None
            config = get_batch_settings()
            activeSheetName = config.get("sheetName", "シート1")
            sheetNameToLoad = targetSheetName if targetSheetName else activeSheetName

            res_all = supabase.table("mercari_items").select("batch_name").execute()
            seen = set()
            allSheets = []
            for r in res_all.data:
                b = str(r.get("batch_name", ""))
                if b and b != "SYSTEM" and b not in seen:
                    seen.add(b)
                    allSheets.append(b)
            
            if activeSheetName and activeSheetName not in seen:
                allSheets.append(activeSheetName)
                
            allSheets = sorted(allSheets)

            res = supabase.table("mercari_items").select("*").eq("batch_name", sheetNameToLoad).order("created_at").execute()
            
            itemMap = {}
            for i, r in enumerate(res.data):
                code = str(r["item_code"])
                if code == "SYSTEM_SETTINGS" or code.startswith("BATCH-"): continue
                
                img = r.get("images", [])
                thumbName = img[0] if img and isinstance(img, list) and len(img) > 0 else ""
                desc = str(r.get("description", ""))
                
                dims_status = "測定済" if "【実寸" in desc or "【寸法データ未入力" not in desc else ""
                
                itemMap[code] = {
                    "count": 1, "row": i + 2, "status": "出品完了", "dims": dims_status,
                    "brand": r.get("brand", "") or "ブランド不明", "statusText": r.get("status_text", ""),
                    "title": r.get("title", ""), "desc": desc,
                    "thumbUrl": f"{PUBLIC_URL}/{thumbName}" if thumbName else "",
                    "packStatus": r.get("pack_status", ""), "shipStatus": "",
                    "missingImages": [], "hasMissingImage": False
                }
                
            return {"data": {
                "config": config,
                "itemMap": itemMap,
                "allSheets": allSheets,
                "activeSheet": activeSheetName,
                "currentViewSheet": sheetNameToLoad
            }}

        # 11. CSV＆ZIP一括ダウンロード用データの構築
        elif method == "getBatchDownloadData":
            targetSheetName = args[0] if args and args[0] else None
            config = get_batch_settings()
            sheetName = targetSheetName if targetSheetName else config.get("sheetName", "シート1")
            
            query = supabase.table("mercari_items").select("*").eq("batch_name", sheetName)
            res = query.execute()
            
            output = io.StringIO()
            writer = csv.writer(output, quoting=csv.QUOTE_ALL)
            writer.writerow(["商品画像名_1","商品画像名_2","商品画像名_3","商品画像名_4","商品画像名_5","商品画像名_6","商品画像名_7","商品画像名_8","商品画像名_9","商品画像名_10","商品画像名_11","商品画像名_12","商品画像名_13","商品画像名_14","商品画像名_15","商品画像名_16","商品画像名_17","商品画像名_18","商品画像名_19","商品画像名_20","商品名","商品説明","SKU1_種類","SKU1_在庫数","SKU1_商品管理コード","SKU1_JANコード","ブランドID","販売価格","カテゴリID","商品の状態","配送方法","発送元の地域","発送までの日数","商品ステータス"])
            
            images_to_download = []
            for r in res.data:
                c = str(r.get("item_code", ""))
                if c.startswith("TMP-") or c == "SYSTEM_SETTINGS" or c.startswith("BATCH-"): continue
                
                imgs = r.get("images", [])
                row_imgs = [imgs[i] if i < len(imgs) else "" for i in range(20)]
                for img in imgs:
                    if img: images_to_download.append(str(img).strip())
                
                status_map = { "新品、未使用": "1", "未使用に近い": "2", "目立った傷や汚れなし": "3", "やや傷や汚れあり": "4", "傷や汚れあり": "5", "全体的に状態が悪い": "6" }
                status_id = status_map.get(str(r.get("status_text", "")), "3")
                
                row_data = row_imgs + [
                    str(r.get("title", "")), str(r.get("description", "")), str(r.get("size_input", "")).strip(), "1",
                    c, "", str(r.get("brand_id", "")), "5999", str(r.get("category_id", "")),
                    status_id, "1", "jp07", "1", "1"
                ]
                writer.writerow(row_data)
                
            return {"data": {"csvString": output.getvalue(), "images": images_to_download}}

        # 12. 画像一覧の取得
        elif method == "getItemImagesForAdmin":
            code = args[1]
            res = supabase.table("mercari_items").select("images").eq("item_code", code).execute()
            images = []
            if res.data:
                for img in res.data[0].get("images", []):
                    if img: images.append({"name": str(img), "url": f"{PUBLIC_URL}/{img}"})
            return {"data": {"images": images}}

        # 13. 管理画面からの画像削除
        elif method == "deleteAdminImage":
            sheetName = args[0]
            code = args[1]
            imgName = args[2]
            res = supabase.table("mercari_items").select("images").eq("item_code", code).execute()
            if res.data:
                imgs = res.data[0].get("images", [])
                if imgName in imgs:
                    imgs.remove(imgName)
                    supabase.table("mercari_items").update({"images": imgs}).eq("item_code", code).execute()
            return {"data": "OK"}

        # 14. 画像の追加
        elif method == "addAdminImages":
            sheetName = args[0]
            code = args[1]
            b64_list = args[2]
            res = supabase.table("mercari_items").select("images").eq("item_code", code).execute()
            if res.data:
                imgs = res.data[0].get("images", [])
                start_idx = len(imgs)
                for i in range(len(b64_list)):
                    imgs.append(f"{code}-{start_idx + i + 1}.jpg")
                supabase.table("mercari_items").update({"images": imgs}).eq("item_code", code).execute()
            return {"data": "OK"}

        # 15. 画像の一括入れ替え
        elif method == "replaceItemImages":
            sheetName = args[0]
            itemCode = args[1]
            b64_list = args[2]
            new_imgs = [f"{itemCode}-{i+1}.jpg" for i in range(len(b64_list))]
            supabase.table("mercari_items").update({"images": new_imgs}).eq("item_code", itemCode).execute()
            return {"data": "OK"}

        # 16. テキストデータの更新
        elif method == "updateItemTextData":
            code = args[1]
            supabase.table("mercari_items").update({
                "title": str(args[2]), "description": str(args[3]), "status_text": str(args[5])
            }).eq("item_code", code).execute()
            return {"data": "OK"}
            
        # 17. ★修正：AI再生成の即時反映とエラー内容の具体的な通知
        elif method == "retryAIGeneration":
            code = args[1]
            new_status = args[2]
            res = supabase.table("mercari_items").select("*").eq("item_code", code).execute()
            if res.data:
                item = res.data[0]
                imgs = item.get("images", [])
                if imgs and imgs[0]:
                    img_url = f"{PUBLIC_URL}/{imgs[0]}"
                    try:
                        img_res = requests.get(img_url, timeout=15)
                        img_res.raise_for_status()
                        b64 = base64.b64encode(img_res.content).decode('utf-8')
                        ai_data = analyze_image_with_gemini(b64, str(item.get("keywords", "")))
                        
                        if "※AIエラー" in str(ai_data):
                            return {"error": f"AI生成自体は完了しましたが、中身がエラーです: {ai_data.get('intro')}"}
                        
                        gender = "メンズ" if "メンズ" in str(item.get("category_text", "")) else "レディース" if "レディース" in str(item.get("category_text", "")) else ""
                        status_to_use = new_status if new_status else str(item.get("status_text", ""))
                        title = build_title(item, ai_data, gender, code)
                        desc = build_description(ai_data.get("intro", ""), status_to_use, str(item.get("size_input", "")))
                        
                        supabase.table("mercari_items").update({
                            "title": title, "description": desc, "status_text": status_to_use
                        }).eq("item_code", code).execute()
                        
                        # ★画面のテキストボックスを即座に書き換えるために、作った文章を直接返す！
                        return {"data": {"title": title, "desc": desc}}
                    except Exception as e:
                        return {"error": f"画像取得またはAI生成エラー: {str(e)}"}
                else:
                    return {"error": "アイテムに画像が登録されていないため再生成できません。"}
            return {"error": "対象のアイテムがデータベースに見つかりません。"}

        # 18. 管理番号の強制修正
        elif method == "fixManagementCode":
            old_code = args[1]
            new_code = args[2]
            res = supabase.table("mercari_items").select("*").eq("item_code", old_code).execute()
            if res.data:
                item = res.data[0]
                new_title = str(item.get("title", "")).replace(old_code, new_code)
                new_images = [str(img).replace(old_code, new_code) for img in item.get("images", [])]
                supabase.table("mercari_items").update({
                    "item_code": new_code, "title": new_title, "images": new_images
                }).eq("item_code", old_code).execute()
            return {"data": "OK"}

        # 19. 梱包状態を未梱包に戻す
        elif method == "revertPackingStatus":
            code = args[1]
            supabase.table("mercari_items").update({"pack_status": ""}).eq("item_code", code).execute()
            return {"data": "OK"}

        # 20. アイテムのバッチ移動
        elif method == "moveItemsToBatch":
            target_batch = args[1]
            codes = args[2]
            for c in codes:
                supabase.table("mercari_items").update({"batch_name": target_batch}).eq("item_code", c).execute()
            return {"data": "OK"}

        # 21. インセンティブ集計
        elif method == "fetchIncentiveData":
            return {"data": []}

        # 22. アイテムの削除
        elif method == "deleteItemData":
            code = args[1]
            supabase.table("mercari_items").delete().eq("item_code", code).execute()
            return {"data": "OK"}

        # 23. 現在のバッチの一括削除
        elif method == "deleteBatch":
            batch_name = args[0]
            if not batch_name or batch_name == "デフォルトバッチ":
                return {"data": "エラー: この枠は削除できません"}
            
            supabase.table("mercari_items").delete().eq("batch_name", batch_name).execute()
            
            config = get_batch_settings()
            if config.get("sheetName") == batch_name:
                supabase.table("mercari_items").delete().eq("item_code", "SYSTEM_SETTINGS").execute()
                
            return {"data": "OK"}
            
        # 24. ★新規追加：長押しで順番を並び替えた際、その順番通りにDBを上書きする
        elif method == "reorderItemImages":
            sheetName = args[0]
            itemCode = args[1]
            newOrder = args[2]
            
            updateArr = []
            for i in range(20):
                updateArr.append(newOrder[i] if i < len(newOrder) else "")
                
            supabase.table("mercari_items").update({"images": updateArr}).eq("item_code", itemCode).execute()
            return {"data": "OK"}
            
        else:
            return {"data": "OK"}
            
    except Exception as e:
        return {"error": str(e)}
