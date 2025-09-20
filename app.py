# app.py — Outf!ts
# 追加:
# - 写真アップ時に「色・カテゴリ・名前・素材・得意シーズン」をヒューリスティックで自動推定して初期入力
# - URL取込の文字化けを修正（多段エンコード検出 + BeautifulSoup + HTMLアンエスケープ）
# - URLからも「カテゴリ/素材/得意シーズン」をテキスト分析で推定
# - 既存機能（AIコーデ/評価/編集 等）は前版を踏襲

import streamlit as st
import pandas as pd, numpy as np
from PIL import Image, ImageDraw
import sqlite3, os, io, requests, colorsys, calendar, json, re
from urllib.parse import urljoin
from datetime import datetime
from bs4 import BeautifulSoup
import html as ihtml  # HTMLエンティティ解除

st.set_page_config(page_title="Outf!ts", layout="centered")

# ---------- Theme ----------
st.markdown("""
<style>
:root{ --bg-a:#f6f1e7; --bg-b:#ece7df; --ink:#222; --accent:#1f7a7a; }
html, body { background: linear-gradient(135deg, var(--bg-a), var(--bg-b)); }
.block-container{ background:#ffffffcc; backdrop-filter: blur(4px); border:1px solid #eee;
  border-radius:16px; padding:18px 16px 30px; }
.stTabs [role="tab"]{ padding:12px 10px; border-radius:10px; font-weight:600; }
.stTabs [role="tab"][aria-selected="true"]{ background:#fff; border:1px solid #ddd; }
button[kind="primary"]{ background: var(--accent) !important; border:0 !important; }
.card{border:1px solid #eee;border-radius:12px;padding:10px;margin:8px 0;background:#fff;}
.badge{display:inline-block;padding:6px 10px;border-radius:999px;border:1px solid #ddd;margin-right:6px;}
.swatch{width:24px;height:24px;border:1px solid #aaa;border-radius:6px;display:inline-block;margin-right:6px;}
.small{font-size:12px;color:#666}
</style>
""", unsafe_allow_html=True)

# ---------- PWA-ish（任意） ----------
st.markdown("""
<link rel="manifest" href="manifest.webmanifest">
<script>
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('service_worker.js').catch(()=>{});
  });
}
</script>
""", unsafe_allow_html=True)

