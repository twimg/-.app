# app.py
# Outfit Log — Mobile Plus
# スマホ完結：日記録/カレンダー/クローゼット/天気/カラー名/自動コーデ/共有画像/PWA風（任意）
# 使い方:
#   pip install -r requirements.txt
#   streamlit run app.py

import streamlit as st
import pandas as pd
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import sqlite3, os, io, math, requests, colorsys, calendar, json
from datetime import date, datetime, timedelta
from typing import List, Tuple, Optional

st.set_page_config(page_title="Outfit Log — Mobile", layout="centered")

# ---- PWA-ish meta（なくても動作OK） ----
st.markdown("""
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<link rel="manifest" href="manifest.webmanifest">
<script>
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('service_worker.js').catch(e=>console.log('SW reg err', e));
  });
}
</script>
""", unsafe_allow_html=True)

# ----------------------- DB -----------------------
DB_PATH = "data/app.db"

def init_db():
    os.makedirs("data", exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS outfits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            d TEXT, season TEXT, top_sil TEXT, bottom_sil TEXT,
            top_color TEXT, bottom_color TEXT, colors TEXT, notes TEXT, img BLOB
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS profile (
            id INTEGER PRIMARY KEY CHECK (id=1),
            season TEXT, undertone TEXT, home_lat REAL, home_lon REAL, city TEXT
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, category TEXT, color_hex TEXT, season_pref TEXT,
            material TEXT, img BLOB, notes TEXT
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS outfit_items (
            outfit_id INTEGER, item_id INTEGER,
            PRIMARY KEY (outfit_id, item_id)
        )""")
        conn.commit()

def json_dumps(x): return json.dumps(x, ensure_ascii=False)
def json_loads(x):
    try: return json.loads(x) if x else []
    except: return []

def insert_outfit(d, season, top_sil, bottom_sil, top_color, bottom_color, colors_list, img_bytes, notes):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""INSERT INTO outfits(d, season, top_sil, bottom_sil, top_color, bottom_color, colors, img, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (d, season, top_sil, bottom_sil, top_color, bottom_color, json_dumps(colors_list), img_bytes, notes))
        conn.commit()

def fetch_outfits(d_from=None, d_to=None):
    q = "SELECT id, d, season, top_sil, bottom_sil, top_color, bottom_color, colors, img, notes FROM outfits"
    params = []
    if d_from and d_to:
        q += " WHERE d BETWEEN ? AND ?"
        params = [d_from, d_to]
    q += " ORDER BY d DESC, id DESC"
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        rows = cur.execute(q, params).fetchall()
    return rows

def fetch_outfits_on(day_str: str):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        rows = cur.execute("""SELECT id, d, season, top_sil, bottom_sil, top_color, bottom_color, colors, img, notes 
                              FROM outfits WHERE d=? ORDER BY id DESC""", (day_str,)).fetchall()
    return rows

def load_profile():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        row = cur.execute("SELECT season, undertone, home_lat, home_lon, city FROM profile WHERE id=1").fetchone()
    if row:
        return {"season": row[0], "undertone": row[1], "home_lat": row[2], "home_lon": row[3], "city": row[4]}
    return {"season": None, "undertone": None, "home_lat": None, "home_lon": None, "city": None}

def save_profile(season=None, undertone=None, home_lat=None, home_lon=None, city=None):
    prof = load_profile()
    season = prof["season"] if season is None else season
    undertone = prof["undertone"] if undertone is None else undertone
    home_lat = prof["home_lat"] if home_lat is None else home_lat
    home_lon = prof["home_lon"] if home_lon is None else home_lon
    city = prof["city"] if city is None else city
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO profile(id, season, undertone, home_lat, home_lon, city) VALUES (1, ?, ?, ?, ?, ?)",
                    (season, undertone, home_lat, home_lon, city))
        conn.commit()

def add_item(name, category, color_hex, season_pref, material, img_bytes, notes):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""INSERT INTO items(name, category, color_hex, season_pref, material, img, notes)
                       VALUES (?,?,?,?,?,?,?)""", (name, category, color_hex, season_pref, material, img_bytes, notes))
        conn.commit()

def list_items(category=None):
    q = "SELECT id, name, category, color_hex, season_pref, material, img, notes FROM items"
    params = []
    if category and category != "すべて":
        q += " WHERE category=?"
        params = [category]
    q += " ORDER BY id DESC"
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        rows = cur.execute(q, params).fetchall()
    return rows

# ----------------------- Color utils & naming -----------------------
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

def nearest_css_name(hexstr: str) -> str:
    r,g,b = hex_to_rgb(hexstr)
    best, bestd = None, 1e9
    for name, hx in CSS_COLORS.items():
        rr,gg,bb = hex_to_rgb(hx)
        d = (r-rr)**2 + (g-gg)**2 + (b-bb)**2
        if d < bestd: bestd, best = d, name
    return best

def hex_family(hexstr: str) -> str:
    r,g,b = [v/255 for v in hex_to_rgb(hexstr)]
    h,s,v = colorsys.rgb_to_hsv(r,g,b)
    hue = h*360
    if v < 0.15: return "black"
    if s < 0.15 and v > 0.9: return "white"
    if s < 0.20: return "gray"
    if 0   <= hue < 15:  return "red"
    if 15  <= hue < 45:  return "orange"
    if 45  <= hue < 65:  return "yellow"
    if 65  <= hue < 170: return "green"
    if 170 <= hue < 200: return "cyan"
    if 200 <= hue < 255: return "blue"
    if 255 <= hue < 290: return "purple"
    if 290 <= hue < 330: return "magenta"
    return "red"

def adjust_harmony(hexstr: str, mode="complement", delta=30) -> List[str]:
    r,g,b = [v/255 for v in hex_to_rgb(hexstr)]
    h,s,v = colorsys.rgb_to_hsv(r,g,b)
    def wrap(deg): 
        x = (h*360 + deg) % 360
        return x/360.0
    outs = []
    if mode == "complement":
        hs = [wrap(180)]
    elif mode == "analogous":
        hs = [wrap(+delta), wrap(-delta)]
    elif mode == "triadic":
        hs = [wrap(+120), wrap(-120)]
    else:
        hs = []
    for hh in hs:
        rr,gg,bb = colorsys.hsv_to_rgb(hh, s, v)
        outs.append(rgb_to_hex((int(rr*255), int(gg*255), int(bb*255))))
    return outs

def extract_dominant_colors(img: Image.Image, k: int = 5) -> List[str]:
    small = img.copy(); small.thumbnail((200,200))
    pal = small.convert("P", palette=Image.ADAPTIVE, colors=k)
    palette = pal.getpalette(); color_counts = pal.getcolors()
    if not color_counts: return ["#888888"]
    color_counts.sort(reverse=True)
    out, seen = [], set()
    for count, idx in color_counts[:k*2]:
        r,g,b = palette[idx*3: idx*3+3]
        hx = rgb_to_hex((r,g,b))
        fam = hex_family(hx)
        key = (fam, (r,g,b))
        if key not in seen:
            out.append(hx); seen.add(key)
        if len(out) >= k: break
    return out

# ----------------------- Advice -----------------------
SIL_TOP = ["ジャスト/レギュラー", "オーバーサイズ", "クロップド/短丈", "タイト/フィット"]
SIL_BOTTOM = ["ストレート", "ワイド/フレア", "スキニー/テーパード", "Aライン/スカート", "ショーツ"]

def shape_advice(top_sil: str, bottom_sil: str) -> str:
    pairs = []
    if top_sil == "オーバーサイズ":
        pairs.append("下は細め（スキニー/テーパード）でY字バランス◎")
    if top_sil in ("クロップド/短丈", "タイト/フィット"):
        pairs.append("ワイド/フレアやAラインで脚長見え")
    if bottom_sil == "ワイド/フレア":
        pairs.append("上はコンパクト（短丈 or タイト）でA字を作る")
    if bottom_sil == "スキニー/テーパード":
        pairs.append("上はボリューム（オーバー/レギュラー）でバランス")
    if not pairs:
        pairs.append("上ゆる×下細で緩急をつけると締まります")
    return " / ".join(pairs)

def color_advice(top_hex: str, bottom_hex: str, season: Optional[str]) -> str:
    tips = []
    fam_top, fam_bottom = hex_family(top_hex), hex_family(bottom_hex)
    if fam_top not in ("black","gray","white","blue","beige") and fam_bottom not in ("black","gray","white","blue","beige"):
        tips.append("上下どちらかはニュートラル（黒/白/グレー/ネイビー/ベージュ）推奨")
    comp = adjust_harmony(top_hex, "complement")[0]
    if hex_family(comp) == hex_family(bottom_hex):
        tips.append("補色の強対比 → 面積比7:3で調整（片方は小物化も◎）")
    if season:
        stips = {
            "spring": "明るく軽やか（コーラル/ライム/ライトベージュ）",
            "summer": "青み＆ソフト（ラベンダー/スモーキーブルー/グレージュ）",
            "autumn": "深み＆黄み（テラコッタ/オリーブ/キャメル）",
            "winter": "高コントラスト＆ビビッド（黒白/ロイヤルブルー等）"
        }.get(season)
        if stips: tips.append(stips)
    if not tips:
        tips.append("同系色の濃淡で大人っぽく（例：ネイビー×ライトブルー）")
    return " / ".join(tips)

# ----------------------- Personal Color -----------------------
SEASON_PALETTES = {
    "spring": ["#ffb3a7","#ffd28c","#ffe680","#b7e07a","#8ed1c8","#ffd7ef","#f5deb3"],
    "summer": ["#c8cbe6","#b0c4de","#c3b1e1","#9fd3c7","#d8d8d8","#e6d5c3","#a3bcd6"],
    "autumn": ["#a0522d","#c68642","#8f9779","#556b2f","#b5651d","#6b4f3f","#8b6c42"],
    "winter": ["#000000","#ffffff","#4169e1","#8a2be2","#ff1493","#00ced1","#2f4f4f"],
}

def diagnose_season(answers: dict):
    warm = (answers.get("gold_silver")=="gold") + (answers.get("vein")=="green") + (answers.get("white_offwhite")=="offwhite")
    cool = (answers.get("gold_silver")=="silver") + (answers.get("vein")=="blue") + (answers.get("white_offwhite")=="white")
    undertone = "warm" if warm>cool else ("cool" if cool>warm else "neutral")
    high_contrast = (answers.get("contrast")=="high")
    bright = (answers.get("chroma")=="bright")
    if undertone=="warm":
        season = "spring" if bright else "autumn"
    elif undertone=="cool":
        season = "winter" if high_contrast or bright else "summer"
    else:
        season = "summer"
    return season, undertone

# ----------------------- Weather -----------------------
def fetch_open_meteo(lat: float, lon: float):
    try:
        url = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
               "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto").format(lat=lat, lon=lon)
        r = requests.get(url, timeout=6)
        if r.status_code==200:
            return r.json()
    except Exception:
        return None
    return None

