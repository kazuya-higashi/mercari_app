import os
import re
import time
import json
import csv
import io
import base64
import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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

@app.get("/")
def read_root():
    return FileResponse("index.html")

# --- AI・タイトル生成ロジック（変更なし） ---
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
        return json.loads(text.replace("
```json", "").replace("```", "").strip())
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
        # ==========================================
        # 1. サーバー側に「現在作業中のバッチ」を記憶・呼び出しする処理
        # ==========================================
        def get_saved_active_batch():
            res = supabase.table("mercari_items").select("batch_name").eq("item_code", "SYSTEM_ACTIVE_BATCH").execute()
            if res.data and res.data[0].get("batch_name"):
                return res.data[0]["batch_name"]
            return ""

        def save_active_batch(batch_name):
            supabase.table("mercari_items").upsert({
                "item_code": "SYSTEM_ACTIVE_BATCH",
                "batch_name": batch_name,
                "title": "SYSTEM_DUMMY"
            }).execute()

        # ==========================================
        # 以下、GAS関数の完全再現
        # ==========================================
        
        if method == "checkBatchFull":
            # 引数がない場合は、サーバーに記憶しているバッチを呼び出す
            batch_name = args[0] if args and args[0] else get_saved_active_batch()
            if not batch_name: return {"data": False}
            
            # ダミーデータ（BATCH-やSYSTEM_）を除外して、純粋なアイテム数をカウントする（これでバグは起きません）
            res = supabase.table("mercari_items").select("item_code").eq("batch_name", batch_name).execute()
            valid_items = [r for r in res.data if not str(r["item_code"]).startswith("BATCH-") and not str(r["item_code"]).startswith("SYSTEM_")]
            current_count = len(valid_items)
            
            # バッチ名（OM100HG〜OM200HG）から上限を計算
            m = re.match(r'^([A-Za-z]+)(\d+)([A-Za-z]+)〜([A-Za-z]+)(\d+)([A-Za-z]+)$', batch_name)
            if m:
                start = int(m.group(2))
                end = int(m.group(5))
                max_items = end - start + 1
                return {"data": current_count >= max_items}
            return {"data": False}

        elif method == "saveBatchSettings":
            d = args[0]
            batch_name = d.get("sheetName")
            # 新しいバッチを作成したら、それを「現在作業中のバッチ」として記憶する
            res = supabase.table("mercari_items").select("item_code").eq("item_code", f"BATCH-{batch_name}").execute()
            if not res.data:
                supabase.table("mercari_items").insert({
                    "item_code": f"BATCH-{batch_name}", 
                    "batch_name": batch_name, 
                    "title": "BATCH_DUMMY"
                }).execute()
            save_active_batch(batch_name)
            return {"data": "OK"}

        elif method == "reserveNewCode":
            code = f"TMP-{int(time.time())}"
            return {"data": {"code": code, "displayCount": "新規", "error": None}}
            
        elif method == "getBrandList":
            return {"data": []}
            
        elif method == "processHeavyData":
            code = args[0]
            d = args[1]
            batch_name = args[2] if len(args) > 2 and args[2] else get_saved_active_batch()
            b64 = d["images"][0]["data"] if d.get("images") and d["images"][0]["data"] != "DUMMY" else ""
            
            ai_data = {}
            if b64: ai_data = analyze_image_with_gemini(b64, d.get("keywords", ""))
            
            gender = "メンズ" if "メンズ" in d.get("categoryText", "") else "レディース" if "レディース" in d.get("categoryText", "") else ""
            title = build_title(d, ai_data, gender, code)
            desc = build_description(ai_data.get("intro", ""), d.get("statusText", ""), d.get("sizeInput", ""))
            
            images = [f"{code}-{i+1}.jpg" for i in range(20) if i < len(d.get("images", []))]
            
            supabase.table("mercari_items").insert({
                "batch_name": batch_name,
                "item_code": code, "brand": d.get("brand", ""), "keywords": d.get("keywords", ""),
                "material": d.get("materialText", ""), "status_text": d.get("statusText", ""),
                "size_input": d.get("sizeInput", ""), "category_text": d.get("categoryText", ""),
                "title": title, "description": desc, "images": images,
                "pack_status": "", "packing_photo": ""
            }).execute()
            
            return {"data": {"code": code, "error": None}}

        elif method == "getPendingMeasurements":
            batch_name = args[0] if args and args[0] else get_saved_active_batch()
            query = supabase.table("mercari_items").select("*")
            if batch_name: query = query.eq("batch_name", batch_name)
            res = query.execute()
            
            items = []
            for r in res.data:
                if str(r.get("item_code", "")).startswith("BATCH-") or str(r.get("item_code", "")).startswith("SYSTEM_"): continue
                if str(r.get("item_code", "")).startswith("TMP-") or "【寸法データ未入力" in r.get("description", ""):
                    img = r.get("images", [])
                    thumb = img[0] if img else ""
                    items.append({
                        "code": r["item_code"], "brand": r.get("brand", ""), 
                        "thumbUrl": f"{PUBLIC_URL}/{thumb}" if thumb else "", 
                        "categoryText": r.get("category_text", "")
                    })
            return {"data": items}
            
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
            
        elif method == "getPendingPackings":
            batch_name = args[0] if args and args[0] else get_saved_active_batch()
            query = supabase.table("mercari_items").select("*").neq("pack_status", "梱包完了")
            if batch_name: query = query.eq("batch_name", batch_name)
            res = query.execute()
            
            items = []
            for r in res.data:
                if str(r.get("item_code", "")).startswith("BATCH-") or str(r.get("item_code", "")).startswith("SYSTEM_"): continue
                if not str(r.get("item_code", "")).startswith("TMP-") and "【寸法データ未入力" not in r.get("description", ""):
                    img = r.get("images", [])
                    thumb = img[0] if img else ""
                    items.append({
                        "code": r["item_code"], "brand": r.get("brand", ""), 
                        "thumbUrl": f"{PUBLIC_URL}/{thumb}" if thumb else "", 
                        "categoryText": r.get("category_text", "")
                    })
            return {"data": items}
            
        elif method == "savePackingPhotoAndAssignCode":
            code = args[0]
            res = supabase.table("mercari_items").select("*").eq("item_code", code).execute()
            if not res.data: raise Exception("アイテムが見つかりません")
            target = res.data[0]
            
            final_code = code
            is_new = False
            
            if code.startswith("TMP-"):
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

        elif method == "getAdminData":
            # 引数(target)が空の場合は、サーバーの記憶(最後に開いたバッチ)を呼び出す！
            req_batch = args[0] if args and args[0] else get_saved_active_batch()
            
            # 全バッチ名の取得
            res_all = supabase.table("mercari_items").select("batch_name").execute()
            all_batches = sorted(list(set([r["batch_name"] for r in res_all.data if r.get("batch_name") and not str(r["batch_name"]).startswith("SYSTEM_")])))
            if not all_batches:
                all_batches = ["デフォルトバッチ"]
                
            active_batch = req_batch if req_batch in all_batches else all_batches[-1]
            
            # 記憶を確実に最新に更新する
            save_active_batch(active_batch)
            
            res = supabase.table("mercari_items").select("*").eq("batch_name", active_batch).order("created_at").execute()
            
            item_map = {}
            for r in res.data:
                c = r["item_code"]
                if str(c).startswith("BATCH-") or str(c).startswith("SYSTEM_"): continue
                img = r.get("images", [])
                thumb = img[0] if img and isinstance(img, list) else ""
                item_map[c] = {
                    "count": 1, "row": 0, "status": "出品完了", "dims": "測定済" if "【実寸" in r.get("description", "") else "",
                    "brand": r.get("brand", ""), "statusText": r.get("status_text", ""),
                    "title": r.get("title", ""), "desc": r.get("description", ""),
                    "thumbUrl": f"{PUBLIC_URL}/{thumb}" if thumb else "",
                    "packStatus": r.get("pack_status", ""), "shipStatus": "",
                    "missingImages": [], "hasMissingImage": False
                }
            return {"data": {"config": {"sheetName": active_batch}, "itemMap": item_map, "allSheets": all_batches, "currentViewSheet": active_batch}}

        elif method == "getBatchDownloadData":
            batch_name = args[0] if args and args[0] else get_saved_active_batch()
            query = supabase.table("mercari_items").select("*")
            if batch_name: query = query.eq("batch_name", batch_name)
            res = query.execute()
            
            output = io.StringIO()
            writer = csv.writer(output, quoting=csv.QUOTE_ALL)
            writer.writerow(["商品画像名_1","商品画像名_2","商品画像名_3","商品画像名_4","商品画像名_5","商品画像名_6","商品画像名_7","商品画像名_8","商品画像名_9","商品画像名_10","商品画像名_11","商品画像名_12","商品画像名_13","商品画像名_14","商品画像名_15","商品画像名_16","商品画像名_17","商品画像名_18","商品画像名_19","商品画像名_20","商品名","商品説明","SKU1_種類","SKU1_在庫数","SKU1_商品管理コード","SKU1_JANコード","ブランドID","販売価格","カテゴリID","商品の状態","配送方法","発送元の地域","発送までの日数","商品ステータス"])
            
            images_to_download = []
            for r in res.data:
                if str(r.get("item_code", "")).startswith("TMP-") or str(r.get("item_code", "")).startswith("BATCH-") or str(r.get("item_code", "")).startswith("SYSTEM_"): continue
                
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

        elif method == "getItemImagesForAdmin":
            code = args[1]
            res = supabase.table("mercari_items").select("images").eq("item_code", code).execute()
            images = []
            if res.data:
                for img in res.data[0].get("images", []):
                    images.append({"name": img, "url": f"{PUBLIC_URL}/{img}"})
            return {"data": {"images": images}}

        elif method == "deleteAdminImage":
            code = args[1]
            imgName = args[2]
            res = supabase.table("mercari_items").select("images").eq("item_code", code).execute()
            if res.data:
                imgs = res.data[0].get("images", [])
                if imgName in imgs:
                    imgs.remove(imgName)
                    supabase.table("mercari_items").update({"images": imgs}).eq("item_code", code).execute()
            return {"data": "OK"}

        elif method == "addAdminImages":
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

        elif method == "replaceItemImages":
            code = args[1]
            b64_list = args[2]
            new_imgs = [f"{code}-{i+1}.jpg" for i in range(len(b64_list))]
            supabase.table("mercari_items").update({"images": new_imgs}).eq("item_code", code).execute()
            return {"data": "OK"}

        elif method == "updateItemTextData":
            code = args[1]
            supabase.table("mercari_items").update({
                "title": args[2], "description": args[3], "status_text": args[5]
            }).eq("item_code", code).execute()
            return {"data": "OK"}
            
        elif method == "retryAIGeneration":
            code = args[1]
            new_status = args[2]
            res = supabase.table("mercari_items").select("*").eq("item_code", code).execute()
            if res.data:
                item = res.data[0]
                imgs = item.get("images", [])
                if imgs:
                    img_url = f"{PUBLIC_URL}/{imgs[0]}"
                    try:
                        img_res = requests.get(img_url)
                        b64 = base64.b64encode(img_res.content).decode('utf-8')
                        ai_data = analyze_image_with_gemini(b64, item.get("keywords", ""))
                        gender = "メンズ" if "メンズ" in item.get("category_text", "") else "レディース" if "レディース" in item.get("category_text", "") else ""
                        status_to_use = new_status if new_status else item.get("status_text", "")
                        title = build_title(item, ai_data, gender, code)
                        desc = build_description(ai_data.get("intro", ""), status_to_use, item.get("size_input", ""))
                        supabase.table("mercari_items").update({
                            "title": title, "description": desc, "status_text": status_to_use
                        }).eq("item_code", code).execute()
                    except:
                        pass
            return {"data": "OK"}

        elif method == "fixManagementCode":
            old_code = args[1]
            new_code = args[2]
            res = supabase.table("mercari_items").select("*").eq("item_code", old_code).execute()
            if res.data:
                item = res.data[0]
                new_title = item.get("title", "").replace(old_code, new_code)
                new_images = [img.replace(old_code, new_code) for img in item.get("images", [])]
                supabase.table("mercari_items").update({
                    "item_code": new_code, "title": new_title, "images": new_images
                }).eq("item_code", old_code).execute()
            return {"data": "OK"}

        elif method == "revertPackingStatus":
            code = args[1]
            supabase.table("mercari_items").update({"pack_status": ""}).eq("item_code", code).execute()
            return {"data": "OK"}

        elif method == "moveItemsToBatch":
            target_batch = args[1]
            codes = args[2]
            for c in codes:
                supabase.table("mercari_items").update({"batch_name": target_batch}).eq("item_code", c).execute()
            return {"data": "OK"}

        elif method == "fetchIncentiveData":
            return {"data": []}

        elif method == "deleteItemData":
            code = args[1]
            supabase.table("mercari_items").delete().eq("item_code", code).execute()
            return {"data": "OK"}
            
        else:
            return {"data": "OK"}
            
    except Exception as e:
        return {"error": str(e)}