# ---------- DB ----------
DB_PATH = "data/app.db"
def init_db():
    os.makedirs("data", exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS outfits(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          d TEXT, season TEXT, top_sil TEXT, bottom_sil TEXT,
          top_color TEXT, bottom_color TEXT, colors TEXT, img BLOB, notes TEXT
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS profile(
          id INTEGER PRIMARY KEY CHECK(id=1),
          season TEXT, undertone TEXT, home_lat REAL, home_lon REAL, city TEXT,
          body_shape TEXT, height_cm REAL
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS items(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT, category TEXT, color_hex TEXT, season_pref TEXT,
          material TEXT, img BLOB, notes TEXT
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS coords(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT,
          top_id INTEGER, bottom_id INTEGER, shoes_id INTEGER, bag_id INTEGER,
          ctx TEXT, score REAL, rating INTEGER
        )""")
        try: c.execute("ALTER TABLE profile ADD COLUMN body_shape TEXT")
        except: pass
        try: c.execute("ALTER TABLE profile ADD COLUMN height_cm REAL")
        except: pass
        conn.commit()

def json_dumps(x): return json.dumps(x, ensure_ascii=False)
def json_loads(x):
    try: return json.loads(x) if x else []
    except: return []

def insert_outfit(d, season, top_sil, bottom_sil, top_color, bottom_color, colors_list, img_bytes, notes):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO outfits(d,season,top_sil,bottom_sil,top_color,bottom_color,colors,img,notes)
                     VALUES(?,?,?,?,?,?,?,?,?)""",
                  (d, season, top_sil, bottom_sil, top_color, bottom_color, json_dumps(colors_list), img_bytes, notes))
        conn.commit()

def fetch_outfits_on(day_str):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        return c.execute("""SELECT id,d,season,top_sil,bottom_sil,top_color,bottom_color,colors,img,notes
                            FROM outfits WHERE d=? ORDER BY id DESC""", (day_str,)).fetchall()

def load_profile():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        row = c.execute("SELECT season,undertone,home_lat,home_lon,city,body_shape,height_cm FROM profile WHERE id=1").fetchone()
    return {"season":row[0],"undertone":row[1],"home_lat":row[2],"home_lon":row[3],
            "city":row[4],"body_shape":row[5],"height_cm":row[6]} if row else \
           {"season":None,"undertone":None,"home_lat":None,"home_lon":None,"city":None,"body_shape":None,"height_cm":None}

def save_profile(**kwargs):
    cur = load_profile()
    cur.update({k:v for k,v in kwargs.items() if v is not None})
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""INSERT OR REPLACE INTO profile(id,season,undertone,home_lat,home_lon,city,body_shape,height_cm)
                     VALUES(1,?,?,?,?,?,?,?)""",
                  (cur["season"], cur["undertone"], cur["home_lat"], cur["home_lon"],
                   cur["city"], cur["body_shape"], cur["height_cm"]))
        conn.commit()

def add_item(name, category, color_hex, season_pref, material, img_bytes, notes):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO items(name,category,color_hex,season_pref,material,img,notes)
                     VALUES(?,?,?,?,?,?,?)""", (name,category,color_hex,season_pref,material,img_bytes,notes))
        conn.commit()

def list_items(category=None):
    q = "SELECT id,name,category,color_hex,season_pref,material,img,notes FROM items"
    params=[]
    if category and category!="すべて":
        q += " WHERE category=?"; params=[category]
    q += " ORDER BY id DESC"
    with sqlite3.connect(DB_PATH) as conn:
        return conn.cursor().execute(q, params).fetchall()

def get_item(iid:int):
    with sqlite3.connect(DB_PATH) as conn:
        return conn.cursor().execute(
            "SELECT id,name,category,color_hex,season_pref,material,img,notes FROM items WHERE id=?",(iid,)
        ).fetchone()

def update_item(iid:int, name, category, color_hex, season_pref, material, img_bytes_or_none, notes):
    cur = get_item(iid)
    if not cur: return
    new_img = img_bytes_or_none if img_bytes_or_none is not None else cur[6]
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""UPDATE items SET name=?,category=?,color_hex=?,season_pref=?,material=?,img=?,notes=? WHERE id=?""",
                  (name,category,color_hex,season_pref,material,new_img,notes,iid))
        conn.commit()

def save_coord(top_id, bottom_id, shoes_id, bag_id, ctx:dict, score:float, rating:int|None):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO coords(created_at,top_id,bottom_id,shoes_id,bag_id,ctx,score,rating)
                     VALUES(?,?,?,?,?,?,?,?)""",
                  (datetime.utcnow().isoformat(), top_id, bottom_id, shoes_id, bag_id, json_dumps(ctx), score, rating))
        conn.commit()

# ---------- Color utils ----------
CSS_COLORS = {
 "Black":"#000000","White":"#ffffff","Gray":"#808080","Silver":"#c0c0c0","DimGray":"#696969",
 "Navy":"#000080","MidnightBlue":"#191970","RoyalBlue":"#4169e1","Blue":"#0000ff","DodgerBlue":"#1e90ff",
 "LightBlue":"#add8e6","Teal":"#008080","Aqua":"#00ffff","Turquoise":"#40e0d0",
 "Green":"#008000","Lime":"#00ff00","Olive":"#808000","ForestGreen":"#228b22","SeaGreen":"#2e8b57",
 "Yellow":"#ffff00","Gold":"#ffd700","Khaki":"#f0e68c","Beige":"#f5f5dc","Tan":"#d2b48c",
 "Orange":"#ffa500","Coral":"#ff7f50","Tomato":"#ff6347","Red":"#ff0000","Maroon":"#800000",
 "Pink":"#ffc0cb","HotPink":"#ff69b4","Magenta":"#ff00ff","Purple":"#800080","Indigo":"#4b0082",
 "Lavender":"#e6e6fa","Plum":"#dda0dd","Brown":"#a52a2a","Chocolate":"#d2691e","SaddleBrown":"#8b4513"
}
JP_COLOR = {"Black":"ブラック","White":"ホワイト","Gray":"グレー","Silver":"シルバー","DimGray":"ダークグレー",
"Navy":"ネイビー","MidnightBlue":"ミッドナイトブルー","RoyalBlue":"ロイヤルブルー","Blue":"ブルー","DodgerBlue":"ドッジャーブルー",
"LightBlue":"ライトブルー","Teal":"ティール","Aqua":"アクア","Turquoise":"ターコイズ",
"Green":"グリーン","Lime":"ライム","Olive":"オリーブ","ForestGreen":"フォレストグリーン","SeaGreen":"シーグリーン",
"Yellow":"イエロー","Gold":"ゴールド","Khaki":"カーキ","Beige":"ベージュ","Tan":"タン",
"Orange":"オレンジ","Coral":"コーラル","Tomato":"トマト","Red":"レッド","Maroon":"マルーン",
"Pink":"ピンク","HotPink":"ホットピンク","Magenta":"マゼンタ","Purple":"パープル","Indigo":"インディゴ",
"Lavender":"ラベンダー","Plum":"プラム","Brown":"ブラウン","Chocolate":"チョコレート","SaddleBrown":"サドルブラウン"}

def hex_to_rgb(h): h=h.lstrip("#"); return tuple(int(h[i:i+2],16) for i in (0,2,4))
def rgb_to_hex(rgb): return "#{:02x}{:02x}{:02x}".format(*rgb)
def hex_luma(h): r,g,b=hex_to_rgb(h); return 0.2126*r+0.7152*g+0.0722*b

def nearest_css_name(hexstr):
    r,g,b = hex_to_rgb(hexstr); best,bd=None,10**9
    for name,hx in CSS_COLORS.items():
        rr,gg,bb = hex_to_rgb(hx); d=(r-rr)**2+(g-gg)**2+(b-bb)**2
        if d<bd: bd, best=d, name
    return best

def hex_family(hx):
    r,g,b=[v/255 for v in hex_to_rgb(hx)]
    h,s,v=colorsys.rgb_to_hsv(r,g,b); hue=h*360
    if v<0.15: return "black"
    if s<0.15 and v>0.9: return "white"
    if s<0.20: return "gray"
    if 0<=hue<15: return "red"
    if 15<=hue<45: return "orange"
    if 45<=hue<65: return "yellow"
    if 65<=hue<170: return "green"
    if 170<=hue<200: return "cyan"
    if 200<=hue<255: return "blue"
    if 255<=hue<290: return "purple"
    if 290<=hue<330: return "magenta"
    return "red"

def adjust_harmony(hx, mode="complement", delta=30):
    r,g,b=[v/255 for v in hex_to_rgb(hx)]
    h,s,v=colorsys.rgb_to_hsv(r,g,b)
    def wrap(deg): return ((h*360+deg)%360)/360
    hs = [wrap(180)] if mode=="complement" else ([wrap(+delta),wrap(-delta)] if mode=="analogous" else [wrap(+120),wrap(-120)])
    outs=[]
    for hh in hs:
        rr,gg,bb=colorsys.hsv_to_rgb(hh,s,v); outs.append(rgb_to_hex((int(rr*255),int(gg*255),int(bb*255))))
    return outs

def extract_dominant_colors(img:Image.Image, k=5):
    small=img.copy(); small.thumbnail((200,200))
    pal=small.convert("P", palette=Image.ADAPTIVE, colors=k)
    palette=pal.getpalette(); cnt=pal.getcolors()
    if not cnt: return ["#888888"]
    cnt.sort(reverse=True); out=[]; seen=set()
    for n,idx in cnt[:k*2]:
        r,g,b=palette[idx*3:idx*3+3]; hx=rgb_to_hex((r,g,b)); fam=hex_family(hx)
        key=(fam,(r,g,b))
        if key not in seen:
            out.append(hx); seen.add(key)
        if len(out)>=k: break
    return out

SEASON_PALETTES = {
    "spring": ["#ffb3a7","#ffd28c","#ffe680","#b7e07a","#8ed1c8","#ffd7ef","#f5deb3"],
    "summer": ["#c8cbe6","#b0c4de","#c3b1e1","#9fd3c7","#d8d8d8","#e6d5c3","#a3bcd6"],
    "autumn": ["#a0522d","#c68642","#8f9779","#556b2f","#b5651d","#6b4f3f","#8b6c42"],
    "winter": ["#000000","#ffffff","#4169e1","#8a2be2","#ff1493","#00ced1","#2f4f4f"],
}
def palette_distance(hexstr, user_season):
    if not user_season or user_season not in SEASON_PALETTES: return 0.0
    px=hex_to_rgb(hexstr); best=1e9
    for p in SEASON_PALETTES[user_season]:
        rr,gg,bb=hex_to_rgb(p)
        d=(px[0]-rr)**2+(px[1]-gg)**2+(px[2]-bb)**2
        if d<best: best=d
    return best

# ---------- 環境考慮（AIコーデ用） ----------
def purpose_match(notes:str, want:str)->int:
    if not want or want=="指定なし": return 0
    n=notes or ""
    score=0
    if want=="通勤":     score += any(k in n for k in ["ジャケット","シャツ","スラックス","革靴","きれいめ"])
    if want=="デート":   score += any(k in n for k in ["綺麗め","スカート","ワンピ","ヒール","上品"])
    if want=="スポーツ": score += any(k in n for k in ["スニーカー","ジャージ","ドライ","ラン","トレ"])
    if want=="フォーマル":score += any(k in n for k in ["ネクタイ","セットアップ","ドレス","革靴"])
    if want=="雨の日":  score += any(k in n for k in ["撥水","防水","ゴア","レイン","ナイロン"])
    return score

def body_shape_bonus(notes:str, body:str|None, category:str)->int:
    if not body: return 0
    n=(notes or "").lower()
    b=body
    if b=="straight":
        if category=="ボトムス" and any(k in n for k in ["テーパード","センタープレス","ストレート"]): return 1
        if category in ["トップス","アウター"] and any(k in n for k in ["vネック","襟","ジャケット","構築的"]): return 1
    if b=="wave":
        if category=="ボトムス" and any(k in n for k in ["ハイウエスト","aライン","フレア"]): return 1
        if category=="トップス" and any(k in n for k in ["短丈","クロップド","柔らか","リブ"]): return 1
    if b=="natural":
        if any(k in n for k in ["ワイド","オーバーサイズ","ドロップショルダー","リネン","ツイード"]): return 1
    return 0

def climate_bonus(material:str|None, heat:str, humidity:str, rainy:bool)->int:
    m=(material or "").lower()
    s=0
    if heat in ["暑い","猛暑"] and any(k in m for k in ["linen","リネン","cotton","コットン","メッシュ","ドライ"]): s+=1
    if heat in ["寒い"] and any(k in m for k in ["wool","ウール","ダウン","中綿","フリース","キルト"]): s+=1
    if humidity=="湿度高い" and any(k in m for k in ["ドライ","吸汗","速乾","メッシュ","ナイロン","nylon"]): s+=1
    if humidity=="乾燥" and any(k in m for k in ["ウール","ニット","フリース"]): s+=1
    if rainy and any(k in m for k in ["ナイロン","nylon","ゴア","gore","防水","撥水"]): s+=1
    return s

def color_pair_score(top_hex:str, item_hex:str, season:str|None)->float:
    r = adjust_harmony(top_hex,"complement")+adjust_harmony(top_hex,"analogous")+adjust_harmony(top_hex,"triadic")
    def dist(h1,h2):
        r1,g1,b1=hex_to_rgb(h1); r2,g2,b2=hex_to_rgb(h2); return (r1-r2)**2+(g1-g2)**2+(b1-b2)**2
    d = min([dist(item_hex, h) for h in r] + [dist(item_hex, top_hex)])
    return d + 0.1*palette_distance(item_hex, season)

def pick_best(items, top_hex, season, body_shape, want, heat, humidity, rainy, category):
    cand=[it for it in items if it[2]==category]
    if not cand: return None, 1e9
    scored=[]
    for row in cand:
        iid,nm,cat,hx,sp,mat,imgb,nts=row
        s  = color_pair_score(top_hex, hx, season)
        s -= 200 if sp and season and sp==season else 0
        s -= 120*purpose_match(nts or "", want)
        s -= 80*body_shape_bonus(nts or "", body_shape, cat)
        s -= 60*climate_bonus(mat, heat, humidity, rainy)
        scored.append((s,row))
    scored.sort(key=lambda x:x[0])
    return scored[0][1], scored[0][0]

def generate_outfit_from_closet(all_items, season, body_shape, want, heat, humidity, rainy):
    tops=[it for it in all_items if it[2]=="トップス"]
    if not tops: return None, None
    t_best=None; t_score=1e9
    for row in tops:
        _,_,cat,hx,sp,mat,imgb,nts=row
        s  = 0.2*palette_distance(hx, season)
        s -= 100*(sp==season) if sp and season else 0
        s -= 80*body_shape_bonus(nts or "", body_shape, cat)
        s -= 40*climate_bonus(mat, heat, humidity, rainy)
        if s<t_score: t_score=s; t_best=row
    top=t_best
    bottom,b_sc = pick_best(all_items, top[3], season, body_shape, want, heat, humidity, rainy, "ボトムス")
    shoes ,s_sc = pick_best(all_items, top[3], season, body_shape, want, heat, humidity, rainy, "シューズ")
    bag   ,g_sc = pick_best(all_items, top[3], season, body_shape, want, heat, humidity, rainy, "バッグ")
    total_score = t_score + b_sc + s_sc + g_sc
    return {"top":top,"bottom":bottom,"shoes":shoes,"bag":bag}, total_score

# ---------- URL取込（エンコード対策 + 推定器） ----------
UA = {"User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1","Accept-Language":"ja,en;q=0.8"}

def _decode_best(r):
    """文字化け対策: 応答バイトから最適なエンコーディングで文字列化"""
    b = r.content
    candidates = []
    if getattr(r, "encoding", None): candidates.append(r.encoding)
    if getattr(r, "apparent_encoding", None): candidates.append(r.apparent_encoding)
    candidates += ["utf-8","cp932","shift_jis","euc-jp"]
    for enc in candidates:
        try: return b.decode(enc)
        except: continue
    return b.decode("utf-8", errors="ignore")

def _meta(soup, key):
    tag = soup.find("meta", attrs={"property":key}) or soup.find("meta", attrs={"name":key})
    return tag.get("content").strip() if tag and tag.get("content") else None

def _jsonld_image(soup):
    for sc in soup.find_all("script", {"type":"application/ld+json"}):
        try:
            data=json.loads(sc.string)
            if isinstance(data, list):
                for d in data:
                    if isinstance(d, dict) and d.get("image"):
                        img=d["image"]; return img[0] if isinstance(img, list) else img
            elif isinstance(data, dict) and data.get("image"):
                img=data["image"]; return img[0] if isinstance(img, list) else img
        except: pass
    return None

# ---- テキストからカテゴリ/素材/季節を推定 ----
CAT_MAP = {
    "トップス":["tシャツ","tee","シャツ","ブラウス","スウェット","パーカー","ニット","セーター","カーディガン","トップス","pullover","hoodie","sweat","blouse"],
    "ボトムス":["パンツ","デニム","ジーンズ","スラックス","トラウザー","スカート","ショーツ","ハーフパンツ","shorts","trousers","skirt","jeans"],
    "アウター":["コート","ジャケット","ブルゾン","ダウン","アウター","マウンテン","ライダース","gジャン","jacket","coat"],
    "ワンピース":["ワンピース","ドレス","ジャンパースカート","one-piece","dress"],
    "シューズ":["スニーカー","ブーツ","パンプス","サンダル","shoes","sneaker","boots","heels"],
    "バッグ":["バッグ","トート","ショルダー","バックパック","リュック","bag","tote","shoulder","backpack"],
    "アクセ":["帽子","キャップ","ハット","ベルト","マフラー","ストール","アクセ","ネックレス","ピアス","cap","hat","scarf","belt","accessory"]
}
MAT_KEYS = ["コットン","綿","ウール","ナイロン","ポリエステル","リネン","麻","デニム","レザー","合皮","カシミヤ","シルク","ダウン","フリース"]

def guess_category_from_text(text:str)->str:
    t=(text or "").lower()
    score=[]
    for cat, kws in CAT_MAP.items():
        if any(k.lower() in t for k in kws): score.append((cat,1))
    if score: return score[0][0]
    return "トップス"

def guess_material_from_text(text:str)->str|None:
    t=text or ""
    for k in MAT_KEYS:
        if k in t: return k
    return None

def guess_season_from_text(text:str)->str|None:
    t=(text or "").lower()
    if any(k in t for k in ["春夏","ss","summer","春/夏"]): return "summer"
    if any(k in t for k in ["秋冬","fw","winter","秋/冬"]): return "winter"
    return None

def fetch_from_page(url:str):
    """商品ページURLから (title, image_bytes, description) を取得（UNIQLO/ZOZO等）"""
    try:
        r=requests.get(url, timeout=10, headers=UA)
        if r.status_code!=200: return None,None,None
        html=_decode_best(r)
        soup=BeautifulSoup(html, "html.parser")
        title = _meta(soup,"og:title") or _meta(soup,"twitter:title") or (soup.title.get_text().strip() if soup.title else None)
        desc  = _meta(soup,"og:description") or _meta(soup,"description")
        if title: title = ihtml.unescape(title)
        img_url = _meta(soup,"og:image:secure_url") or _meta(soup,"og:image") or _meta(soup,"twitter:image")
        if not img_url: img_url = _jsonld_image(soup)
        if img_url: img_url=urljoin(url, img_url)
        img_bytes=None
        if img_url:
            try:
                r2=requests.get(img_url, timeout=10, headers=UA)
                if r2.status_code==200: img_bytes=r2.content
            except: pass
        return title, img_bytes, desc
    except:
        return None, None, None

# ---------- 画像からの簡易推定 ----------
def pick_top_bottom_from_colors(cols:list[str]):
    if not cols: return "#2f2f2f","#c9c9c9"
    bottom = sorted(cols, key=lambda h: hex_luma(h))[0]
    vivid = [h for h in cols if hex_family(h) not in ("black","white","gray")]
    top = vivid[0] if vivid else (cols[0] if cols else "#2f2f2f")
    if top == bottom: bottom = "#c9c9c9"
    return top, bottom

def guess_season_from_colors(cols:list[str])->str|None:
    if not cols: return None
    hsv=[]
    for h in cols:
        r,g,b=[v/255 for v in hex_to_rgb(h)]
        hsv.append(colorsys.rgb_to_hsv(r,g,b))
    h = sum([x[0] for x in hsv])/len(hsv)
    s = sum([x[1] for x in hsv])/len(hsv)
    v = sum([x[2] for x in hsv])/len(hsv)
    hue=h*360
    if v>0.75 and s>0.35 and 20<=hue<=70:   return "spring"
    if v>0.7 and s<0.35:                    return "summer"
    if v<0.55 and 20<=hue<=80:              return "autumn"
    if v>0.8 and s>0.6 and (hue<20 or hue>220): return "winter"
    return None

def guess_category_from_image(img:Image.Image)->str:
    ar = img.height / max(1,img.width)
    if ar>=1.4:  # 縦長→ワンピ/ボトム推定
        return "ボトムス"
    if ar<=0.9:  # 横長→トップス/アウター
        return "トップス"
    return "トップス"

def guess_material_from_colors(cols:list[str])->str:
    if not cols: return "コットン"
    v = np.mean([hex_luma(x) for x in cols])
    if v<90:  return "ウール/ニット"
    if v>200: return "コットン/リネン"
    return "コットン"

# ---------- UI ----------
init_db()
profile = load_profile()

st.title("Outf!ts")
tab1, tabCal, tabCloset, tabAI, tabProfile = st.tabs(["📒 記録","📅 カレンダー","🧳 クローゼット","🤖 AIコーデ","👤 プロフィール"])

SIL_TOP = ["ジャスト/レギュラー","オーバーサイズ","クロップド/短丈","タイト/フィット"]
SIL_BOTTOM = ["ストレート","ワイド/フレア","スキニー/テーパード","Aライン/スカート","ショーツ"]

# ===== 記録 =====
with tab1:
    d = st.date_input("日付", value=pd.Timestamp.today(), key="rec_date")
    up = st.file_uploader("写真（カメラ可）", type=["jpg","jpeg","png","webp"], key="rec_photo")
    colA, colB = st.columns(2)
    top_sil = colA.selectbox("トップ", SIL_TOP, index=0, key="rec_top_sil")
    bottom_sil = colB.selectbox("ボトム", SIL_BOTTOM, index=0, key="rec_bottom_sil")
    notes = st.text_area("メモ", placeholder="", key="rec_notes")

    auto_colors=[]; auto_top="#2f2f2f"; auto_bottom="#c9c9c9"
    if up is not None:
        img = Image.open(up).convert("RGB")
        st.image(img, use_container_width=True)
        auto_colors = extract_dominant_colors(img, k=5)
        auto_top, auto_bottom = pick_top_bottom_from_colors(auto_colors)
        st.caption("自動カラー認識")
        st.markdown(" ".join([f"<span class='swatch' style='background:{h}'></span>" for h in auto_colors]), unsafe_allow_html=True)

    use_auto = st.toggle("自動色認識を使う", value=True, key="use_auto_colors")
    if use_auto:
        top_color, bottom_color = auto_top, auto_bottom
        st.markdown(f"<div class='badge'>Top: {top_color}</div><div class='badge'>Bottom: {bottom_color}</div>", unsafe_allow_html=True)
    else:
        col1, col2 = st.columns(2)
        top_color = col1.color_picker("トップ色", auto_top, key="rec_top_color")
        bottom_color = col2.color_picker("ボトム色", auto_bottom, key="rec_bottom_color")

    if st.button("保存", type="primary", key="rec_save", disabled=(up is None)):
        img_bytes = up.read()
        insert_outfit(str(pd.to_datetime(d).date()), profile.get("season"), top_sil, bottom_sil, top_color, bottom_color, auto_colors, img_bytes, notes)
        st.success("保存しました")

# ===== カレンダー =====
with tabCal:
    today = pd.Timestamp.today()
    colM = st.columns(2)
    year = colM[0].number_input("年", value=int(today.year), step=1, min_value=2000, max_value=2100, key="cal_year")
    month = colM[1].number_input("月", value=int(today.month), step=1, min_value=1, max_value=12, key="cal_month")
    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdatescalendar(int(year), int(month))
    if "modal_day" not in st.session_state: st.session_state["modal_day"] = None

    for wk in weeks:
        cols = st.columns(7)
        for i, d0 in enumerate(wk):
            slots = fetch_outfits_on(str(d0))
            with cols[i]:
                style = "padding:6px; border:1px solid #eee; border-radius:8px; min-height:110px; position:relative"
                if d0.month != int(month): style += "; opacity:0.5"
                st.markdown(f"<div style='{style}'><b>{d0.day}</b></div>", unsafe_allow_html=True)
                if slots:
                    try: st.image(Image.open(io.BytesIO(slots[0][8])), use_container_width=True)
                    except: pass
                    if st.button("詳細", key=f"detail_{d0.isoformat()}"):
                        st.session_state["modal_day"] = str(d0)

    if st.session_state["modal_day"]:
        day = st.session_state["modal_day"]; lst = fetch_outfits_on(day)
        st.markdown("<div style='position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:10000'>", unsafe_allow_html=True)
        with st.container():
            st.markdown("<div class='card' style='width:92%;max-width:640px'>", unsafe_allow_html=True)
            st.markdown(f"### {day}")
            if st.button("閉じる", key="cal_close"):
                st.session_state["modal_day"] = None
                st.experimental_rerun()
            for row in lst:
                oid, dd, seas, ts, bs, tc, bc, cols_js, img_b, nt = row
                colm = st.columns([1,2])
                with colm[0]:
                    try: st.image(Image.open(io.BytesIO(img_b)), use_container_width=True)
                    except: st.write("画像なし")
                with colm[1]:
                    st.write(f"Top:{ts}({tc}) / Bottom:{bs}({bc})")
                    st.caption(nt or "")
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

# ===== クローゼット =====
with tabCloset:
    st.subheader("追加")
    add_mode = st.radio("", ["写真から","URLから"], horizontal=True, key="cl_add_mode")

    if add_mode=="写真から":
        colC = st.columns(2)
        upi = st.file_uploader("画像", type=["jpg","jpeg","png","webp"], key="cl_img")
        # --- 自動推定 ---
        color_auto="#2f2f2f"; cat_guess="トップス"; season_guess=None; name_suggest="アイテム"; material_guess="コットン"
        if upi:
            img_i = Image.open(upi).convert("RGB")
            st.image(img_i, use_container_width=True)
            cols_auto = extract_dominant_colors(img_i, k=5)
            if cols_auto: color_auto = cols_auto[0]
            cat_guess = guess_category_from_image(img_i)
            season_guess = guess_season_from_colors(cols_auto)
            cname = JP_COLOR.get(nearest_css_name(color_auto), "カラー")
            name_suggest = f"{cname} {('Tシャツ' if cat_guess=='トップス' else 'パンツ' if cat_guess=='ボトムス' else cat_guess)}"
            material_guess = guess_material_from_colors(cols_auto)
            st.caption("自動カラー/カテゴリ/季節/素材を推定しました（必要に応じて修正）")
            st.markdown(" ".join([f"<span class='swatch' style='background:{h}'></span>" for h in cols_auto]), unsafe_allow_html=True)

        colN = st.columns(2)
        name = colN[0].text_input("名前", value=name_suggest, key="cl_name")
        category = colN[1].selectbox("カテゴリ", ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"],
                                     index=(["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"].index(cat_guess) if cat_guess in ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"] else 0),
                                     key="cl_category")
        color_hex = st.color_picker("色", color_auto, key="cl_color")
        colS = st.columns(2)
        season_pref = colS[0].selectbox("得意シーズン", ["指定なし","spring","summer","autumn","winter"],
                                        index=(["指定なし","spring","summer","autumn","winter"].index(season_guess) if season_guess in ["spring","summer","autumn","winter"] else 0),
                                        key="cl_season")
        material = colS[1].text_input("素材", value=material_guess, key="cl_material")
        notes_i = st.text_area("メモ（用途/特徴）", key="cl_notes")
        if st.button("追加", key="cl_add_btn"):
            img_b = upi.read() if upi else None
            add_item(name or "Unnamed", category, color_hex,
                     None if season_pref=="指定なし" else season_pref,
                     material, img_b, notes_i)
            st.success("追加しました")

    else:
        url = st.text_input("商品URL", placeholder="https://", key="cl_url")
        if st.button("解析", key="cl_parse"):
            title, img_bytes, desc = fetch_from_page(url)
            if not title and not img_bytes:
                st.error("取得できませんでした")
            else:
                st.session_state["url_title"]=title
                st.session_state["url_img"]=img_bytes
                st.session_state["url_desc"]=desc
                st.success("読み込みました")

        title = st.session_state.get("url_title")
        img_bytes = st.session_state.get("url_img")
        desc = st.session_state.get("url_desc","")

        # --- 推定（文字から） ---
        cat_from_text = guess_category_from_text((title or "") + " " + (desc or ""))
        mat_from_text = guess_material_from_text((title or "") + " " + (desc or "")) or ""
        ssn_from_text = guess_season_from_text((title or "") + " " + (desc or ""))

        color_guess="#2f2f2f"
        if img_bytes:
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            st.image(img, use_container_width=True)
            cols_auto = extract_dominant_colors(img, k=5)
            if cols_auto: color_guess=cols_auto[0]
            st.markdown(" ".join([f"<span class='swatch' style='background:{h}'></span>" for h in cols_auto]), unsafe_allow_html=True)

        colU = st.columns(2)
        name_url = colU[0].text_input("名前", value=(title or ""), key="cl_name_url")  # ← 文字化け対策済タイトル
        category_url = colU[1].selectbox("カテゴリ", ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"],
                                         index=(["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"].index(cat_from_text) if cat_from_text in ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"] else 0),
                                         key="cl_category_url")
        color_url = st.color_picker("色", color_guess, key="cl_color_url")

        colU2 = st.columns(2)
        material_url = colU2[0].text_input("素材", value=mat_from_text, key="cl_material_url")
        season_idx = (["指定なし","spring","summer","autumn","winter"].index(ssn_from_text) if ssn_from_text in ["spring","summer","autumn","winter"] else 0)
        season_url = colU2[1].selectbox("得意シーズン", ["指定なし","spring","summer","autumn","winter"], index=season_idx, key="cl_season_url")

        notes_url = st.text_area("メモ", value=(url or desc or ""), key="cl_notes_url")
        if st.button("追加", key="cl_add_btn_url", disabled=(not name_url and img_bytes is None)):
            add_item(name_url or "Unnamed", category_url, color_url,
                     None if season_url=="指定なし" else season_url,
                     material_url, img_bytes, notes_url)
            st.success("追加しました")

    st.markdown("---")
    st.subheader("一覧 / 編集")
    filt = st.selectbox("絞り込み", ["すべて","トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"], index=0, key="cl_filter")
    items = list_items(filt)
    for iid, nm, cat, hx, sp, mat, imgb, nts in items:
        with st.expander(f"{nm}（{cat}）", expanded=False):
            cols = st.columns([1,2])
            with cols[0]:
                if imgb: 
                    try: st.image(Image.open(io.BytesIO(imgb)), use_container_width=True)
                    except: st.write("画像なし")
                else: st.write("画像なし")
            with cols[1]:
                ename = st.text_input("名前", value=nm, key=f"edit_name_{iid}")
                ecat = st.selectbox("カテゴリ", ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"],
                                    index=(["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"].index(cat) if cat in ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"] else 0),
                                    key=f"edit_cat_{iid}")
                ehx = st.color_picker("色", hx or "#2f2f2f", key=f"edit_color_{iid}")
                esp = st.selectbox("得意シーズン", ["指定なし","spring","summer","autumn","winter"],
                                   index=(["指定なし","spring","summer","autumn","winter"].index(sp) if sp in ["spring","summer","autumn","winter"] else 0),
                                   key=f"edit_season_{iid}")
                emat = st.text_input("素材", value=mat or "", key=f"edit_mat_{iid}")
                enotes = st.text_area("メモ", value=nts or "", key=f"edit_notes_{iid}")
                eup = st.file_uploader("画像差し替え（任意）", type=["jpg","jpeg","png","webp"], key=f"edit_img_{iid}")
                if st.button("保存", key=f"edit_save_{iid}"):
                    new_img_bytes = eup.read() if eup else None
                    update_item(iid, ename, ecat, ehx, None if esp=="指定なし" else esp, emat, new_img_bytes, enotes)
                    st.success("保存しました")

# ===== AIコーデ =====
with tabAI:
    all_items = list_items("すべて")
    if not all_items:
        st.info("まずアイテムを登録してください")
    else:
        colctx = st.columns(4)
        want = colctx[0].selectbox("用途", ["指定なし","通勤","デート","カジュアル","スポーツ","フォーマル","雨の日"], index=0, key="ai_want")
        heat = colctx[1].selectbox("体感", ["寒い","涼しい","ちょうど","暑い","猛暑"], index=2, key="ai_heat")
        humidity = colctx[2].selectbox("空気", ["乾燥","普通","湿度高い"], index=1, key="ai_humid")
        rainy= colctx[3].toggle("雨", value=False, key="ai_rain")
        season = profile.get("season"); body_shape = profile.get("body_shape")

        if st.button("生成", key="ai_gen"):
            outfit, score = generate_outfit_from_closet(all_items, season, body_shape, want, heat, humidity, rainy)
            if not outfit:
                st.warning("候補が見つかりませんでした")
            else:
                st.markdown("### 提案")
                cols = st.columns(4)
                labels=[("トップ","top"),("ボトム","bottom"),("靴","shoes"),("バッグ","bag")]
                for j,(label,key) in enumerate(labels):
                    with cols[j]:
                        row = outfit[key]
                        if row:
                            if row[6]: st.image(Image.open(io.BytesIO(row[6])), use_container_width=True)
                            st.caption(f"{label}：{row[1]} / {row[3]}")
                        else:
                            st.caption(f"{label}：なし")
                st.caption(f"score {score:.1f}")
                rating = st.select_slider("評価", options=[1,2,3,4,5], value=4, key="ai_rating")
                if st.button("保存", key="ai_save"):
                    save_coord(outfit["top"][0], outfit["bottom"][0] if outfit["bottom"] else None,
                               outfit["shoes"][0] if outfit["shoes"] else None,
                               outfit["bag"][0] if outfit["bag"] else None,
                               {"want":want,"heat":heat,"humidity":humidity,"rainy":rainy,"season":season,"body_shape":body_shape},
                               float(score), int(rating))
                    st.success("保存しました")

# ===== プロフィール =====
with tabProfile:
    colp = st.columns(2)
    season = colp[0].selectbox("PC", ["未設定","spring","summer","autumn","winter"],
                               index=(["未設定","spring","summer","autumn","winter"].index(profile.get("season")) if profile.get("season") else 0),
                               key="prof_season")
    body_shape = colp[1].selectbox("体格", ["未設定","straight","wave","natural"],
                                   index=(["未設定","straight","wave","natural"].index(profile.get("body_shape")) if profile.get("body_shape") else 0),
                                   key="prof_body")
    height = st.number_input("身長(cm)", min_value=120.0, max_value=220.0, step=0.5,
                             value=float(profile.get("height_cm") or 165.0), key="prof_height")
    if st.button("保存", key="prof_save"):
        save_profile(season=None if season=="未設定" else season,
                     body_shape=None if body_shape=="未設定" else body_shape,
                     height_cm=float(height))
        st.success("保存しました")