def weather_tip(daily):
    try:
        tmax = daily["temperature_2m_max"][0]
        tmin = daily["temperature_2m_min"][0]
        prcp = daily["precipitation_probability_max"][0]
    except:
        return "天気情報を取得できませんでした。"
    msg = []
    if tmax >= 27: msg.append("暑い：半袖/軽素材/通気◎")
    elif tmax >= 20: msg.append("穏やか：長袖1枚 or 薄羽織")
    elif tmax >= 12: msg.append("肌寒い：薄手ニット/ライトアウター")
    else: msg.append("寒い：コート/中綿/マフラー")
    if prcp >= 50: msg.append("降水高め：撥水アウター/防水シューズ/傘を")
    return " / ".join(msg)+f"（最高{tmax:.0f}℃・最低{tmin:.0f}℃・降水{prcp}%）"

# ----------------------- UI helpers -----------------------
def color_swatch(hexes: List[str], size=24):
    cols = st.columns(len(hexes))
    for i, hx in enumerate(hexes):
        cols[i].markdown(f"<div style='width:{size}px;height:{size}px;background:{hx};border:1px solid #aaa;border-radius:6px'></div>", unsafe_allow_html=True)

def img_from_bytes(b: bytes) -> Image.Image:
    return Image.open(io.BytesIO(b)).convert("RGB")

