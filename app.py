# app.py — Outfit Log (Mobile+)
# - use_container_width で警告解消 / 全ウィジェットに unique key 付与（DuplicateElementId対策）
# - 商品URL取込：UNIQLO/ZOZOTOWN 他（og:image / twitter:image / JSON-LD の image を解析）
# - クローゼットからのAIコーデ自動生成（天候・PCシーズン・体格を考慮）
# - 生成コーデの保存＆⭐️評価（5段階）
# - 体格/パーソナルカラーをプロフィールに保存 → 推薦に反映

import streamlit as st
import pandas as pd, numpy as np
from PIL import Image, ImageDraw
import sqlite3, os, io, requests, colorsys, calendar, json, re
from urllib.parse import urljoin
from datetime import datetime

st.set_page_config(page_title="Outfit Log — Mobile", layout="centered")

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
        # 生成コーデ履歴＋評価
        c.execute("""
        CREATE TABLE IF NOT EXISTS coords(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT,
          top_id INTEGER, bottom_id INTEGER, shoes_id INTEGER, bag_id INTEGER,
          ctx TEXT, score REAL, rating INTEGER
        )""")
        # 既存DBに後から追加された列は ALTER で安全に拡張
        try: c.execute("ALTER TABLE profile ADD COLUMN body_shape TEXT");   # 1回目のみ
        except: pass
        try: c.execute("ALTER TABLE profile ADD COLUMN height_cm REAL");
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
def hex_to_rgb(h): h=h.lstrip("#"); return tuple(int(h[i:i+2],16) for i in (0,2,4))
def rgb_to_hex(rgb): return "#{:02x}{:02x}{:02x}".format(*rgb)
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

# ---------- Weather ----------
def fetch_open_meteo(lat, lon):
    try:
        url=(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
             "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto")
        r=requests.get(url, timeout=6)
        if r.status_code==200: return r.json()
    except: return None
    return None
def weather_tip(daily):
    try:
        tmax=daily["temperature_2m_max"][0]; tmin=daily["temperature_2m_min"][0]; p=daily["precipitation_probability_max"][0]
    except: return "天気情報を取得できませんでした。"
    msg=[]
    if tmax>=27: msg.append("暑い：半袖/軽素材/通気◎")
    elif tmax>=20: msg.append("穏やか：長袖1枚 or 薄羽織")
    elif tmax>=12: msg.append("肌寒い：薄手ニット/ライトアウター")
    else: msg.append("寒い：コート/中綿/マフラー")
    if p>=50: msg.append("降水高め：撥水アウター/防水シューズ/傘を")
    return f"{' / '.join(msg)}（最高{tmax:.0f}℃・最低{tmin:.0f}℃・降水{p}%）"

# ---------- Helpers ----------
def img_from_bytes(b): return Image.open(io.BytesIO(b)).convert("RGB")

