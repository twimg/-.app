# app.py — Outfit Log (Mobile Plus, URL取込 & 編集 / DuplicateElementId対策済)
import streamlit as st
import pandas as pd, numpy as np
from PIL import Image, ImageDraw
import sqlite3, os, io, requests, colorsys, calendar, json
from urllib.parse import urljoin

st.set_page_config(page_title="Outfit Log — Mobile", layout="centered")

# ---------- PWA-ish（なくてもOK） ----------
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
          season TEXT, undertone TEXT, home_lat REAL, home_lon REAL, city TEXT
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS items(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT, category TEXT, color_hex TEXT, season_pref TEXT,
          material TEXT, img BLOB, notes TEXT
        )""")
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
        row = c.execute("SELECT season,undertone,home_lat,home_lon,city FROM profile WHERE id=1").fetchone()
    return {"season":row[0],"undertone":row[1],"home_lat":row[2],"home_lon":row[3],"city":row[4]} if row else \
           {"season":None,"undertone":None,"home_lat":None,"home_lon":None,"city":None}

def save_profile(**kwargs):
    cur = load_profile()
    cur.update({k:v for k,v in kwargs.items() if v is not None})
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO profile(id,season,undertone,home_lat,home_lon,city) VALUES(1,?,?,?,?,?)",
                  (cur["season"], cur["undertone"], cur["home_lat"], cur["home_lon"], cur["city"]))
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

# ---------- URL 取り込み ----------
def fetch_image_bytes_from_url(url:str):
    try:
        r=requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code==200:
            return r.content
    except: return None
    return None

def fetch_from_page(url:str):
    """商品ページURLから og:image と title を推定（bs4ナシ簡易版）"""
    try:
        r=requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code!=200: return None,None
        html=r.text
        import re
        m=re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        img_url=m.group(1) if m else None
        if img_url: img_url=urljoin(url, img_url)
        t=re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        title=t.group(1).strip() if t else None
        if not title:
            t2=re.search(r'<title[^>]*>(.*?)</title>', html, re.I|re.S)
            title=t2.group(1).strip() if t2 else None
        img_bytes=fetch_image_bytes_from_url(img_url) if img_url else None
        return title, img_bytes
    except:
        return None, None

# ---------- UI ----------
init_db()
profile = load_profile()

st.title("📱 Outfit Log — モバイル（URL取込対応）")
tab1, tabCal, tabCloset, tabWx, tabAdvice = st.tabs(
    ["📒 記録","📅 カレンダー","🧳 クローゼット","☀ 天気","🎨 アドバイス"]
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
        st.image(img, caption="プレビュー", use_column_width=True)
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
                    try: st.image(img_from_bytes(slots[0][8]), use_column_width=True)
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
            if st.button("× 閉じる", key="cal_close"):
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
        material = colC2[1].text_input("素材", placeholder="例：コットン/ウール/リネン", key="cl_material")
        upi = st.file_uploader("アイテム画像", type=["jpg","jpeg","png","webp"], key="cl_img")
        notes_i = st.text_area("メモ", placeholder="ブランド/用途など", key="cl_notes")

        if st.button("追加する", key="cl_add_btn"):
            img_b = upi.read() if upi else None
            add_item(name or "Unnamed", category, color_hex, None if season_pref=="指定なし" else season_pref, material, img_b, notes_i)
            st.success("追加しました")

    else:  # URLから追加
        url = st.text_input("商品ページのURL", placeholder="https://...", key="cl_url")
        if st.button("ページを解析", key="cl_parse"):
            title, img_bytes = fetch_from_page(url)
            if not title and not img_bytes:
                st.error("取得できませんでした。URLをご確認ください。")
            else:
                st.session_state["url_title"] = title
                st.session_state["url_img_bytes"] = img_bytes
                st.success("候補を読み込みました")

        title = st.session_state.get("url_title")
        img_bytes = st.session_state.get("url_img_bytes")
        if img_bytes:
            img = img_from_bytes(img_bytes)
            st.image(img, caption=title or "画像", use_column_width=True)
            cols_auto = extract_dominant_colors(img, k=5)
            st.caption("主要色（自動推定）")
            cs = st.columns(len(cols_auto))
            for i,cx in enumerate(cols_auto):
                cs[i].markdown(f"<div style='width:24px;height:24px;background:{cx};border:1px solid #aaa;border-radius:6px'></div>", unsafe_allow_html=True)
        colU = st.columns(2)
        name_url = colU[0].text_input("名前/アイテム名", value=title or "", key="cl_name_url")
        category_url = colU[1].selectbox("カテゴリ", ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"], key="cl_category_url")
        color_url = st.color_picker("色（推定を調整可）", (cols_auto[0] if img_bytes else "#2f2f2f") if (img_bytes) else "#2f2f2f", key="cl_color_url")
        material_url = st.text_input("素材", placeholder="例：コットン/ナイロン", key="cl_material_url")
        notes_url = st.text_area("メモ", value=(url or ""), key="cl_notes_url")
        if st.button("この内容で追加", key="cl_add_btn_url", disabled=(img_bytes is None and (not name_url))):
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
                    try: st.image(img_from_bytes(imgb), width=140)
                    except: st.write("画像なし")
                else: st.write("画像なし")
            with colv[1]:
                ename = st.text_input("名前", value=nm, key=f"edit_name_{iid}")
                ecat = st.selectbox("カテゴリ", ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"],
                                    index=["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"].index(cat) if cat in ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"] else 0,
                                    key=f"edit_cat_{iid}")
                ehx = st.color_picker("色", hx or "#2f2f2f", key=f"edit_color_{iid}")
                esp = st.selectbox("得意シーズン", ["指定なし","spring","summer","autumn","winter"],
                                   index=(["指定なし","spring","summer","autumn","winter"].index(sp) if sp in ["spring","summer","autumn","winter"] else 0),
                                   key=f"edit_season_{iid}")
                emat = st.text_input("素材", value=mat or "", key=f"edit_mat_{iid}")
                enotes = st.text_area("メモ", value=nts or "", key=f"edit_notes_{iid}")
                eup = st.file_uploader("画像を差し替え（任意）", type=["jpg","jpeg","png","webp"], key=f"edit_img_{iid}")
                if st.button("保存", key=f"edit_save_{iid}"):
                    new_img_bytes = eup.read() if eup else None  # Noneなら現画像維持
                    update_item(iid, ename, ecat, ehx, None if esp=="指定なし" else esp, emat, new_img_bytes, enotes)
                    st.success("保存しました（再読込で反映）")

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

# ===== アドバイス =====
with tabAdvice:
    st.subheader("色 & 形のアドバイス")
    colx = st.columns(2)
    top_color2 = colx[0].color_picker("トップ色", "#2f2f2f", key="adv_top_color")
    bottom_color2 = colx[1].color_picker("ボトム色", "#c9c9c9", key="adv_bottom_color")
    ts2 = st.selectbox("トップのシルエット", SIL_TOP, index=0, key="adv_ts")
    bs2 = st.selectbox("ボトムのシルエット", SIL_BOTTOM, index=0, key="adv_bs")

    def color_advice(top_hex: str, bottom_hex: str, season: str|None):
        tips=[]
        fam_top, fam_bottom = hex_family(top_hex), hex_family(bottom_hex)
        if fam_top not in ("black","gray","white","blue","beige") and fam_bottom not in ("black","gray","white","blue","beige"):
            tips.append("上下どちらかはニュートラル（黒/白/グレー/ネイビー/ベージュ）推奨")
        comp = adjust_harmony(top_hex, "complement")[0]
        if hex_family(comp) == hex_family(bottom_hex):
            tips.append("補色の強対比 → 面積比7:3で調整（片方は小物化も◎）")
        if season:
            stips = {
                "spring":"明るく軽やか（コーラル/ライム/ライトベージュ）",
                "summer":"青み＆ソフト（ラベンダー/スモーキーブルー/グレージュ）",
                "autumn":"深み＆黄み（テラコッタ/オリーブ/キャメル）",
                "winter":"高コントラスト＆ビビッド（黒白/ロイヤルブルー等）"
            }.get(season)
            if stips: tips.append(stips)
        if not tips:
            tips.append("同系色の濃淡で大人っぽく（例：ネイビー×ライトブルー）")
        return " / ".join(tips)

    def shape_advice(top_sil: str, bottom_sil: str) -> str:
        pairs=[]
        if top_sil=="オーバーサイズ": pairs.append("下は細め（スキニー/テーパード）でY字バランス◎")
        if top_sil in ("クロップド/短丈","タイト/フィット"): pairs.append("ワイド/フレアやAラインで脚長見え")
        if bottom_sil=="ワイド/フレア": pairs.append("上はコンパクト（短丈 or タイト）でA字を作る")
        if bottom_sil=="スキニー/テーパード": pairs.append("上はボリューム（オーバー/レギュラー）でバランス")
        if not pairs: pairs.append("上ゆる×下細で緩急をつけると締まります")
        return " / ".join(pairs)

    st.success(color_advice(top_color2, bottom_color2, profile.get("season")))
    st.info(shape_advice(ts2, bs2))

st.caption("※ 画像/URLからの取り込み・編集・共有に対応。全ウィジェットに一意な key を付与して重複IDを回避。")