def dist_rgb(h1, h2):
    r1,g1,b1 = hex_to_rgb(h1); r2,g2,b2 = hex_to_rgb(h2)
    return (r1-r2)**2+(g1-g2)**2+(b1-b2)**2

# ----------------------- Auto outfit generator -----------------------
def score_item_for_top(item_hex: str, top_hex: str, season_pref: Optional[str], user_season: Optional[str]) -> float:
    # 色スコア：補色/類似/トライアド候補との距離最小を使用
    harmonies = adjust_harmony(top_hex, "complement") + adjust_harmony(top_hex, "analogous") + adjust_harmony(top_hex, "triadic")
    color_d = min([dist_rgb(item_hex, h) for h in harmonies] + [dist_rgb(item_hex, top_hex)])
    # 季節マッチ加点
    season_bonus = -500 if (season_pref and user_season and season_pref==user_season) else 0
    return color_d + season_bonus

def pick_best(items, top_hex, user_season, category):
    cand = [it for it in items if it[2]==category]  # (id, name, category, color_hex, season_pref, material, img, notes)
    if not cand: return None
    scored = []
    for row in cand:
        iid, nm, cat, hx, sp, mat, imgb, nts = row
        s = score_item_for_top(hx, top_hex, sp, user_season)
        scored.append((s, row))
    scored.sort(key=lambda x: x[0])
    return scored[0][1] if scored else None

