# app.py — Outf!ts (fix NameError + finer classification/color + grouped list)

import streamlit as st
import pandas as pd, numpy as np
from PIL import Image
import sqlite3, os, io, requests, colorsys, calendar, json, re, html as ihtml
from urllib.parse import urljoin, quote_plus
from datetime import datetime
from collections import defaultdict
from math import sqrt

st.set_page_config(page_title="Outf!ts", layout="centered")

# ---------- Theme ----------
st.markdown("""
<style>
:root{ --bg-a:#f2eee7; --bg-b:#e9e4db; --ink:#222; --accent:#1f7a7a; }
html, body { background: linear-gradient(135deg, var(--bg-a), var(--bg-b)); }
.block-container{ background:#ffffffcc; backdrop-filter: blur(4px); border:1px solid #eee;
  border-radius:16px; padding:14px 12px 24px; }
.stTabs [role="tab"]{ padding:10px 10px; border-radius:10px; font-weight:600; }
.stTabs [role="tab"][aria-selected="true"]{ background:#fff; border:1px solid #ddd; }
button[kind="primary"]{ background: var(--accent) !important; border:0 !important; }
.card{border:1px solid #e9e9e9;border-radius:12px;padding:8px;background:#fff;
      box-shadow:0 3px 8px rgba(0,0,0,.05);}
.card:hover{box-shadow:0 7px 14px rgba(0,0,0,.1); transform: translateY(-1px);}
.badge{display:inline-block;padding:5px 8px;border-radius:999px;border:1px solid #ddd;margin-right:6px;}
.swatch{width:22px;height:22px;border:1px solid #aaa;border-radius:6px;display:inline-block;margin-right:6px;}
.mini{width:14px;height:14px;border:1px solid #aaa;border-radius:4px;display:inline-block;margin-right:4px;}
.small{font-size:12px;color:#666}
.pill{border:1px solid #ddd;border-radius:999px;padding:2px 7px;font-size:12px;color:#555}
.cap{font-size:12px;color:#666;margin-top:4px}
.kpi{display:inline-block;background:#fff;border:1px solid #eee;border-radius:10px;padding:6px 8px;margin-right:6px}
.scoreRing{width:70px;height:70px;border-radius:50%;display:flex;align-items:center;justify-content:center;
           background:conic-gradient(#1f7a7a var(--deg), #e8e8e8 0);}
.scoreRing span{font-weight:700}
.compact .card{padding:6px}
.compact .swatch{width:18px;height:18px}
.compact .pill{font-size:11px;padding:2px 6px}
.compact .cap{font-size:11px}
</style>
""", unsafe_allow_html=True)

# ---------- (optional) PWA ----------
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