def make_share_card(row, out_path="data/exports/share.png", weather=None):
    os.makedirs("data/exports", exist_ok=True)
    (oid,dd,seas,ts,bs,tc,bc,cols_js,img_b,nt)=row
    W,H=1080,1350
    base=Image.new("RGB",(W,H),(250,250,250)); draw=ImageDraw.Draw(base)
    draw.rectangle((0,0,W,110), fill=(17,17,17)); draw.text((36,34),"Outfit Log", fill=(255,255,255))
    y=130
    try:
        img=img_from_bytes(img_b)
        r=4/5; iw,ih=img.width,img.height
        if iw/ih>r:
            nw=int(ih*r); x0=(iw-nw)//2; box=(x0,0,x0+nw,ih)
        else:
            nh=int(iw/r); y0=(ih-nh)//2; box=(0,y0,iw,y0+nh)
        img=img.crop(box).resize((W-160,720), Image.LANCZOS)
        base.paste(img,((W-img.width)//2, y)); y+=img.height+14
    except: y+=14
    try: colors=json_loads(cols_js)[:5]
    except: colors=[]
    sw=80; gap=16
    for i,hx in enumerate(colors):
        x=100+i*(sw+gap); draw.rectangle((x,y,x+sw,y+sw), fill=hex_to_rgb(hx), outline=(30,30,30))
    y+=sw+14
    draw.text((100,y), f"Top: {tc}", fill=(0,0,0)); y+=30
    draw.text((100,y), f"Bottom: {bc}", fill=(0,0,0)); y+=30
    if weather:
        draw.text((100,y), f"Weather: {weather}", fill=(50,50,50)); y+=28
    draw.text((100,H-70), f"{dd} / {seas or '-'}", fill=(80,80,80))
    base.save(out_path,"PNG")
    with open(out_path,"rb") as f: return f.read()

# ---------- URL 取り込み（ZOZO強化） ----------
UA = {"User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
      "Accept-Language":"ja,en;q=0.8"}

def fetch_image_bytes_from_url(url:str):
    try:
        r=requests.get(url, timeout=10, headers=UA)
        if r.status_code==200: return r.content
    except: return None
    return None

def _meta(content, name):
    m=re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']', content, re.I)
    return m.group(1) if m else None

def _jsonld_image(content):
    # JSON-LDの"image"（配列 or 文字列）
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', content, re.I|re.S):
        try:
            data=json.loads(m.group(1))
            if isinstance(data, list):
                for d in data:
                    img = d.get("image") if isinstance(d, dict) else None
                    if img: return img[0] if isinstance(img, list) else img
            elif isinstance(data, dict):
                img = data.get("image")
                if img: return img[0] if isinstance(img, list) else img
        except: pass
    return None

def fetch_from_page(url:str):
    """商品ページURLから title と image を推定（UNIQLO/ZOZO/他）"""
    try:
        r=requests.get(url, timeout=10, headers=UA)
        if r.status_code!=200: return None,None
        html=r.text

        # 1) og:title / og:image / twitter:image
        title = _meta(html, "og:title") or _meta(html, "twitter:title")
        img_url = _meta(html, "og:image:secure_url") or _meta(html, "og:image") or _meta(html, "twitter:image")

        # 2) JSON-LD の image
        if not img_url:
            img_url = _jsonld_image(html)

        # 3) Fallback: <title>
        if not title:
            t2=re.search(r'<title[^>]*>(.*?)</title>', html, re.I|re.S)
            title=t2.group(1).strip() if t2 else None

        if img_url:
            img_url=urljoin(url, img_url)
        img_bytes=fetch_image_bytes_from_url(img_url) if img_url else None
        return title, img_bytes
    except:
        return None, None

# ---------- 推薦/スコアリング ----------
PURPOSES = ["指定なし","通勤","デート","カジュアル","スポーツ","フォーマル","雨の日"]

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
    # ゆるいヒューリスティック
    if b=="straight":   # 骨格ストレート
        if category in ["ボトムス"] and any(k in n for k in ["テーパード","センタープレス","ストレート"]): return 1
        if category in ["トップス","アウター"] and any(k in n for k in ["vネック","襟付き","構築的","ジャケット"]): return 1
    if b=="wave":       # 骨格ウェーブ
        if category in ["ボトムス"] and any(k in n for k in ["ハイウエスト","aライン","フレア"]): return 1
        if category in ["トップス"] and any(k in n for k in ["短丈","クロップド","柔らかい","リブ"]): return 1
    if b=="natural":    # 骨格ナチュラル
        if any(k in n for k in ["ワイド","オーバーサイズ","ドロップショルダー","リネン","ツイード"]): return 1
    return 0

def weather_bonus(material:str|None, felt:int, rainy:bool)->int:
    m=(material or "").lower()
    s=0
    if felt>=27 and any(k in m for k in ["linen","リネン","cotton","コットン","メッシュ","ドライ"]): s+=1
    if felt<=12 and any(k in m for k in ["wool","ウール","ダウン","中綿","フリース"]): s+=1
    if rainy and any(k in m for k in ["ナイロン","nylon","ゴア","gore","防水","撥水"]): s+=1
    return s

def color_pair_score(top_hex:str, item_hex:str, season:str|None)->float:
    # 補色/類似/トライアド候補への距離 + シーズンパレット近さ
    r = adjust_harmony(top_hex,"complement")+adjust_harmony(top_hex,"analogous")+adjust_harmony(top_hex,"triadic")
    # 最小距離
    def dist(h1,h2):
        r1,g1,b1=hex_to_rgb(h1); r2,g2,b2=hex_to_rgb(h2); return (r1-r2)**2+(g1-g2)**2+(b1-b2)**2
    d = min([dist(item_hex, h) for h in r] + [dist(item_hex, top_hex)])
    return d + 0.1*palette_distance(item_hex, season)

def pick_best(items, top_hex, season, body_shape, want, felt, rainy, category):
    cand=[it for it in items if it[2]==category]  # (id,name,cat,color_hex,season_pref,material,img,notes)
    if not cand: return None, 1e9
    scored=[]
    for row in cand:
        iid,nm,cat,hx,sp,mat,imgb,nts=row
        s  = color_pair_score(top_hex, hx, season)
        s -= 200 if sp and season and sp==season else 0
        s -= 120*purpose_match(nts or "", want)
        s -= 80*body_shape_bonus(nts or "", body_shape, cat)
        s -= 60*weather_bonus(mat, felt, rainy)
        scored.append((s,row))
    scored.sort(key=lambda x:x[0])
    return scored[0][1], scored[0][0]

def generate_outfit_from_closet(all_items, season, body_shape, want, felt, rainy):
    # 1) 主役トップを自動選択（季節×体格×目的で最良）
    tops=[it for it in all_items if it[2]=="トップス"]
    if not tops: return None, None
    t_best=None; t_score=1e9
    for row in tops:
        _,_,cat,hx,sp,mat,imgb,nts=row
        s  = 0.2*palette_distance(hx, season)
        s -= 100*(sp==season) if sp and season else 0
        s -= 80*body_shape_bonus(nts or "", body_shape, cat)
        s -= 40*weather_bonus(mat, felt, rainy)
        if s<t_score: t_score=s; t_best=row
    top=t_best
    # 2) 他アイテム
    bottom,b_sc = pick_best(all_items, top[3], season, body_shape, want, felt, rainy, "ボトムス")
    shoes ,s_sc = pick_best(all_items, top[3], season, body_shape, want, felt, rainy, "シューズ")
    bag   ,g_sc = pick_best(all_items, top[3], season, body_shape, want, felt, rainy, "バッグ")
    total_score = t_score + b_sc + s_sc + g_sc
    return {"top":top,"bottom":bottom,"shoes":shoes,"bag":bag}, total_score

# ---------- UI ----------
init_db()
profile = load_profile()

st.title("📱 Outfit Log — モバイル（URL取込・AIコーデ・評価対応）")
tab1, tabCal, tabCloset, tabAI, tabWx, tabProfile = st.tabs(
    ["📒 記録","📅 カレンダー","🧳 クローゼット","🤖 AIコーデ","☀ 天気","👤 プロフィール"]
)

SIL_TOP = ["ジャスト/レギュラー","オーバーサイズ","クロップド/短丈","タイト/フィット"]
SIL_BOTTOM = ["ストレート","ワイド/フレア","スキニー/テーパード","Aライン/スカート","ショーツ"]

# ===== 記録 =====
with tab1:
    st.subheader("今日のコーデを記録")
    d = st.date_input("日付", value=pd.Timestamp.today(), key="rec_date")
    up = st.file_uploader("写真をアップ（カメラ可）", type=["jpg","jpeg","png","webp"], key="rec_photo")
    colA, colB = st.columns(2)
    top_sil = colA.selectbox("トップのシルエット", SIL_TOP, index=0, key="rec_top_sil")
    bottom_sil = colB.selectbox("ボトムのシルエット", SIL_BOTTOM, index=0, key="rec_bottom_sil")
    notes = st.text_area("メモ", placeholder="例：20℃/カフェ/よく歩く", key="rec_notes")

    auto_colors=[]
    if up is not None:
        img = Image.open(up).convert("RGB")
        st.image(img, caption="プレビュー", use_container_width=True)
        auto_colors = extract_dominant_colors(img, k=5)
        st.caption("写真から主要色")
        cols = st.columns(len(auto_colors) or 1)
        for i,cx in enumerate(auto_colors or ["#888888"]):
            cols[i].markdown(f"<div style='width:24px;height:24px;background:{cx};border:1px solid #aaa;border-radius:6px'></div>", unsafe_allow_html=True)

    default_top = auto_colors[0] if auto_colors else "#2f2f2f"
    default_bottom = (auto_colors[1] if len(auto_colors)>1 else "#c9c9c9") if auto_colors else "#c9c9c9"
    col1, col2 = st.columns(2)
    top_color = col1.color_picker("トップ色", default_top, key="rec_top_color")
    bottom_color = col2.color_picker("ボトム色", default_bottom, key="rec_bottom_color")

    if st.button("保存する", type="primary", key="rec_save", disabled=(up is None)):
        img_bytes = up.read()
        insert_outfit(str(pd.to_datetime(d).date()), profile.get("season"), top_sil, bottom_sil, top_color, bottom_color, auto_colors, img_bytes, notes)
        st.success("保存しました！")

# ===== カレンダー =====
with tabCal:
    st.subheader("月間カレンダー（タップで詳細）")
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
                    try: st.image(img_from_bytes(slots[0][8]), use_container_width=True)
                    except: pass
                    if st.button("詳細", key=f"detail_{d0.isoformat()}"):
                        st.session_state["modal_day"] = str(d0)

    if st.session_state["modal_day"]:
        day = st.session_state["modal_day"]
        lst = fetch_outfits_on(day)
        st.markdown("<div style='position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:10000'>", unsafe_allow_html=True)
        with st.container():
            st.markdown("<div class='card' style='width:92%;max-width:640px'>", unsafe_allow_html=True)
            st.markdown(f"### {day} の記録")
            if st.button("× 閉じる", key="cal_close"):
                st.session_state["modal_day"] = None
                st.experimental_rerun()
            for row in lst:
                oid, dd, seas, ts, bs, tc, bc, cols_js, img_b, nt = row
                colm = st.columns([1,2])
                with colm[0]:
                    try: st.image(img_from_bytes(img_b), use_container_width=True)
                    except: st.write("画像なし")
                with colm[1]:
                    st.write(f"Season: {seas or '-'} / Top:{ts}({tc}) / Bottom:{bs}({bc})")
                    st.caption(nt or "")
                    if st.button("🖼 共有画像を作る", key=f"export_{oid}"):
                        prof = load_profile()
                        wx = None
                        if prof.get("home_lat") and prof.get("home_lon"):
                            data = fetch_open_meteo(prof["home_lat"], prof["home_lon"])
                            if data and "daily" in data: wx = weather_tip(data["daily"])
                        imgbytes = make_share_card(row, out_path=f"data/exports/share_{oid}.png", weather=wx)
                        st.download_button("画像をDL", data=imgbytes, file_name=f"outfit_{dd}_{oid}.png", mime="image/png", key=f"dl_{oid}")
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

# ===== クローゼット =====
with tabCloset:
    st.subheader("アイテム追加")
    add_mode = st.radio("追加方法", ["写真から追加","URLから追加"], horizontal=True, key="cl_add_mode")

    if add_mode=="写真から追加":
        colC = st.columns(2)
        name = colC[0].text_input("名前/アイテム名", placeholder="例：オーバーシャツ", key="cl_name")
        category = colC[1].selectbox("カテゴリ", ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"], key="cl_category")
        color_hex = st.color_picker("色", "#2f2f2f", key="cl_color")
        colC2 = st.columns(2)
        season_pref = colC2[0].selectbox("得意シーズン", ["指定なし","spring","summer","autumn","winter"], index=0, key="cl_season")
        material = colC2[1].text_input("素材", placeholder="例：コットン/ウール/リネン/ナイロン", key="cl_material")
        upi = st.file_uploader("アイテム画像", type=["jpg","jpeg","png","webp"], key="cl_img")
        notes_i = st.text_area("メモ（用途/特徴）", placeholder="例：撥水 スニーカー / センタープレス / Vネック", key="cl_notes")

        if st.button("追加する", key="cl_add_btn"):
            img_b = upi.read() if upi else None
            add_item(name or "Unnamed", category, color_hex, None if season_pref=="指定なし" else season_pref, material, img_b, notes_i)
            st.success("追加しました")

    else:  # URLから追加（UNIQLO/ZOZOTOWN等）
        url = st.text_input("商品ページのURL", placeholder="https://...", key="cl_url")
        if st.button("ページを解析", key="cl_parse"):
            title, img_bytes = fetch_from_page(url)
            if not title and not img_bytes:
                st.error("取得できませんでした。URLをご確認ください。")
            else:
                colors = []
                if img_bytes:
                    img = img_from_bytes(img_bytes)
                    st.image(img, caption=title or "画像", use_container_width=True)
                    colors = extract_dominant_colors(img, k=5)
                st.session_state["url_title"]=title
                st.session_state["url_img"]=img_bytes
                st.session_state["url_colors"]=colors
                st.success("候補を読み込みました")

        title = st.session_state.get("url_title")
        img_bytes = st.session_state.get("url_img")
        colors = st.session_state.get("url_colors", [])
        colU = st.columns(2)
        name_url = colU[0].text_input("名前/アイテム名", value=title or "", key="cl_name_url")
        category_url = colU[1].selectbox("カテゴリ", ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"], key="cl_category_url")
        color_url = st.color_picker("色（推定を調整可）", colors[0] if colors else "#2f2f2f", key="cl_color_url")
        material_url = st.text_input("素材", placeholder="例：コットン/ナイロン", key="cl_material_url")
        notes_url = st.text_area("メモ", value=(url or ""), key="cl_notes_url")
        if st.button("この内容で追加", key="cl_add_btn_url", disabled=(not name_url and img_bytes is None)):
            add_item(name_url or "Unnamed", category_url, color_url, None, material_url, img_bytes, notes_url)
            st.success("追加しました（URLから）")

    st.markdown("---")
    st.subheader("クローゼット一覧 / 編集")
    filt = st.selectbox("カテゴリで絞り込み", ["すべて","トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"], index=0, key="cl_filter")
    items = list_items(filt)
    st.caption(f"{len(items)}件")
    for iid, nm, cat, hx, sp, mat, imgb, nts in items:
        with st.expander(f"{nm}（{cat}）", expanded=False):
            colv = st.columns([1,2])
            with colv[0]:
                if imgb: 
                    try: st.image(img_from_bytes(imgb), use_container_width=True)
                    except: st.write("画像なし")
                else: st.write("画像なし")
            with colv[1]:
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
                eup = st.file_uploader("画像を差し替え（任意）", type=["jpg","jpeg","png","webp"], key=f"edit_img_{iid}")
                if st.button("保存", key=f"edit_save_{iid}"):
                    new_img_bytes = eup.read() if eup else None
                    update_item(iid, ename, ecat, ehx, None if esp=="指定なし" else esp, emat, new_img_bytes, enotes)
                    st.success("保存しました（再読込で反映）")

# ===== AIコーデ =====
with tabAI:
    st.subheader("🤖 登録アイテムからAIコーデを提案（評価つき）")
    all_items = list_items("すべて")
    if not all_items:
        st.info("まずはクローゼットにアイテムを登録してください。")
    else:
        colctx = st.columns(3)
        want = colctx[0].selectbox("用途", PURPOSES, index=0, key="ai_want")
        felt = colctx[1].slider("体感温度（℃）", 0, 40, 22, key="ai_felt")
        rainy= colctx[2].toggle("今日は雨", value=False, key="ai_rain")
        season = profile.get("season")
        body_shape = profile.get("body_shape")

        if st.button("コーデを生成", key="ai_gen"):
            outfit, score = generate_outfit_from_closet(all_items, season, body_shape, want, int(felt), bool(rainy))
            if not outfit:
                st.warning("候補が見つかりませんでした（トップス/ボトムス/靴/バッグを登録してください）。")
            else:
                st.markdown("### 提案セット")
                cols = st.columns(4)
                labels=[("トップ","top"),("ボトム","bottom"),("靴","shoes"),("バッグ","bag")]
                for j,(label,key) in enumerate(labels):
                    with cols[j]:
                        row = outfit[key]
                        if row:
                            if row[6]: st.image(img_from_bytes(row[6]), use_container_width=True)
                            st.caption(f"{label}：{row[1]} / {row[3]}")
                        else:
                            st.caption(f"{label}：候補なし")

                st.caption(f"内部スコア（小さいほど適合）：{score:.1f}")
                rating = st.select_slider("このコーデの評価", options=[1,2,3,4,5], value=4, key="ai_rating")
                if st.button("保存（履歴に残す）", key="ai_save"):
                    save_coord(outfit["top"][0], outfit["bottom"][0] if outfit["bottom"] else None,
                               outfit["shoes"][0] if outfit["shoes"] else None,
                               outfit["bag"][0] if outfit["bag"] else None,
                               {"want":want,"felt":felt,"rainy":rainy,"season":season,"body_shape":body_shape},
                               float(score), int(rating))
                    st.success("保存しました！✨ ありがとう、評価は次回の学習に使われます。")

# ===== 天気 =====
with tabWx:
    st.subheader("☀ 天気 × コーデメモ")
    try:
        q = st.query_params
        lat_q = q.get("lat", None); lon_q = q.get("lon", None)
    except Exception:
        q = st.experimental_get_query_params()
        lat_q = q.get("lat", [None])[0]; lon_q = q.get("lon", [None])[0]

    city = st.text_input("都市名（メモ用）", value=profile.get("city") or "Tokyo", key="wx_city")
    colLL = st.columns(2)
    lat = colLL[0].number_input("緯度", value=float(lat_q) if lat_q else float(profile.get("home_lat") or 35.68), step=0.01, format="%.5f", key="wx_lat")
    lon = colLL[1].number_input("経度", value=float(lon_q) if lon_q else float(profile.get("home_lon") or 139.76), step=0.01, format="%.5f", key="wx_lon")

    if st.button("📍 現在地を取得（位置情報を許可）", key="wx_geo"):
        st.markdown("""
        <script>
        (function(){
          if (!navigator.geolocation) { alert("ブラウザが位置情報に未対応です"); return; }
          navigator.geolocation.getCurrentPosition(function(pos){
            const lat = pos.coords.latitude.toFixed(5);
            const lon = pos.coords.longitude.toFixed(5);
            const url = new URL(window.location.href);
            url.searchParams.set('lat', lat);
            url.searchParams.set('lon', lon);
            window.location.href = url.toString();
          }, function(err){
            alert("位置情報を取得できませんでした: " + err.message);
          }, {enableHighAccuracy:true, timeout:8000, maximumAge:0});
        })();
        </script>
        """, unsafe_allow_html=True)

    if st.button("保存（位置）", key="wx_save"):
        save_profile(city=city, home_lat=float(lat), home_lon=float(lon))
        st.success("保存しました")

    data = fetch_open_meteo(lat, lon)
    if data and "daily" in data:
        st.info(weather_tip(data["daily"]))
    else:
        st.warning("天気が取得できませんでした。")

# ===== プロフィール =====
with tabProfile:
    st.subheader("👤 体格・パーソナルカラー設定")
    colp = st.columns(2)
    season = colp[0].selectbox("PCシーズン", ["未設定","spring","summer","autumn","winter"],
                               index=(["未設定","spring","summer","autumn","winter"].index(profile.get("season")) if profile.get("season") else 0),
                               key="prof_season")
    body_shape = colp[1].selectbox("体格タイプ", ["未設定","straight","wave","natural"],
                                   index=(["未設定","straight","wave","natural"].index(profile.get("body_shape")) if profile.get("body_shape") else 0),
                                   key="prof_body")
    height = st.number_input("身長（cm / 任意）", min_value=120.0, max_value=220.0, step=0.5,
                             value=float(profile.get("height_cm") or 165.0), key="prof_height")

    if st.button("保存する", key="prof_save"):
        save_profile(season=None if season=="未設定" else season,
                     body_shape=None if body_shape=="未設定" else body_shape,
                     height_cm=float(height))
        st.success("プロフィールを保存しました。AI提案に反映されます。")

st.caption("※ use_container_width で警告解消 / URL取込は ZOZO/UNIQLO を含む多くのサイトの og:image/twitter:image/JSON-LD に対応。")