def generate_outfit(top_item_row, all_items, user_season):
    if not top_item_row: return None
    top_hex = top_item_row[3]
    choose_bottom = pick_best(all_items, top_hex, user_season, "ボトムス")
    choose_shoes  = pick_best(all_items, top_hex, user_season, "シューズ")
    choose_bag    = pick_best(all_items, top_hex, user_season, "バッグ")
    return {"top": top_item_row, "bottom": choose_bottom, "shoes": choose_shoes, "bag": choose_bag}

# ----------------------- Share card -----------------------
def make_share_card(outfit_row, out_path="data/exports/share.png", weather=None):
    # outfit_row: (id, d, season, top_sil, bottom_sil, top_color, bottom_color, colors, img, notes)
    W, H = 1080, 1350  # portrait
    os.makedirs("data/exports", exist_ok=True)
    base = Image.new("RGB", (W,H), (250,250,250))
    draw = ImageDraw.Draw(base)

    # Header
    draw.rectangle((0,0,W,120), fill=(17,17,17))
    draw.text((40,40), "Outfit Log", fill=(255,255,255))

    # Photo
    y = 140
    try:
        img = img_from_bytes(outfit_row[8])
        # Center-crop to 4:5 then fit
        target_ratio = 4/5
        iw, ih = img.width, img.height
        if iw/ih > target_ratio:
            new_w = int(ih*target_ratio); x0 = (iw-new_w)//2; box = (x0, 0, x0+new_w, ih)
        else:
            new_h = int(iw/target_ratio); y0 = (ih-new_h)//2; box = (0, y0, iw, y0+new_h)
        img = img.crop(box).resize((W-160, 720), Image.LANCZOS)
        bx = (W - img.width)//2
        base.paste(img, (bx, y))
        y += img.height + 16
    except Exception:
        y += 16

    # Colors
    try:
        colors = json_loads(outfit_row[7])[:5]
    except:
        colors = []
    sw = 80; gap=16
    for i,hx in enumerate(colors):
        x = 100 + i*(sw+gap)
        draw.rectangle((x, y, x+sw, y+sw), fill=hex_to_rgb(hx), outline=(30,30,30))
    y += sw + 16

    # Text info
    top = outfit_row[5]; bottom = outfit_row[6]
    draw.text((100, y), f"Top: {top}  ({nearest_css_name(top)})", fill=(0,0,0)); y += 32
    draw.text((100, y), f"Bottom: {bottom}  ({nearest_css_name(bottom)})", fill=(0,0,0)); y += 32

    # Weather
    if weather:
        draw.text((100, y), f"Weather: {weather}", fill=(40,40,40)); y += 30

    # Footer
    dd = outfit_row[1]; seas = outfit_row[2] or "-"
    draw.text((100, H-80), f"{dd} / {seas}", fill=(60,60,60))
    draw.text((100, H-50), "Made with Outfit Log — Mobile Plus", fill=(80,80,80))

    base.save(out_path, "PNG")
    with open(out_path, "rb") as f:
        return f.read()

# ----------------------- Styles -----------------------
st.markdown("""
<style>
html, body, .block-container {max-width: 720px; margin:auto;}
button[kind="primary"] {padding:14px 18px; font-size:1.05rem;}
.stTabs [role="tab"] {padding:12px 10px; font-size:0.95rem;}
.card {border:1px solid #eee; border-radius:12px; padding:10px; margin:8px 0; background:#fff;}
.small {color:#666; font-size:0.9rem}
</style>
""", unsafe_allow_html=True)