def delete_item(iid:int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM items WHERE id=?", (iid,))
        for col in ["top_id","bottom_id","shoes_id","bag_id"]:
            c.execute(f"UPDATE coords SET {col}=NULL WHERE {col}=?", (iid,))
        conn.commit()

def save_coord(top_id, bottom_id, shoes_id, bag_id, ctx:dict, ai_score:float):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO coords(created_at,top_id,bottom_id,shoes_id,bag_id,ctx,score,rating)
                     VALUES(?,?,?,?,?,?,?,?)""",
                  (datetime.utcnow().isoformat(), top_id, bottom_id, shoes_id, bag_id, json_dumps(ctx), float(ai_score), int(round(ai_score))))
        conn.commit()

def get_usage_stats():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.cursor().execute("SELECT created_at, top_id, bottom_id, shoes_id, bag_id FROM coords").fetchall()
    use_count = defaultdict(int); last_used = {}
    for created_at, t, b, s, g in rows:
        for iid in [t,b,s,g]:
            if iid is None: continue
            use_count[iid] += 1
            if (iid not in last_used) or (created_at > last_used[iid]): last_used[iid] = created_at
    return use_count, last_used

# ---------- セッション保持アップローダ ----------
def persistent_uploader(label: str, key: str, types=("jpg","jpeg","png","webp")):
    up = st.file_uploader(label, type=list(types), key=f"{key}_uploader")
    if up is not None:
        st.session_state[f"{key}_bytes"] = up.read()
    cols = st.columns([4,1])
    with cols[1]:
        if st.button("クリア", key=f"{key}_clear", help="選択中の画像をクリア"):
            st.session_state.pop(f"{key}_bytes", None)
    return st.session_state.get(f"{key}_bytes")

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
    """★ NameError の原因：この関数を入れ忘れていました。"""
    r,g,b=[v/255 for v in hex_to_rgb(hx)]
    h,s,v=colorsys.rgb_to_hsv(r,g,b)
    def wrap(deg): return ((h*360+deg)%360)/360
    hs = [wrap(180)] if mode=="complement" else ([wrap(+delta),wrap(-delta)] if mode=="analogous" else [wrap(+120),wrap(-120)])
    outs=[]
    for hh in hs:
        rr,gg,bb=colorsys.hsv_to_rgb(hh,s,v); outs.append(rgb_to_hex((int(rr*255),int(gg*255),int(bb*255))))
    return outs

# ---------- sRGB→Lab & K-Means（色抽出を高精度化） ----------
def _srgb_to_xyz(arr):
    a = np.where(arr <= 0.04045, arr/12.92, ((arr+0.055)/1.055)**2.4)
    M = np.array([[0.4124564,0.3575761,0.1804375],
                  [0.2126729,0.7151522,0.0721750],
                  [0.0193339,0.1191920,0.9503041]])
    return np.tensordot(a, M.T, axes=1)
def _xyz_to_lab(xyz):
    Xn,Yn,Zn = 0.95047, 1.00000, 1.08883
    x = xyz[...,0]/Xn; y = xyz[...,1]/Yn; z = xyz[...,2]/Zn
    def f(t): return np.where(t>0.008856, np.cbrt(t), 7.787*t+16/116)
    fx,fy,fz = f(x),f(y),f(z)
    L = 116*fy - 16; a = 500*(fx - fy); b = 200*(fy - fz)
    return np.stack([L,a,b], axis=-1)
def rgb_to_lab_u8(pix):
    arr = pix.astype(np.float32)/255.0
    return _xyz_to_lab(_srgb_to_xyz(arr))
def kmeans_lab(pixels_lab, k=4, iters=12, seed=42):
    rng = np.random.default_rng(seed)
    cent = np.empty((k,3), dtype=np.float32)
    idx = rng.integers(0, len(pixels_lab)); cent[0] = pixels_lab[idx]
    d2 = np.full(len(pixels_lab), np.inf, dtype=np.float32)
    for i in range(1,k):
        d2 = np.minimum(d2, np.sum((pixels_lab - cent[i-1])**2, axis=1))
        probs = d2 / np.sum(d2)
        cent[i] = pixels_lab[rng.choice(len(pixels_lab), p=probs)]
    for _ in range(iters):
        dist = np.sum((pixels_lab[:,None,:]-cent[None,:,:])**2, axis=2)
        lab = np.argmin(dist, axis=1)
        for j in range(k):
            mask = (lab==j)
            if np.any(mask):
                cent[j] = pixels_lab[mask].mean(axis=0)
    return cent, lab

def _hsv_from_rgb(arrf):
    r,g,b = arrf[...,0],arrf[...,1],arrf[...,2]
    mx = np.max(arrf,axis=2); mn = np.min(arrf,axis=2); diff = mx-mn
    h = np.zeros_like(mx)
    mask = diff!=0
    r2 = ((mx==r) & mask); g2 = ((mx==g) & mask); b2 = ((mx==b) & mask)
    h[r2] = (60*((g-b)/diff)%360)[r2]
    h[g2] = (60*((b-r)/diff)+120)[g2]
    h[b2] = (60*((r-g)/diff)+240)[b2]
    s = np.where(mx==0, 0, diff/mx); v = mx
    return h, s, v

def main_color_from_region(img:Image.Image, region:str)->str:
    w,h = img.size
    crop = img.crop((0,0,w,h//2)) if region=="upper" else img.crop((0,h//2,w,h))
    small = crop.copy(); small.thumbnail((220,220))
    arr = np.asarray(small).astype(np.uint8)
    arrf = arr.astype(np.float32)/255.0
    # 背景除去 + 中心重み
    hgt,wid = arr.shape[0], arr.shape[1]
    yy,xx = np.mgrid[0:hgt,0:wid]
    cx,cy = wid/2, hgt/2
    sigma = max(hgt,wid)/3.2
    weights = np.exp(-(((xx-cx)**2 + (yy-cy)**2)/(2*sigma*sigma))).astype(np.float32)
    cmax = np.max(arrf, axis=2); cmin = np.min(arrf, axis=2)
    sat  = (cmax - cmin); val = cmax
    mask = ((sat > 0.10) | (val < 0.85)) & (val < 0.98)
    pix = arr[mask]; wv = weights[mask]
    if len(pix) < 50:
        pix = arr.reshape(-1,3); wv = weights.reshape(-1)
    lab = rgb_to_lab_u8(pix)
    k = 4 if len(pix) > 400 else 3
    cent, labidx = kmeans_lab(lab, k=k, iters=10)
    # 白/黒ペナルティ + 中心重みでクラス選択
    def penalty(c):
        L,a,b = c; pen = 0.0
        if L>92: pen += 0.7
        if L<20: pen += 0.4
        return pen
    sizes=[]
    for j in range(k):
        wsum = float(wv[labidx==j].sum())
        sizes.append((wsum*(1.0-penalty(cent[j])), j))
    sizes.sort(reverse=True); best_j = sizes[0][1]
    sel = pix[labidx==best_j]; wsel = wv[labidx==best_j][:,None]
    rgb_mean = (sel*wsel).sum(axis=0)/max(1e-6,wsel.sum())
    return rgb_to_hex(tuple(int(x) for x in rgb_mean))

# ---------- ハイブリッド上/下判定（肌色検知を追加） ----------
def _edge_histogram(img:Image.Image):
    a = np.asarray(img.resize((128,128))).astype(np.float32)/255.0
    gyx = np.abs(np.diff(a, axis=1, prepend=a[:,:1,:])).mean(axis=2)
    gyy = np.abs(np.diff(a, axis=0, prepend=a[:1,:,:])).mean(axis=2)
    edge = (gyx+gyy)/2.0
    return edge.mean(axis=1)

def _clothing_mask(arrf):
    cmax = np.max(arrf, axis=2); cmin = np.min(arrf, axis=2)
    sat  = (cmax - cmin); val = cmax
    return ((sat > 0.12) | (val < 0.75)) & (val < 0.98)

def _skin_score(arrf):
    # HSVで肌色レンジ（ざっくり）：H 0–50 or 330–360, S 0.15–0.68, V 0.2–0.95
    H,S,V = _hsv_from_rgb(arrf)
    mask = ((H<=50) | (H>=330)) & (S>=0.15) & (S<=0.68) & (V>=0.20) & (V<=0.95)
    return float(mask.mean())

def classify_top_or_bottom(img:Image.Image)->str:
    w,h = img.size
    upper = img.crop((0,0,w,h//2)); lower = img.crop((0,h//2,w,h))
    def area_score(region):
        arrf = np.asarray(region.resize((160,160))).astype(np.float32)/255.0
        mask = _clothing_mask(arrf)
        gyx = np.abs(np.diff(arrf, axis=1, prepend=arrf[:,:1,:])).mean(axis=2)
        gyy = np.abs(np.diff(arrf, axis=0, prepend=arrf[:1,:,:])).mean(axis=2)
        edge = (gyx+gyy)/2.0
        return float(mask.mean() + 0.12*edge[mask].mean() if mask.any() else mask.mean())
    s_top = area_score(upper); s_bot = area_score(lower)
    vote_top = 0; vote_bot = 0
    if s_bot >= s_top*1.20: vote_bot += 1
    elif s_top >= s_bot*1.05: vote_top += 1
    eh = _edge_histogram(img); peak_row = np.argmax(eh)/len(eh)
    if 0.18 <= peak_row <= 0.42: vote_top += 1
    if 0.55 <= peak_row <= 0.90: vote_bot += 1
    def light_sat(region):
        arrf = np.asarray(region.resize((160,160))).astype(np.float32)/255.0
        cmax = np.max(arrf, axis=2); cmin = np.min(arrf, axis=2)
        sat  = (cmax - cmin); val = cmax
        return float(val.mean()), float(sat.mean())
    vt,stt = light_sat(upper); vb,stb = light_sat(lower)
    if vt > vb+0.03 and stt >= stb-0.01: vote_top += 1
    # デニム/ダーク検知（下に多いとボトム票）
    def denim_like(region):
        arrf = np.asarray(region.resize((120,120))).astype(np.float32)/255.0
        H,S,V = _hsv_from_rgb(arrf)
        mask = (H>=200)&(H<=255)&(V<0.55)
        return float(mask.mean())
    if denim_like(lower) > 0.06: vote_bot += 1
    # 肌色が上部30%に見えるとトップ票
    up_small = np.asarray(img.resize((160,160))).astype(np.float32)/255.0
    up_band = up_small[:48,:,:]
    if _skin_score(up_band) > 0.04: vote_top += 1
    return "ボトムス" if vote_bot > vote_top else "トップス"

# ---------- URL取込 ----------
UA = {"User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1","Accept-Language":"ja,en;q=0.8"}
def _decode_best(r):
    b = r.content; cands=[]
    if getattr(r, "encoding", None): cands.append(r.encoding)
    if getattr(r, "apparent_encoding", None): cands.append(r.apparent_encoding)
    cands += ["utf-8","cp932","shift_jis","euc-jp"]
    for enc in cands:
        try:
            s = b.decode(enc)
            if "Ã" in s or "Â" in s:
                try:
                    s2 = s.encode("latin-1","ignore").decode("utf-8","ignore")
                    if len(s2.replace("�","")) > len(s.replace("�","")): s = s2
                except: pass
            return s
        except: continue
    return b.decode("utf-8", errors="ignore")
def _meta(content, name):
    m=re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']', content, re.I)
    return ihtml.unescape(m.group(1)) if m else None
def _jsonld_image(content):
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', content, re.I|re.S):
        try:
            data=json.loads(m.group(1))
            if isinstance(data, list):
                for d in data:
                    if isinstance(d, dict) and d.get("image"):
                        img=d["image"]; return img[0] if isinstance(img, list) else img
            elif isinstance(data, dict) and data.get("image"):
                img=data["image"]; return img[0] if isinstance(img, list) else img
        except: pass
    return None
def fetch_from_page(url:str):
    try:
        r=requests.get(url, timeout=10, headers=UA)
        if r.status_code!=200: return None,None,None
        html=_decode_best(r)
        title = _meta(html,"og:title") or _meta(html,"twitter:title")
        if not title:
            t2=re.search(r'<title[^>]*>(.*?)</title>', html, re.I|re.S)
            title=ihtml.unescape(t2.group(1).strip()) if t2 else None
        desc  = _meta(html,"og:description") or _meta(html,"description")
        img_url = _meta(html,"og:image:secure_url") or _meta(html,"og:image") or _meta(html,"twitter:image")
        if not img_url: img_url = _jsonld_image(html)
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

# ---- テキスト/素材/季節 推定（補助） ----
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
    for cat, kws in CAT_MAP.items():
        if any(k.lower() in t for k in kws): return cat
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

# ---------- 評価（既存） ----------
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
    return sqrt(best)
def rgb_dist(h1,h2):
    r1,g1,b1=hex_to_rgb(h1); r2,g2,b2=hex_to_rgb(h2)
    return sqrt((r1-r2)**2+(g1-g2)**2+(b1-b2)**2)
MAXD = sqrt(255**2*3)
def harmony_score(top_hex, others):
    if not others: return 0
    ds=[]
    for hx in others:
        if not hx: continue
        d=rgb_dist(top_hex, hx)
        s = max(0.0, 1.0 - d/MAXD)
        ds.append(s)
    if not ds: return 0
    return 40 * (sum(ds)/len(ds))
def palette_score(hexes, user_season):
    if not user_season: return 15
    ss=[]
    for hx in hexes:
        d = palette_distance(hx, user_season)
        s = max(0.0, 1.0 - d/MAXD)
        ss.append(s)
    return 30 * (sum(ss)/len(ss)) if ss else 0
def climate_bonus(material, heat, humidity, rainy):
    m=(material or "").lower(); s=0
    if heat in ["暑い","猛暑"] and any(k in m for k in ["linen","リネン","cotton","コットン","メッシュ","ドライ"]): s+=1
    if heat in ["寒い"] and any(k in m for k in ["wool","ウール","ダウン","中綿","フリース","キルト"]): s+=1
    if humidity=="湿度高い" and any(k in m for k in ["ドライ","吸汗","速乾","メッシュ","ナイロン","nylon"]): s+=1
    if humidity=="乾燥" and any(k in m for k in ["ウール","ニット","フリース"]): s+=1
    if rainy and any(k in m for k in ["ナイロン","nylon","ゴア","gore","防水","撥水"]): s+=1
    return s
def purpose_match(notes, want):
    if not want or want=="指定なし": return 0
    n=(notes or ""); pts=0
    if want=="通勤":     pts += any(k in n for k in ["ジャケット","シャツ","スラックス","革靴","きれいめ"])
    if want=="デート":   pts += any(k in n for k in ["綺麗め","スカート","ワンピ","ヒール","上品"])
    if want=="カジュアル":pts += any(k in n for k in ["デニム","スニーカー","カジュアル","リラックス"])
    if want=="スポーツ": pts += any(k in n for k in ["スニーカー","ジャージ","ドライ","ラン","トレ"])
    if want=="フォーマル":pts += any(k in n for k in ["ネクタイ","セットアップ","ドレス","革靴"])
    if want=="雨の日":  pts += any(k in n for k in ["撥水","防水","ゴア","レイン","ナイロン"])
    return int(bool(pts))
def body_shape_bonus(notes, body, category):
    if not body: return 0
    n=(notes or "").lower(); b=body
    if b=="straight":
        if category=="ボトムス" and any(k in n for k in ["テーパード","センタープレス","ストレート"]): return 1
        if category in ["トップス","アウター"] and any(k in n for k in ["vネック","襟","ジャケット","構築的"]): return 1
    if b=="wave":
        if category=="ボトムス" and any(k in n for k in ["ハイウエスト","aライン","フレア"]): return 1
        if category=="トップス" and any(k in n for k in ["短丈","クロップド","柔らか","リブ"]): return 1
    if b=="natural":
        if any(k in n for k in ["ワイド","オーバーサイズ","ドロップショルダー","リネン","ツイード"]): return 1
    return 0
def evaluate_outfit(outfit, season, body_shape, want, heat, humidity, rainy):
    items = [outfit[k] for k in ["top","bottom","shoes","bag"] if outfit.get(k)]
    hexes = [it[3] for it in items if it]
    top_hex = outfit["top"][3] if outfit.get("top") else (hexes[0] if hexes else "#2f2f2f")
    sc_harmony = harmony_score(top_hex, [h for h in hexes[1:]])
    sc_palette = palette_score(hexes, season)
    clim = sum([climate_bonus(it[5], heat, humidity, rainy) for it in items]); sc_climate = min(clim, 4) / 4 * 20
    purp = sum([purpose_match(it[7], want) for it in items]); sc_purpose = min(purp, 2) / 2 * 10
    bodyb = sum([body_shape_bonus(it[7], body_shape, it[2]) for it in items]); sc_body = min(bodyb, 3) / 3 * 10
    total = round(max(0.0, min(100.0, sc_harmony + sc_palette + sc_climate + sc_purpose + sc_body)), 1)
    goods=[]; bads=[]
    if sc_harmony >= 28: goods.append("トップと他アイテムの**色相バランス**が良い")
    else: bads.append("配色の一体感が弱め。**補色/類似色**を意識するとまとまりやすい")
    if sc_palette >= 20: goods.append("**パーソナルカラー**に合うトーン")
    else: bads.append("PCから少し外れ気味。**優先パレット**寄りの色に寄せると◎")
    if sc_climate >= 12: goods.append("**気候**に合った素材選び")
    else: bads.append("気候との相性が弱い素材あり")
    if sc_purpose >= 6: goods.append("用途（シーン）に対する**TPO**が合っている")
    else: bads.append("TPO要素が弱い")
    if sc_body >= 6: goods.append("体型に合う**シルエット**/ディテール")
    else: bads.append("体型補正が弱め")
    comp = adjust_harmony(top_hex, "complement")[0]
    ana  = adjust_harmony(top_hex, "analogous")
    tri  = adjust_harmony(top_hex, "triadic")
    suggest = sorted([comp, ana[0], tri[0]], key=lambda h: palette_distance(h, season))
    def jp_name(hx): return JP_COLOR.get(nearest_css_name(hx), nearest_css_name(hx))
    suggestions = [{"hex":h, "name":jp_name(h)} for h in suggest]
    breakdown = {"Harmony(40)": round(sc_harmony,1),"PC Fit(30)": round(sc_palette,1),
                 "Climate(20)": round(sc_climate,1),"Purpose(10)": round(sc_purpose,1),"Body(10)": round(sc_body,1)}
    return total, goods, bads, suggestions, breakdown

# ---------- オンライン提案 ----------
SHOP_LINKS = {
    "ZOZOTOWN": "https://www.google.com/search?q=",
    "UNIQLO": "https://www.uniqlo.com/jp/ja/search?q=",
    "GU": "https://www.gu-global.com/jp/ja/search/?q=",
    "MUJI": "https://www.muji.com/jp/ja/search/?query=",
    "Rakuten": "https://search.rakuten.co.jp/search/mall/",
    "Amazon": "https://www.amazon.co.jp/s?k=",
    "WEAR": "https://wear.jp/item/?keyword=",
}
CAT_JP = {"トップス":"トップス","ボトムス":"パンツ","シューズ":"スニーカー","バッグ":"バッグ"}
def shop_suggestions(category:str, base_hex:str, season:str|None):
    color_jp = JP_COLOR.get(nearest_css_name(base_hex), "ベーシック")
    season_jp = {"spring":"春","summer":"夏","autumn":"秋","winter":"冬"}.get(season or "", "")
    kw = f"{color_jp} {CAT_JP.get(category, category)} {season_jp}".strip()
    out=[]
    for site, base in SHOP_LINKS.items():
        if site=="ZOZOTOWN":
            q = quote_plus(f"site:zozo.jp {kw}"); url = base + q
        elif site=="Rakuten":
            url = base + quote_plus(kw) + "/"
        else:
            url = base + quote_plus(kw)
        out.append({"site":site, "kw":kw, "url":url})
    return out

# ---------- UI ----------
init_db()
profile = load_profile()

compact = st.toggle("コンパクト表示", value=True, help="情報密度を上げます。")
st.markdown("<div class='compact'>" if compact else "<div>", unsafe_allow_html=True)

st.title("Outf!ts")
tab1, tabCal, tabCloset, tabAI, tabProfile = st.tabs(["📒 記録","📅 カレンダー","🧳 クローゼット","🤖 AIコーデ","👤 プロフィール"])

SIL_TOP = ["ジャスト/レギュラー","オーバーサイズ","クロップド/短丈","タイト/フィット"]
SIL_BOTTOM = ["ストレート","ワイド/フレア","スキニー/テーパード","Aライン/スカート","ショーツ"]

# ===== 記録 =====
with tab1:
    d = st.date_input("日付", value=pd.Timestamp.today(), key="rec_date")
    img_bytes = persistent_uploader("写真（カメラ可）", key="rec_photo")
    colA, colB = st.columns(2)
    top_sil = colA.selectbox("トップ", SIL_TOP, index=0, key="rec_top_sil")
    bottom_sil = colB.selectbox("ボトム", SIL_BOTTOM, index=0, key="rec_bottom_sil")
    notes = st.text_area("メモ", placeholder="", key="rec_notes")

    auto_colors=[]; auto_top="#2f2f2f"; auto_bottom="#c9c9c9"
    if img_bytes:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        st.image(img, use_container_width=True)
        auto_top = main_color_from_region(img, "upper")
        auto_bottom = main_color_from_region(img, "lower")
        auto_colors = [auto_top, auto_bottom]
        st.caption("自動カラー認識（上/下それぞれ）")
        st.markdown(" ".join([f"<span class='swatch' style='background:{h}'></span>" for h in auto_colors]), unsafe_allow_html=True)

    use_auto = st.toggle("自動色認識を使う", value=True, key="use_auto_colors")
    if use_auto:
        top_color, bottom_color = auto_top, auto_bottom
        st.markdown(f"<div class='badge'>Top: {top_color}</div><div class='badge'>Bottom: {bottom_color}</div>", unsafe_allow_html=True)
    else:
        col1, col2 = st.columns(2)
        top_color = col1.color_picker("トップ色", auto_top, key="rec_top_color")
        bottom_color = col2.color_picker("ボトム色", auto_bottom, key="rec_bottom_color")

    if st.button("保存", type="primary", key="rec_save", disabled=(img_bytes is None)):
        insert_outfit(str(pd.to_datetime(d).date()), profile.get("season"),
                      top_sil, bottom_sil, top_color, bottom_color, auto_colors, img_bytes, notes)
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
        img_bytes = persistent_uploader("画像", key="cl_img")
        color_auto="#2f2f2f"; cat_guess="トップス"; season_guess=None; name_suggest="アイテム"; material_guess="コットン"
        seed = len(img_bytes) if img_bytes else 0

        if img_bytes:
            img_i = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            st.image(img_i, use_container_width=True)
            cat_guess = classify_top_or_bottom(img_i)
            region = "upper" if cat_guess=="トップス" else "lower"
            color_auto = main_color_from_region(img_i, region)
            season_guess = None
            material_guess = "コットン" if hex_luma(color_auto)>150 else "ウール/ニット"
            cname = JP_COLOR.get(nearest_css_name(color_auto), "カラー")
            name_suggest = f"{cname} {('Tシャツ' if cat_guess=='トップス' else 'パンツ' if cat_guess=='ボトムス' else cat_guess)}"
            st.caption("自動：カテゴリ/主色（領域別）/素材（簡易）")
            st.markdown(f"<span class='swatch' style='background:{color_auto}'></span> {color_auto}", unsafe_allow_html=True)

        colN = st.columns(2)
        name = colN[0].text_input("名前", value=name_suggest, key=f"cl_name_{seed}")
        category = colN[1].selectbox("カテゴリ", ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"],
                                     index=(["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"].index(cat_guess)
                                            if cat_guess in ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"] else 0),
                                     key=f"cl_category_{seed}")
        color_hex = st.color_picker("色", color_auto, key=f"cl_color_{seed}")
        colS = st.columns(2)
        season_pref = colS[0].selectbox("得意シーズン", ["指定なし","spring","summer","autumn","winter"],
                                        index=(["指定なし","spring","summer","autumn","winter"].index(season_guess) if season_guess in ["spring","summer","autumn","winter"] else 0),
                                        key=f"cl_season_{seed}")
        material = colS[1].text_input("素材", value=material_guess, key=f"cl_material_{seed}")
        notes_i = st.text_area("メモ（用途/特徴）", key=f"cl_notes_{seed}")

        if st.button("追加", key=f"cl_add_btn_{seed}", disabled=(img_bytes is None)):
            add_item(name or "Unnamed", category, color_hex,
                     None if season_pref=="指定なし" else season_pref,
                     material, img_bytes, notes_i)
            st.success("追加しました")

    else:
        url = st.text_input("商品URL", placeholder="https://", key="cl_url")
        if st.button("解析", key="cl_parse"):
            title, imgb, desc = fetch_from_page(url)
            if not title and not imgb: st.error("取得できませんでした")
            else:
                st.session_state["url_title"]=title
                st.session_state["url_img"]=imgb
                st.session_state["url_desc"]=desc
                st.success("読み込みました")

        title = st.session_state.get("url_title")
        img_bytes = st.session_state.get("url_img")
        desc = st.session_state.get("url_desc","")
        seed = (len(img_bytes) if img_bytes else 0) + (len(title or "") if title else 0)

        cat_from_text = guess_category_from_text((title or "") + " " + (desc or ""))
        mat_from_text = guess_material_from_text((title or "") + " " + (desc or "")) or ""
        ssn_from_text = guess_season_from_text((title or "") + " " + (desc or ""))

        color_guess="#2f2f2f"
        if img_bytes:
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            st.image(img, use_container_width=True)
            color_guess = main_color_from_region(img, "upper")
            st.markdown(f"<span class='swatch' style='background:{color_guess}'></span> {color_guess}", unsafe_allow_html=True)

        colU = st.columns(2)
        name_url = colU[0].text_input("名前", value=(title or ""), key=f"cl_name_url_{seed}")
        category_url = colU[1].selectbox("カテゴリ", ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"],
                                         index=(["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"].index(cat_from_text) if cat_from_text in ["トップス","ボトムス","アウター","ワンピース","シューズ","バッグ","アクセ"] else 0),
                                         key=f"cl_category_url_{seed}")
        color_url = colU[0].color_picker("色", color_guess, key=f"cl_color_url_{seed}")

        colU2 = st.columns(2)
        material_url = colU2[0].text_input("素材", value=mat_from_text, key=f"cl_material_url_{seed}")
        season_idx = (["指定なし","spring","summer","autumn","winter"].index(ssn_from_text) if ssn_from_text in ["spring","summer","autumn","winter"] else 0)
        season_url = colU2[1].selectbox("得意シーズン", ["指定なし","spring","summer","autumn","winter"], index=season_idx, key=f"cl_season_url_{seed}")
        notes_url = st.text_area("メモ", value=(url or desc or ""), key=f"cl_notes_url_{seed}")

        if st.button("追加", key=f"cl_add_btn_url_{seed}", disabled=(not name_url and img_bytes is None)):
            add_item(name_url or "Unnamed", category_url, color_url,
                     None if season_url=="指定なし" else season_url,
                     material_url, img_bytes, notes_url)
            st.success("追加しました")

    # ---------- グループごと一覧 / 編集 / 削除 ----------
    st.markdown("---")
    st.subheader("クローゼット一覧（カテゴリ別）")

    frow = st.columns([2,3,1])
    q = frow[1].text_input("検索（名前/メモ）", key="cl_query", placeholder="例：ネイビー, 撥水, オフィス など")
    per_row = int(frow[2].selectbox("列数", [1,2,3], index=2, help="画面密度を変更"))

    use_count, last_used = get_usage_stats()
    def _last_dt(iid): return last_used.get(iid, "")
    all_items = list_items("すべて")
    if q:
        ql = q.lower()
        all_items = [r for r in all_items if (r[1] and ql in r[1].lower()) or (r[7] and ql in r[7].lower())]

    groups = {
        "トップス": ["トップス","ワンピース"],
        "ボトムス": ["ボトムス"],
        "アウター": ["アウター"],
        "小物": ["シューズ","バッグ"],
        "アクセサリー": ["アクセ"],
    }

    def render_card(row, col):
        iid, nm, cat, hx, sp, mat, imgb, nts = row
        worn = use_count.get(iid, 0)
        last = last_used.get(iid)
        last_txt = pd.to_datetime(last).strftime("%Y-%m-%d") if last else "—"
        with col:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            if imgb:
                try: st.image(Image.open(io.BytesIO(imgb)), use_container_width=True)
                except: st.markdown("<div style='width:100%;aspect-ratio:1/1;border:1px dashed #ccc;border-radius:8px;display:flex;align-items:center;justify-content:center;'>画像表示不可</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='width:100%;aspect-ratio:1/1;border:1px dashed #ccc;border-radius:8px;display:flex;align-items:center;justify-content:center;'>画像なし</div>", unsafe_allow_html=True)
            st.markdown(f"**{nm or '（名称未設定）'}**")
            st.markdown(f"<span class='pill'>{cat}</span> <span class='pill'>{sp or '季節指定なし'}</span> <span class='pill'>{mat or '素材不明'}</span>", unsafe_allow_html=True)
            st.markdown(f"<div class='cap'><span class='mini' style='background:{hx or '#2f2f2f'}'></span>色: {hx or '-'}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='cap'>使用回数: <b>{worn}</b>／最終着用: {last_txt}</div>", unsafe_allow_html=True)
            if st.button("編集を開く", key=f"open_edit_{iid}"):
                st.session_state[f"open_exp_{iid}"] = True
            st.markdown("</div>", unsafe_allow_html=True)

    for gname, cats in groups.items():
        items_g = [r for r in all_items if r[2] in cats]
        with st.expander(f"{gname}（{len(items_g)}）", expanded=True):
            if not items_g:
                st.caption("該当なし")
            else:
                for i in range(0, len(items_g), per_row):
                    cols = st.columns(per_row)
                    for col, row in zip(cols, items_g[i:i+per_row]):
                        render_card(row, col)

    st.markdown("### 編集 / 削除")
    for row in all_items:
        iid, nm, cat, hx, sp, mat, imgb, nts = row
        expanded = st.session_state.get(f"open_exp_{iid}", False)
        with st.expander(f"{nm}（{cat}）", expanded=expanded):
            cols = st.columns([1,2])
            with cols[0]:
                if imgb:
                    try: st.image(Image.open(io.BytesIO(imgb)), use_container_width=True)
                    except: st.write("画像なし")
                else:
                    st.write("画像なし")
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
                b1, b2, b3 = st.columns([1,1,1])
                if b1.button("保存", key=f"edit_save_{iid}"):
                    new_img_bytes = eup.read() if eup else None
                    update_item(iid, ename, ecat, ehx, None if esp=="指定なし" else esp, emat, new_img_bytes, enotes)
                    st.session_state[f"open_exp_{iid}"] = True
                    st.success("保存しました")
                confirm = b2.checkbox("本当に削除", key=f"confirm_del_{iid}")
                if b3.button("削除", key=f"delete_{iid}", disabled=not confirm):
                    delete_item(iid)
                    st.success("削除しました")
                    st.experimental_rerun()

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

        def pick_best(items, top_hex, category):
            cand=[it for it in items if it[2]==category]
            if not cand: return None, 1e9
            scored=[]
            for row in cand:
                iid,nm,cat,hx,sp,mat,imgb,nts=row
                d = rgb_dist(top_hex, hx)
                s_h = max(0.0, 1.0 - d/MAXD)
                s_p = max(0.0, 1.0 - (palette_distance(hx, season) if season else MAXD/2)/MAXD)
                s_c = climate_bonus(mat, heat, humidity, rainy)
                s_u = purpose_match(nts, want)
                s_b = body_shape_bonus(nts, body_shape, cat)
                score = -(0.6*s_h + 0.3*s_p + 0.07*s_c + 0.02*s_u + 0.01*s_b)
                scored.append((score,row))
            scored.sort(key=lambda x:x[0])
            return scored[0][1], scored[0][0]

        if st.button("生成", key="ai_gen"):
            tops=[it for it in all_items if it[2]=="トップス"]
            if not tops:
                st.warning("トップスが未登録です")
            else:
                best_top=None; best_s=1e9
                for row in tops:
                    _,_,cat,hx,sp,mat,imgb,nts=row
                    s = - (0.5*max(0.0, 1.0 - (palette_distance(hx, season) if season else MAXD/2)/MAXD)
                           + 0.4*climate_bonus(mat, heat, humidity, rainy)
                           + 0.1*body_shape_bonus(nts, body_shape, cat))
                    if s<best_s: best_s=s; best_top=row
                top=best_top
                bottom,_ = pick_best(all_items, top[3], "ボトムス")
                shoes ,_ = pick_best(all_items, top[3], "シューズ")
                bag   ,_ = pick_best(all_items, top[3], "バッグ")
                outfit={"top":top,"bottom":bottom,"shoes":shoes,"bag":bag}

                score, goods, bads, suggestions, breakdown = evaluate_outfit(
                    outfit, season, body_shape, want, heat, humidity, rainy
                )

                st.markdown("### おすすめコーデ")
                cols = st.columns(4)
                labels=[("トップ","top"),("ボトム","bottom"),("靴","shoes"),("バッグ","bag")]
                for j,(label,key) in enumerate(labels):
                    with cols[j]:
                        row = outfit.get(key)
                        st.markdown("<div class='card'>", unsafe_allow_html=True)
                        if row and row[6]:
                            try: st.image(Image.open(io.BytesIO(row[6])), use_container_width=True)
                            except: st.write("画像なし")
                        else:
                            st.markdown("<div style='width:100%;aspect-ratio:1/1;border:1px dashed #ccc;border-radius:8px;display:flex;align-items:center;justify-content:center;'>画像なし</div>", unsafe_allow_html=True)
                        st.caption(f"{label}：{row[1] if row else '—'} / {row[3] if row else '-'}")
                        st.markdown("</div>", unsafe_allow_html=True)

                st.markdown("### AIスコア")
                deg = int(360 * (score/100))
                st.markdown(f"<div class='scoreRing' style='--deg:{deg}deg'><span>{int(round(score))}</span></div>", unsafe_allow_html=True)
                st.markdown(
                    f"<div class='kpi'>Harmony: {breakdown['Harmony(40)']}</div>"
                    f"<div class='kpi'>PC Fit: {breakdown['PC Fit(30)']}</div>"
                    f"<div class='kpi'>Climate: {breakdown['Climate(20)']}</div>"
                    f"<div class='kpi'>Purpose: {breakdown['Purpose(10)']}</div>"
                    f"<div class='kpi'>Body: {breakdown['Body(10)']}</div>",
                    unsafe_allow_html=True
                )

                c1,c2 = st.columns(2)
                with c1:
                    st.markdown("#### Good")
                    for g in goods: st.write("• " + g)
                with c2:
                    st.markdown("#### Bad / 改善ポイント")
                    for b in bads: st.write("• " + b)

                st.markdown("#### 買うべき色（トップ基準の提案）")
                st.markdown("".join([f"<span class='swatch' style='background:{s['hex']}'></span> {s['name']} ({s['hex']})  " for s in suggestions]), unsafe_allow_html=True)

                missing=[]
                if outfit["bottom"] is None: missing.append("ボトムス")
                if outfit["shoes"]  is None: missing.append("シューズ")
                if outfit["bag"]    is None: missing.append("バッグ")
                if missing:
                    st.markdown("### 不足アイテムのオンライン提案")
                    base_hex = outfit["top"][3] if outfit["top"] else "#2f2f2f"
                    for cat in missing:
                        st.markdown(f"**{cat}**（検索キーワード例：{JP_COLOR.get(nearest_css_name(base_hex),'カラー')} + {CAT_JP.get(cat,cat)}）")
                        links = shop_suggestions(cat, base_hex, season)
                        cols = st.columns(3)
                        for col, rec in zip(cols, links[:3]):
                            with col:
                                st.markdown("<div class='card'>", unsafe_allow_html=True)
                                st.caption(rec["site"])
                                st.link_button("検索を開く", rec["url"])
                                st.markdown("</div>", unsafe_allow_html=True)

                if st.button("このコーデを保存", key="ai_save"):
                    save_coord(outfit['top'][0],
                               outfit['bottom'][0] if outfit['bottom'] else None,
                               outfit['shoes'][0] if outfit['shoes'] else None,
                               outfit['bag'][0] if outfit['bag'] else None,
                               {"want":want,"heat":heat,"humidity":humidity,"rainy":rainy,"season":season,"body_shape":body_shape,
                                "ai_breakdown":breakdown,"goods":goods,"bads":bads,"suggest_colors":[s['hex'] for s in suggestions],
                                "missing":missing},
                               score)
                    st.success("保存しました（AIスコア付き）")

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

st.markdown("</div>", unsafe_allow_html=True)