# ----------------------- App -----------------------
init_db()
profile = load_profile()

st.title("📱 Outfit Log — モバイル")

tab1, tabCal, tabCloset, tabAuto, tabWx, tabAdvice, tabPC = st.tabs(["📒 記録", "📅 カレンダー", "🧳 クローゼット", "🤖 自動コーデ", "☀ 天気", "🎨 アドバイス", "🧑‍🎨 PC診断"])

# ---- 記録
with tab1:
    st.subheader("今日のコーデを記録")
    d = st.date_input("日付", value=date.today())
    up = st.file_uploader("写真", type=["jpg","jpeg","png","webp"], accept_multiple_files=False)
    colA, colB = st.columns(2)
    top_sil = colA.selectbox("トップのシルエット", SIL_TOP, index=0)
    bottom_sil = colB.selectbox("ボトムのシルエット", SIL_BOTTOM, index=0)
    notes = st.text_area("メモ", placeholder="例：20℃/カフェ/よく歩く")

    auto_colors = []
    if up is not None:
        img = Image.open(up).convert("RGB")
        st.image(img, caption="プレビュー", use_column_width=True)
        auto_colors = extract_dominant_colors(img, k=5)
        st.caption("写真から主要色")
        color_swatch(auto_colors)

    default_top = auto_colors[0] if auto_colors else "#2f2f2f"
    default_bottom = (auto_colors[1] if len(auto_colors)>1 else "#c9c9c9") if auto_colors else "#c9c9c9"
    col1, col2 = st.columns(2)
    top_color = col1.color_picker("トップ色", default_top)
    bottom_color = col2.color_picker("ボトム色", default_bottom)
    st.caption(f"Top≈{nearest_css_name(top_color)} / Bottom≈{nearest_css_name(bottom_color)}")

    if st.button("保存する", type="primary", disabled=(up is None)):
        img_bytes = up.read()
        insert_outfit(str(d), profile.get("season"), top_sil, bottom_sil, top_color, bottom_color, auto_colors, img_bytes, notes)
        st.success("保存しました！")

# ---- カレンダー
with tabCal:
    st.subheader("月間カレンダー（タップで詳細）")
    today = date.today()
    colM = st.columns(2)
    year = colM[0].number_input("年", value=today.year, step=1, min_value=2000, max_value=2100)
    month = colM[1].number_input("月", value=today.month, step=1, min_value=1, max_value=12)
    cal = calendar.Calendar(firstweekday=6)  # 日曜始まり
    weeks = cal.monthdatescalendar(int(year), int(month))

    if "modal_day" not in st.session_state:
        st.session_state["modal_day"] = None

    for wk in weeks:
        cols = st.columns(7)
        for i, d0 in enumerate(wk):
            slots = fetch_outfits_on(str(d0))
            with cols[i]:
                style = "padding:6px; border:1px solid #eee; border-radius:8px; min-height:110px; position:relative"
                if d0.month != int(month): style += "; opacity:0.5"
                st.markdown(f"<div style='{style}'><b>{d0.day}</b></div>", unsafe_allow_html=True)
                if slots:
                    try:
                        st.image(img_from_bytes(slots[0][8]), use_column_width=True)
                    except: pass
                    if st.button("詳細", key=f"detail_{d0.isoformat()}"):
                        st.session_state["modal_day"] = str(d0)

    # Modal
    if st.session_state["modal_day"]:
        day = st.session_state["modal_day"]
        lst = fetch_outfits_on(day)
        st.markdown("<div style='position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:10000'>", unsafe_allow_html=True)
        with st.container():
            st.markdown("<div class='card' style='width:92%;max-width:640px'>", unsafe_allow_html=True)
            st.markdown(f"### {day} の記録")
            if st.button("× 閉じる"):
                st.session_state["modal_day"] = None
                st.experimental_rerun()
            for row in lst:
                oid, dd, seas, ts, bs, tc, bc, cols_js, img_b, nt = row
                colm = st.columns([1,2])
                with colm[0]:
                    try: st.image(img_from_bytes(img_b), width=120)
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
                        st.download_button("画像をDL", data=imgbytes, file_name=f"outfit_{dd}_{oid}.png", mime="image/png")
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

# ---- クローゼット
with tabCloset:
    st.subheader("クローゼット")
    colC = st.columns(2)
    with colC[0]:
        name = st.text_input("名前/アイテム名", placeholder="例：オーバーシャツ")
        category = st.selectbox("カテゴリ", ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"])
        color_hex = st.color_picker("色", "#2f2f2f")
        season_pref = st.selectbox("得意シーズン", ["指定なし","spring","summer","autumn","winter"], index=0)
    with colC[1]:
        material = st.text_input("素材", placeholder="例：コットン/ウール/リネン")
        upi = st.file_uploader("アイテム画像", type=["jpg","jpeg","png","webp"], key="item_img")
        notes_i = st.text_area("メモ", placeholder="ブランド/用途など")
    if st.button("アイテムを追加"):
        img_b = upi.read() if upi else None
        add_item(name or "Unnamed", category, color_hex, None if season_pref=="指定なし" else season_pref, material, img_b, notes_i)
        st.success("追加しました")

    st.markdown("### 一覧")
    filt = st.selectbox("カテゴリで絞り込み", ["すべて","トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"], index=0)
    items = list_items(filt)
    st.caption(f"{len(items)}件")
    for iid, nm, cat, hx, sp, mat, imgb, nts in items:
        with st.container():
            c1, c2 = st.columns([1,2])
            with c1:
                if imgb: 
                    try: st.image(img_from_bytes(imgb), width=140)
                    except: st.write("画像なし")
                else: st.write("画像なし")
            with c2:
                st.markdown(f"<div class='card'><b>{nm}</b> / {cat}<br>色:{hx}（{nearest_css_name(hx)}） / 素材:{mat or '-'}<br>得意:{sp or '未指定'}<br>{nts or ''}</div>", unsafe_allow_html=True)

# ---- 自動コーデ
with tabAuto:
    st.subheader("🤖 自動コーデ生成（トップを選ぶ）")
    tops = list_items("トップス")
    if not tops:
        st.info("まずはクローゼットにトップスを登録してください。")
    else:
        top_names = [f"{t[1]} — {t[3]}({nearest_css_name(t[3])})" for t in tops]
        sel = st.selectbox("トップを選択", top_names)
        idx = top_names.index(sel)
        chosen_top = tops[idx]
        st.write("主役色：", chosen_top[3], f"（{nearest_css_name(chosen_top[3])}）")
        st.image(img_from_bytes(chosen_top[6]), width=160) if chosen_top[6] else st.caption("画像なし")

        all_items = list_items("すべて")
        outfit = generate_outfit(chosen_top, all_items, profile.get("season"))
        if outfit:
            st.markdown("### 提案セット")
            cols = st.columns(4)
            with cols[0]:
                st.write("トップ")
                if chosen_top[6]: st.image(img_from_bytes(chosen_top[6]), width=120)
                st.caption(chosen_top[1])
            for j,(label,key) in enumerate([("ボトム","bottom"),("靴","shoes"),("バッグ","bag")]):
                with cols[j+1]:
                    st.write(label)
                    row = outfit[key]
                    if row:
                        if row[6]: st.image(img_from_bytes(row[6]), width=120)
                        st.caption(f"{row[1]} / {row[3]}")
                    else:
                        st.caption("候補なし")
            st.markdown("— 配色候補 —")
            color_swatch([chosen_top[3]] + adjust_harmony(chosen_top[3],"complement") + adjust_harmony(chosen_top[3],"analogous"))
        else:
            st.warning("候補が見つかりませんでした（ボトム/靴/バッグの登録数が少ない可能性）。")

# ---- 天気
with tabWx:
    st.subheader("☀ 天気 × コーデ提案")
    # Query params（新API/旧APIどちらでも）
    try:
        q = st.query_params
        lat_q = q.get("lat", None); lon_q = q.get("lon", None)
    except Exception:
        q = st.experimental_get_query_params()
        lat_q = q.get("lat", [None])[0]; lon_q = q.get("lon", [None])[0]

    city = st.text_input("都市名（メモ用）", value=profile.get("city") or "Tokyo")
    colLL = st.columns(2)
    lat_val = float(lat_q) if lat_q else float(profile.get("home_lat") or 35.68)
    lon_val = float(lon_q) if lon_q else float(profile.get("home_lon") or 139.76)
    lat = colLL[0].number_input("緯度", value=lat_val, step=0.01, format="%.5f")
    lon = colLL[1].number_input("経度", value=lon_val, step=0.01, format="%.5f")

    if st.button("📍 現在地を取得（位置情報を許可）"):
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
            window.location.href = url.toString(); // reload with params
          }, function(err){
            alert("位置情報を取得できませんでした: " + err.message);
          }, {enableHighAccuracy:true, timeout:8000, maximumAge:0});
        })();
        </script>
        """, unsafe_allow_html=True)

    c1,c2,c3 = st.columns(3)
    if c1.button("保存（位置）"):
        save_profile(city=city, home_lat=float(lat), home_lon=float(lon))
        st.success("保存しました")

    data = fetch_open_meteo(lat, lon)
    if data and "daily" in data:
        daily = data["daily"]
        st.info(weather_tip(daily))
        seas = profile.get("season")
        if seas:
            st.write("季節タイプに合う色：", ", ".join(SEASON_PALETTES[seas][:4]))
            color_swatch(SEASON_PALETTES[seas][:6])
    else:
        st.warning("天気が取得できませんでした（位置/通信をご確認ください）。")

# ---- アドバイス
with tabAdvice:
    st.subheader("色 & 形のアドバイス")
    colx = st.columns(2)
    top_color2 = colx[0].color_picker("トップ色", "#2f2f2f")
    bottom_color2 = colx[1].color_picker("ボトム色", "#c9c9c9")
    ts2 = st.selectbox("トップのシルエット", SIL_TOP, index=0)
    bs2 = st.selectbox("ボトムのシルエット", SIL_BOTTOM, index=0)
    st.markdown("**配色ヒント**")
    comp_all = adjust_harmony(top_color2, "complement") + adjust_harmony(top_color2, "analogous") + adjust_harmony(top_color2, "triadic")
    color_swatch([top_color2] + comp_all[:4])
    st.caption("左がトップ色。右は相性候補（全部使う必要はありません）")
    st.success(color_advice(top_color2, bottom_color2, profile.get("season")))
    st.info(shape_advice(ts2, bs2))

# ---- パーソナルカラー
with tabPC:
    st.subheader("パーソナルカラー（簡易）")
    colq1, colq2 = st.columns(2)
    q1 = colq1.radio("ゴールド/シルバー どちらが似合う？", ["gold","silver","どちらも"], index=2, horizontal=True)
    q2 = colq2.radio("手首の血管は？", ["green","blue","どちらも"], index=2, horizontal=True)
    colq3, colq4 = st.columns(2)
    q3 = colq3.radio("真っ白/オフ白 似合うのは？", ["white","offwhite","どちらも"], index=2, horizontal=True)
    q4 = colq4.radio("顔のコントラスト感", ["high","soft","わからない"], index=2, horizontal=True)
    q5 = st.radio("鮮やかさの得意度", ["bright","soft","中間"], index=2, horizontal=True)

    answers = {
        "gold_silver": "gold" if q1=="gold" else ("silver" if q1=="silver" else None),
        "vein": "green" if q2=="green" else ("blue" if q2=="blue" else None),
        "white_offwhite": "white" if q3=="white" else ("offwhite" if q3=="offwhite" else None),
        "contrast": "high" if q4=="high" else ("soft" if q4=="soft" else None),
        "chroma": "bright" if q5=="bright" else ("soft" if q5=="soft" else None),
    }
    if st.button("診断して保存", type="primary"):
        season, undertone = diagnose_season(answers)
        save_profile(season=season, undertone=undertone)
        st.success(f"仮シーズン：{season.title()} / ベース：{undertone} を保存")

    prof = load_profile()
    st.write(f"Season: { (prof['season'] or '未設定').title() if prof['season'] else '未設定' } / Undertone: {prof['undertone'] or '未設定'}")
    if prof.get("season"):
        from itertools import islice
        pal = SEASON_PALETTES.get(prof["season"], [])
        color_swatch(list(islice(pal, 6)))

st.caption("© Outfit Log — Mobile Plus（データは data/app.db に保存。バックアップはこのファイルをコピー）")
