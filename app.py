# -*- coding: utf-8 -*-
"""Tool Check Backlink SEO — Check backlink song/chet + trace redirect 301.

Chay: run.bat (hoac: streamlit run app.py)
Nguyen tac: UI-first — end-user chi thao tac bang nut bam tren giao dien.
"""

import concurrent.futures
import io
import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
import streamlit as st
import urllib3
from bs4 import BeautifulSoup

from providers import ProviderError, build_provider

# tool trace redirect: nhieu site nguon co chung chi SSL loi (het han/self-signed) nhung van
# redirect. Cho phep retry khong verify de van trace duoc; tat canh bao rac cua urllib3.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def safe_get(url: str, insecure_flag: list = None, **kw):
    """GET; neu loi CHUNG CHI SSL thi thu lai voi verify=False (van trace duoc site loi cert).
    insecure_flag: neu truyen list, append True khi da phai bo qua SSL."""
    try:
        return requests.get(url, **kw)
    except requests.exceptions.SSLError:
        if insecure_flag is not None:
            insecure_flag.append(True)
        kw["verify"] = False
        return requests.get(url, **kw)

CONFIG_FILE = Path(__file__).with_name("config.json")
HISTORY_DB = Path(__file__).with_name("history.db")
HISTORY_TTL = 24 * 3600  # lich su tracking tu xoa sau 24 gio

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
}
# soi cloaking: cung 1 URL hoi bang NHIEU "danh tinh" (User-Agent) khac nhau roi so ket qua.
# Da nguon, cau hinh tuy chon (memory multi-source-api): user tu chon con nao de soi + them UA rieng.
UA_PRESETS = {
    "Trình duyệt Chrome": HEADERS["User-Agent"],
    "Googlebot (Google)": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Bingbot (Bing)": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "AhrefsBot": "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)",
    "SemrushBot": "Mozilla/5.0 (compatible; SemrushBot/7~bl; +http://www.semrush.com/bot.html)",
    "DuckDuckBot": "Mozilla/5.0 (compatible; DuckDuckBot/1.1; +http://duckduckgo.com/duckduckbot.html)",
    "Facebook bot": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "iPhone Safari": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
}
UA_DEFAULT = ["Trình duyệt Chrome", "Googlebot (Google)", "AhrefsBot"]

# nguon tra LICH SU redirect (URL nay tung 301 ve dau) — da nguon, mo rong duoc.
# archive.today la phuong an khi ISP chan archive.org (nhieu ISP VN chan dich danh archive.org).
HISTORY_SOURCES = {
    "Wayback Machine (archive.org)": "wayback",
    "archive.today (khi archive.org bị chặn)": "archive_today",
}
HISTORY_DEFAULT = ["Wayback Machine (archive.org)"]

TIMEOUT = 20
MAX_HOPS = 10
REDIRECT_CODES = (301, 302, 303, 307, 308)


# ---------------------------------------------------------------- helpers
def normalize_domain(raw: str) -> str:
    """'https://www.example.com/path' -> 'example.com'"""
    raw = raw.strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    netloc = urlparse(raw).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def normalize_url(raw: str) -> str:
    raw = raw.strip()
    if raw and "://" not in raw:
        raw = "https://" + raw
    return raw


def parse_url_list(text: str) -> list:
    seen, urls = set(), []
    for line in text.splitlines():
        u = normalize_url(line)
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


def domain_matches(href_netloc: str, target: str) -> bool:
    if href_netloc.startswith("www."):
        href_netloc = href_netloc[4:]
    return href_netloc == target or href_netloc.endswith("." + target)


# ---------------------------------------------------------------- backlink check
def check_backlink(url: str, target: str) -> dict:
    row = {
        "Backlink URL": url,
        "HTTP Status": "",
        "Còn link?": "",
        "Số link tìm thấy": 0,
        "Anchor text": "",
        "Loại link": "",
        "Meta robots": "",
        "Lỗi": "",
    }
    try:
        r = safe_get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        row["HTTP Status"] = r.status_code
        if r.status_code >= 400:
            row["Còn link?"] = "❌ Trang lỗi"
            return row

        soup = BeautifulSoup(r.text, "lxml")

        meta = soup.find(
            "meta", attrs={"name": lambda v: v and v.lower() == "robots"}
        )
        content = (meta.get("content", "") if meta else "").lower()
        row["Meta robots"] = "⚠️ noindex" if "noindex" in content else "✅ index"

        found = []
        for a in soup.find_all("a", href=True):
            absolute = urljoin(r.url, a["href"])
            netloc = urlparse(absolute).netloc.lower()
            if not netloc or not domain_matches(netloc, target):
                continue
            rel = " ".join(a.get("rel") or []).lower()
            anchor = a.get_text(strip=True) or "[ảnh/không có anchor]"
            found.append((anchor, "nofollow" if "nofollow" in rel else "dofollow"))

        row["Số link tìm thấy"] = len(found)
        if found:
            row["Còn link?"] = "✅ Còn link"
            row["Anchor text"] = "; ".join(dict.fromkeys(a for a, _ in found))
            rels = {rel for _, rel in found}
            row["Loại link"] = "dofollow" if "dofollow" in rels else "nofollow"
        else:
            row["Còn link?"] = "❌ Mất link"
    except requests.exceptions.Timeout:
        row["Còn link?"] = "❌ Lỗi"
        row["Lỗi"] = "Timeout"
    except requests.exceptions.SSLError:
        row["Còn link?"] = "❌ Lỗi"
        row["Lỗi"] = "Lỗi SSL"
    except requests.exceptions.RequestException as e:
        row["Còn link?"] = "❌ Lỗi"
        row["Lỗi"] = f"Không kết nối được: {type(e).__name__}"
    except Exception as e:  # noqa: BLE001
        row["Còn link?"] = "❌ Lỗi"
        row["Lỗi"] = f"{type(e).__name__}: {e}"
    return row


# ---------------------------------------------------------------- redirect check
def detect_hidden_redirect(html: str, base_url: str):
    """Bat redirect an trong HTML: meta refresh + JS doi location. Tra (kieu, dich) hoac None."""
    soup = BeautifulSoup(html, "lxml")
    meta = soup.find(
        "meta", attrs={"http-equiv": lambda v: v and v.lower() == "refresh"}
    )
    if meta:
        m = re.search(r"url\s*=\s*['\"]?([^'\";]+)", meta.get("content", ""), re.I)
        if m:
            return ("meta refresh", urljoin(base_url, m.group(1).strip()))
    m = re.search(
        r"(?:window\.|document\.|top\.|self\.)?location"
        r"(?:\.href|\.assign|\.replace)?\s*(?:=|\()\s*['\"]([^'\"]+)['\"]",
        html[:200_000],
    )
    if m:
        return ("JS redirect", urljoin(base_url, m.group(1).strip()))
    return None


def ua_probe(url: str, ua_pairs: list) -> str:
    """Goi cung URL bang cac User-Agent do user chon (ua_pairs = [(nhan, UA)...]),
    so (status, Location) — lech nhau = nghi cloaking. Da nguon, cau hinh tuy chon."""
    if len(ua_pairs) < 2:
        return "cần ≥2 User-Agent để so"
    probes = []
    for label, ua in ua_pairs:
        try:
            r = safe_get(
                url,
                headers={**HEADERS, "User-Agent": ua},
                timeout=TIMEOUT,
                allow_redirects=False,
            )
            loc = r.headers.get("Location") or ""
            probes.append((label, str(r.status_code), urljoin(url, loc) if loc else ""))
        except requests.exceptions.RequestException as e:
            probes.append((label, f"lỗi {type(e).__name__}", ""))
    detail = " | ".join(
        f"{lab}: {s}" + (f" → {loc}" if loc else "") for lab, s, loc in probes
    )
    uniform = len({(s, loc) for _, s, loc in probes}) == 1
    return ("✅ đồng nhất — " if uniform else "⚠️ NGHI CLOAKING — ") + detail


def archive_today_history(url: str) -> str:
    """archive.today chan truy cap TU DONG (Cloudflare 429) nhung MO BANG TRINH DUYET thi
    xem duoc. Nen KHONG scrape (tranh bao loi 429 vo ich) — dua thang link de user tu mo."""
    return f"mở link để xem bản lưu → https://archive.today/newest/{url}"


def redirect_history(url: str, sources: list) -> str:
    """Tra lich su redirect cua URL tu cac nguon user chon (da nguon).
    Them nguon moi = 1 nhanh o day + 1 dong trong HISTORY_SOURCES."""
    keys = [HISTORY_SOURCES.get(s) for s in sources]
    parts = []
    if "wayback" in keys:
        parts.append("Wayback: " + wayback_301_history(url))
    if "archive_today" in keys:
        parts.append("archive.today: " + archive_today_history(url))
    return "  ||  ".join(parts) if parts else "chưa chọn nguồn lịch sử"


def wayback_301_history(url: str, max_lookups: int = 4) -> str:
    """Best-effort doc header 301 cu tu Wayback (timeout NGAN de khong treo). Wayback chan
    truy cap tu dong (IP cloud/ISP) nhung mo trinh duyet thi duoc — nen DU doc duoc hay khong,
    LUON kem link mo tay de user tu xem."""
    manual = f"https://web.archive.org/web/2*/{url}"
    try:
        r = requests.get(
            "https://web.archive.org/cdx/search/cdx",
            params={
                "url": url,
                "output": "json",
                "fl": "timestamp,statuscode",
                "filter": "statuscode:3..",
                "collapse": "timestamp:6",  # toi da 1 ban chup / thang
            },
            timeout=(4, 8),  # connect 4s: chan/treo thi bo nhanh, khong doi 20s
        )
        data = r.json()
    except Exception:  # noqa: BLE001 — chan/treo/loi deu chuyen sang link mo tay
        return f"tự mở xem lịch sử → {manual}"
    rows = data[1:] if isinstance(data, list) and len(data) > 1 else []
    if not rows:
        return f"Wayback chưa có bản chụp 3xx — tự kiểm tra: {manual}"
    if len(rows) > max_lookups:  # rai deu tu ban cu nhat den moi nhat
        idx = [round(i * (len(rows) - 1) / (max_lookups - 1)) for i in range(max_lookups)]
        rows = [rows[i] for i in dict.fromkeys(idx)]
    hist, seen = [], set()
    for ts, status in rows:
        try:
            s = requests.get(
                f"https://web.archive.org/web/{ts}id_/{url}",
                timeout=(4, 8),
                allow_redirects=False,
            )
            loc = s.headers.get("Location") or ""
        except requests.exceptions.RequestException:
            continue
        loc = re.sub(r"^https?://web\.archive\.org/web/\d+(?:id_)?/", "", loc)
        if loc and loc not in seen:
            seen.add(loc)
            hist.append(f"{ts[:4]}-{ts[4:6]}: {status} → {loc}")
    if hist:
        return " ;  ".join(hist) + f"  (đầy đủ: {manual})"
    return f"có {len(rows)} bản chụp 3xx — tự mở đọc đích: {manual}"


def check_redirect(url: str, ua_pairs: list = None, history_sources: list = None) -> dict:
    """ua_pairs: cac (nhan, User-Agent) de soi cloaking (>=2 moi soi).
    history_sources: cac nhan nguon lich sur redirect (rong = bo qua)."""
    ua_pairs = ua_pairs or []
    history_sources = history_sources or []
    row = {
        "URL gốc": url,
        "Kết quả": "",
        "Số bước redirect": 0,
        "Chuỗi status": "",
        "URL cuối cùng": "",
        "Status cuối": "",
        "Chi tiết chuỗi": "",
        "Redirect ẩn (meta/JS)": "",
        "Lỗi": "",
    }
    if len(ua_pairs) >= 2:
        row["Soi cloaking (đa User-Agent)"] = ""
    if history_sources:
        row["Lịch sử redirect"] = ""
    chain = []
    current = url
    final_resp = None
    _insecure = []  # danh dau neu phai bo qua loi SSL de trace duoc
    try:
        for _ in range(MAX_HOPS):
            r = safe_get(
                current, insecure_flag=_insecure,
                headers=HEADERS, timeout=TIMEOUT, allow_redirects=False,
            )
            chain.append((current, r.status_code))
            if r.status_code in REDIRECT_CODES:
                loc = r.headers.get("Location")
                if not loc:
                    row["Lỗi"] = "Redirect nhưng thiếu header Location"
                    break
                current = urljoin(current, loc)
            else:
                final_resp = r
                break
        else:
            row["Lỗi"] = f"Quá {MAX_HOPS} bước redirect (nghi vòng lặp)"

        statuses = [s for _, s in chain]
        hops = len(chain) - 1
        row["Số bước redirect"] = hops
        row["Chuỗi status"] = " → ".join(str(s) for s in statuses)
        row["URL cuối cùng"] = chain[-1][0]
        row["Status cuối"] = statuses[-1]
        row["Chi tiết chuỗi"] = "  →  ".join(
            f"[{s}] {u}" for u, s in chain
        )

        if hops == 0:
            row["Kết quả"] = "⏺ Không redirect"
        elif all(s == 301 for s in statuses[:-1]):
            row["Kết quả"] = "✅ 301 (direct)" if hops == 1 else f"✅ 301 (chuỗi {hops} bước)"
        else:
            kinds = "/".join(sorted({str(s) for s in statuses[:-1]}))
            row["Kết quả"] = f"⚠️ Redirect {kinds}"
        if isinstance(row["Status cuối"], int) and row["Status cuối"] >= 400:
            row["Kết quả"] += " → ❌ đích lỗi"

        # trang cuoi tra 200 nhung van co the redirect ngam bang meta refresh / JS
        if final_resp is not None and final_resp.status_code < 400:
            hidden = detect_hidden_redirect(final_resp.text or "", chain[-1][0])
            if hidden:
                row["Redirect ẩn (meta/JS)"] = f"⚠️ {hidden[0]} → {hidden[1]}"
                row["Kết quả"] += " + ⚠️ có redirect ẩn"
    except requests.exceptions.Timeout:
        row["Kết quả"] = "❌ Lỗi"
        row["Lỗi"] = "Timeout"
    except requests.exceptions.SSLError:
        row["Kết quả"] = "❌ Lỗi"
        row["Lỗi"] = "Lỗi SSL"
    except requests.exceptions.RequestException as e:
        row["Kết quả"] = "❌ Lỗi"
        row["Lỗi"] = f"Không kết nối được: {type(e).__name__}"
    except Exception as e:  # noqa: BLE001
        row["Kết quả"] = "❌ Lỗi"
        row["Lỗi"] = f"{type(e).__name__}: {e}"

    if len(ua_pairs) >= 2:
        row["Soi cloaking (đa User-Agent)"] = ua_probe(url, ua_pairs)
    if history_sources:
        row["Lịch sử redirect"] = redirect_history(url, history_sources)
    return row


# ---------------------------------------------------------------- runner
def run_parallel(fn, urls, workers, progress_label):
    results = []
    bar = st.progress(0, text=progress_label)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fn, u): i for i, u in enumerate(urls)}
        done = 0
        indexed = {}
        for fut in concurrent.futures.as_completed(futures):
            indexed[futures[fut]] = fut.result()
            done += 1
            bar.progress(done / len(urls), text=f"{progress_label} ({done}/{len(urls)})")
    bar.empty()
    for i in range(len(urls)):
        results.append(indexed[i])
    return results


def to_excel_bytes(df: pd.DataFrame, sheet: str) -> bytes:
    return to_excel_multi({sheet: df})


def to_excel_multi(sheets: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet, df in sheets.items():
            df.to_excel(writer, index=False, sheet_name=sheet[:31])
            ws = writer.sheets[sheet[:31]]
            for col_cells in ws.columns:
                width = max(len(str(c.value or "")) for c in col_cells)
                ws.column_dimensions[col_cells[0].column_letter].width = min(width + 2, 80)
    return buf.getvalue()


def get_secret(name: str):
    """Doc bien cau hinh khi deploy web: bien moi truong -> st.secrets -> None."""
    v = os.environ.get(name)
    if v:
        return v
    try:
        return st.secrets[name]  # Streamlit Cloud dung secrets thay vi env
    except Exception:
        return None


def is_multi_user() -> bool:
    """Deploy web nhieu nguoi: dat MULTI_USER=1 trong Secrets. Khi bat:
    key user nhap CHI luu trong phien (st.session_state), KHONG ghi ra o dia server."""
    return str(get_secret("MULTI_USER") or "").strip().lower() in ("1", "true", "yes", "on")


def _owner_config() -> dict:
    """Key CHUNG cua chu (qua Secrets/env) — dung lam fallback (mo hinh B/C)."""
    cfg = {}
    se = get_secret("SE_KEYS")
    if se:
        cfg["se_keys"] = [k.strip() for k in str(se).split(",") if k.strip()]
    for src, dst in (("DFS_LOGIN", "dfs_login"), ("DFS_PASSWORD", "dfs_password"), ("PROVIDER", "provider")):
        v = get_secret(src)
        if v:
            cfg[dst] = str(v)
    return cfg


def config_for_display() -> dict:
    """Gia tri hien len o nhap key (KHONG lo key chung cua chu cho nguoi khac):
    - multi-user: chi lay key user da nhap trong phien nay.
    - local: doc config.json tren may."""
    if is_multi_user():
        return dict(st.session_state.get("user_cfg", {}))
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_config() -> dict:
    """Cau hinh HIEU LUC de goi API:
    - multi-user: key user nhap trong phien ƯU TIÊN, thieu thi fallback key chung cua chu.
    - local: config.json + Secrets/env ghi de (nhu cu)."""
    owner = _owner_config()
    if is_multi_user():
        merged = dict(owner)  # fallback key chung
        for k, v in st.session_state.get("user_cfg", {}).items():
            if v:  # key user nhap thang len tren
                merged[k] = v
        return merged
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    cfg.update({k: v for k, v in owner.items() if v})  # local van cho phep env override
    return cfg


def save_config(cfg: dict) -> None:
    """Multi-user: luu trong PHIEN (khong cham o dia server). Local: ghi config.json."""
    if is_multi_user():
        st.session_state["user_cfg"] = cfg
    else:
        CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )


# ---------------------------------------------------------------- lich su 24h
def _history_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(HISTORY_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS runs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, label TEXT, sheets TEXT)"
    )
    return conn


def save_history(kind: str, label: str, sheets: dict) -> None:
    """Luu 1 lan chay (moi sheet 1 DataFrame). Loi lich su khong duoc pha luong chinh."""
    try:
        payload = json.dumps(
            {name: df.to_dict("records") for name, df in sheets.items()},
            ensure_ascii=False,
            default=str,
        )
        conn = _history_conn()
        try:
            conn.execute("DELETE FROM runs WHERE ts < ?", (time.time() - HISTORY_TTL,))
            conn.execute(
                "INSERT INTO runs (ts, kind, label, sheets) VALUES (?,?,?,?)",
                (time.time(), kind, label, payload),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass


def list_history() -> list:
    try:
        conn = _history_conn()
        try:
            conn.execute("DELETE FROM runs WHERE ts < ?", (time.time() - HISTORY_TTL,))
            conn.commit()
            return conn.execute(
                "SELECT id, ts, kind, label FROM runs ORDER BY ts DESC"
            ).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return []


def load_history_sheets(run_id: int) -> dict:
    try:
        conn = _history_conn()
        try:
            row = conn.execute(
                "SELECT sheets FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return {}
        return {name: pd.DataFrame(rows) for name, rows in json.loads(row[0]).items()}
    except Exception:  # noqa: BLE001
        return {}


def clear_history() -> None:
    try:
        conn = _history_conn()
        try:
            conn.execute("DELETE FROM runs")
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass


def pick_expand_sources(rows: list, k: int, target_domain: str, queried: set) -> list:
    """Chon toi da k trang nguon cua tier hien tai de tim backlink tier ke tiep.

    Uu tien trang co rank cao nhat; moi domain chi lay 1 trang (da dang nguon);
    bo trang thuoc chinh site dich va trang da query roi.
    """

    def rank_of(r):
        pv = r.get("Rank trang nguồn")
        dv = r.get("Rank domain nguồn")
        return (
            pv if isinstance(pv, (int, float)) else -1,
            dv if isinstance(dv, (int, float)) else -1,
        )

    picked, seen_domains = [], set()
    for r in sorted(rows, key=rank_of, reverse=True):
        u = r.get("URL nguồn")
        if not u or u in queried:
            continue
        d = urlparse(u).netloc.lower()
        if d.startswith("www."):
            d = d[4:]
        if not d or d in seen_domains:
            continue
        if target_domain and (d == target_domain or d.endswith("." + target_domain)):
            continue
        seen_domains.add(d)
        picked.append(u)
        if len(picked) >= k:
            break
    return picked


# ---------------------------------------------------------------- UI
st.set_page_config(page_title="Tool Check Backlink SEO", page_icon="🔗", layout="wide")
st.title("🔗 Tool Check Backlink SEO")
st.caption("Check backlink còn sống / anchor / dofollow — và trace redirect 301 của bất kỳ URL nào.")

# khi deploy web: dat APP_PASSWORD (env/secrets) de nguoi la khong dung duoc key API cua ban
_app_pw = get_secret("APP_PASSWORD")
if _app_pw and not st.session_state.get("auth_ok"):
    st.text_input("🔒 Mật khẩu truy cập", type="password", key="pw_in")
    if st.button("Đăng nhập", type="primary"):
        if st.session_state.get("pw_in") == str(_app_pw):
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Sai mật khẩu.")
    st.stop()

tab_backlink, tab_redirect, tab_api, tab_history = st.tabs(
    [
        "🔗 Check Backlink",
        "↪️ Check Redirect 301",
        "📊 Phân tích Backlink (API)",
        "📜 Lịch sử (24h)",
    ]
)

# ---------- TAB 1: BACKLINK ----------
with tab_backlink:
    st.subheader("Kiểm tra backlink trỏ về site của bạn")
    target_raw = st.text_input(
        "Domain đích (site nhận backlink)",
        placeholder="vd: example.com hoặc https://example.com",
    )
    backlink_text = st.text_area(
        "Danh sách URL chứa backlink (mỗi dòng 1 URL)",
        height=220,
        placeholder="https://blog-a.com/bai-viet-1\nhttps://forum-b.com/thread-2\n...",
    )
    up1 = st.file_uploader("Hoặc upload file .txt / .csv (cột đầu là URL)", type=["txt", "csv"], key="up1")
    if up1 is not None:
        raw = up1.read().decode("utf-8", errors="ignore")
        if up1.name.lower().endswith(".csv"):
            raw = "\n".join(line.split(",")[0] for line in raw.splitlines())
        backlink_text = raw

    workers_bl = st.number_input(
        "Số luồng chạy song song", min_value=1, max_value=50, value=10, step=1, key="workers_bl"
    )

    if st.button("🚀 Check Backlink", type="primary", use_container_width=True):
        target = normalize_domain(target_raw)
        urls = parse_url_list(backlink_text)
        if not target:
            st.error("Vui lòng nhập domain đích.")
        elif not urls:
            st.error("Vui lòng nhập ít nhất 1 URL backlink.")
        else:
            st.info(f"Đang check **{len(urls)}** URL, tìm link trỏ về **{target}** ...")
            results = run_parallel(
                lambda u: check_backlink(u, target), urls, int(workers_bl), "Đang check backlink"
            )
            st.session_state["backlink_df"] = pd.DataFrame(results)
            save_history(
                "Check Backlink", f"{target} — {len(urls)} URL",
                {"Backlink": st.session_state["backlink_df"]},
            )

    if "backlink_df" in st.session_state:
        df = st.session_state["backlink_df"]
        alive = (df["Còn link?"] == "✅ Còn link").sum()
        lost = (df["Còn link?"] == "❌ Mất link").sum()
        errors = len(df) - alive - lost
        dofollow = (df["Loại link"] == "dofollow").sum()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("✅ Còn link", int(alive))
        c2.metric("❌ Mất link", int(lost))
        c3.metric("⚠️ Lỗi truy cập", int(errors))
        c4.metric("Dofollow", int(dofollow))
        st.dataframe(df, use_container_width=True, height=420)
        st.download_button(
            "📥 Tải kết quả Excel",
            data=to_excel_bytes(df, "Backlink"),
            file_name="check_backlink.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

# ---------- TAB 2: REDIRECT ----------
with tab_redirect:
    st.subheader("Trace chuỗi redirect (301 / 302 / 307 / 308)")
    redirect_text = st.text_area(
        "Danh sách URL cần check (mỗi dòng 1 URL)",
        height=220,
        placeholder="https://old-domain.com/page-cu\nhttp://example.com\n...",
    )
    up2 = st.file_uploader("Hoặc upload file .txt / .csv (cột đầu là URL)", type=["txt", "csv"], key="up2")
    if up2 is not None:
        raw = up2.read().decode("utf-8", errors="ignore")
        if up2.name.lower().endswith(".csv"):
            raw = "\n".join(line.split(",")[0] for line in raw.splitlines())
        redirect_text = raw

    workers_rd = st.number_input(
        "Số luồng chạy song song", min_value=1, max_value=50, value=10, step=1, key="workers_rd"
    )
    st.caption(
        "Tool luôn tự soi thêm **redirect ẩn** trong HTML trang cuối (meta refresh / JS). "
        "Hai lựa chọn dưới đây soi sâu hơn nhưng chạy chậm hơn:"
    )
    with st.expander("🕵️ Soi cloaking bằng nhiều User-Agent (đa nguồn, tùy chọn)"):
        st.caption(
            "Gọi mỗi URL bằng NHIỀU 'danh tính' bot khác nhau rồi so kết quả — lệch nhau là nghi "
            "site giấu redirect với bot SEO. Bạn tự chọn con nào để soi (≥2 mới so được), thêm được "
            "UA riêng. Lưu ý: site xác minh Googlebot bằng IP thật thì không kết luận được."
        )
        ua_sel = st.multiselect(
            "Các User-Agent dùng để soi",
            list(UA_PRESETS.keys()),
            default=UA_DEFAULT,
            key="ua_sel",
        )
        ua_custom = st.text_area(
            "Thêm User-Agent tùy chỉnh (mỗi dòng 1 UA — tùy chọn)",
            height=68, placeholder="MyBot/1.0 (+https://...)", key="ua_custom",
        )
    with st.expander("🕰️ Tra lịch sử redirect (đa nguồn, tùy chọn)"):
        st.caption(
            "Xem mỗi URL TỪNG trỏ 301 về đâu trong quá khứ (bắt redirect đã gỡ/đang giấu). "
            "Lưu ý: các kho lưu trữ (Wayback, archive.today) **chặn truy cập tự động** (giới hạn IP / Cloudflare) "
            "nhưng **mở bằng trình duyệt thì xem được** — nên tool sẽ **đưa link bấm mở tay**, và cố đọc tự động khi được. "
            "Không phải lỗi tool."
        )
        hist_sel = st.multiselect(
            "Nguồn tra lịch sử",
            list(HISTORY_SOURCES.keys()),
            default=[],
            key="hist_sel",
        )

    # gom cau hinh nguon (da nguon, user tu chon)
    ua_pairs = [(lbl, UA_PRESETS[lbl]) for lbl in ua_sel]
    ua_pairs += [
        (f"UA riêng {i + 1}", line.strip())
        for i, line in enumerate(ua_custom.splitlines()) if line.strip()
    ]

    if st.button("🚀 Check Redirect", type="primary", use_container_width=True):
        urls = parse_url_list(redirect_text)
        if not urls:
            st.error("Vui lòng nhập ít nhất 1 URL.")
        elif len(ua_pairs) == 1:
            st.error("Soi cloaking cần ≥2 User-Agent — chọn thêm 1 nguồn hoặc bỏ chọn hết.")
        else:
            st.info(f"Đang trace redirect cho **{len(urls)}** URL ...")
            results = run_parallel(
                lambda u: check_redirect(u, ua_pairs, hist_sel),
                urls, int(workers_rd), "Đang trace redirect",
            )
            st.session_state["redirect_df"] = pd.DataFrame(results)
            save_history(
                "Check Redirect", f"{len(urls)} URL",
                {"Redirect": st.session_state["redirect_df"]},
            )

    if "redirect_df" in st.session_state:
        df = st.session_state["redirect_df"]
        is301 = df["Kết quả"].str.startswith("✅ 301").sum()
        none_ = (df["Kết quả"] == "⏺ Không redirect").sum()
        other = df["Kết quả"].str.startswith("⚠️").sum()
        errors = df["Kết quả"].str.startswith("❌").sum()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("✅ Redirect 301", int(is301))
        c2.metric("⏺ Không redirect", int(none_))
        c3.metric("⚠️ Redirect khác 301", int(other))
        c4.metric("❌ Lỗi", int(errors))
        st.dataframe(df, use_container_width=True, height=420)
        st.download_button(
            "📥 Tải kết quả Excel",
            data=to_excel_bytes(df, "Redirect"),
            file_name="check_redirect.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    st.divider()
    st.subheader("🔎 Tìm domain đang trỏ 301 về một domain (qua API)")
    st.caption(
        "Ngược với trace ở trên: nhập domain đích → tool quét index API liệt kê **mọi trang/domain đang "
        "(hoặc từng) 301 về domain đó**. Vì mỗi nguồn API có index khác nhau, nên chọn **Gộp** để "
        "cộng dồn nhiều nguồn → phủ nhiều nhất, đỡ sót. Tốn phí theo nguồn (SE Ranking ~1 credit/dòng)."
    )
    _cfg_r = load_config()
    _has_se = bool(_cfg_r.get("se_keys"))
    _has_dfs = bool(_cfg_r.get("dfs_login") and _cfg_r.get("dfs_password"))
    # liet ke ro 3 lua chon giong tab Phan tich Backlink — chon 1 nguon hoac Gop tuy y
    _src_opts = [
        "DataForSEO",
        "SE Ranking (xoay nhiều key)",
        "Gộp (SE Ranking + DataForSEO)",
    ]
    _saved_prov_r = _cfg_r.get("provider", "DataForSEO")
    _src_idx = 0 if _saved_prov_r == "DataForSEO" else (1 if _saved_prov_r == "SE Ranking" else 2)
    colr1, colr2 = st.columns([2, 1])
    with colr1:
        origin_src = st.radio(
            "Nguồn dữ liệu",
            _src_opts,
            index=_src_idx,
            horizontal=True,
            help="Chọn 1 nguồn (rẻ hơn, chỉ tốn credit 1 bên) hoặc Gộp cả 2 (phủ rộng nhất, tốn credit cả 2 bên). Key lấy từ tab '📊 Phân tích Backlink (API)'.",
        )
    with colr2:
        origin_limit = int(st.number_input(
            "Số dòng quét tối đa / nguồn",
            min_value=10, max_value=10000, value=1000, step=100, key="origin_limit",
        ))
    if not (_has_se or _has_dfs):
        st.warning(
            "Chưa có key API nào. Mở tab '📊 Phân tích Backlink (API)' → '🔑 Cấu hình API' "
            "nhập key rồi quay lại đây."
        )
    origin_url_raw = st.text_input(
        "Domain đích (nơi các trang khác trỏ 301 về)",
        placeholder="vd: example.com",
        key="origin_url",
    )
    if st.button("🔎 Tìm domain trỏ 301 về đây", type="primary", use_container_width=True):
        origin_url = normalize_url(origin_url_raw)
        if not origin_url:
            st.error("Vui lòng nhập domain đích.")
        else:
            _prov_arg = (
                "DataForSEO" if origin_src == "DataForSEO"
                else ("SE Ranking" if origin_src.startswith("SE Ranking") else "Gộp")
            )
            try:
                provider2 = build_provider(
                    _prov_arg,
                    _cfg_r.get("dfs_login", ""),
                    _cfg_r.get("dfs_password", ""),
                    _cfg_r.get("se_keys", []),
                )
                with st.spinner(f"[{provider2.name}] Đang quét redirect trỏ về {origin_url} ..."):
                    rows = provider2.redirect_sources(origin_url, origin_limit)
                for n in getattr(provider2, "notes", []):
                    st.warning(n)
                st.session_state["origin_df"] = pd.DataFrame(rows)
                st.session_state["origin_target"] = origin_url
                if rows:
                    save_history(
                        "Domain trỏ 301", f"{origin_url} — {provider2.name}",
                        {"Domain tro 301": st.session_state["origin_df"]},
                    )
                else:
                    st.info(
                        "Không nguồn nào ghi nhận redirect trỏ về domain này. Index chỉ biết những gì "
                        "bot từng crawl — nếu bạn chắc chắn có redirect, hãy thêm nguồn API khác (DataForSEO "
                        "có index rất lớn) để tăng độ phủ, hoặc redirect đó đang bị cloaking/chặn bot."
                    )
            except ProviderError as e:
                st.error(
                    f"{e}\n\nMở tab '📊 Phân tích Backlink (API)' → mục '🔑 Cấu hình API' để kiểm tra key."
                )

    odf = st.session_state.get("origin_df")
    if odf is not None and not odf.empty:
        st.markdown(f"**Trang/domain trỏ 301 về:** `{st.session_state.get('origin_target', '')}`")
        alive_301 = odf["Trạng thái"].astype(str).str.startswith("✅").sum()
        n_dom = odf["Trang gốc (trỏ 301 về)"].map(
            lambda u: urlparse(str(u)).netloc.lower()
        ).nunique()
        c1, c2, c3 = st.columns(3)
        c1.metric("🔗 Tổng redirect", len(odf))
        c2.metric("✅ Đang trỏ", int(alive_301))
        c3.metric("🌐 Số domain gốc", int(n_dom))
        if "Nguồn" in odf.columns:
            st.caption("Nguồn: " + ", ".join(f"{k} ({v})" for k, v in odf["Nguồn"].value_counts().items()))
        # bang don gian theo domain: bo cot phan nhom URL (khong can khi check domain)
        show_cols = [c for c in [
            "Trang gốc (trỏ 301 về)", "Redirect đến", "Trạng thái", "Ngày ghi nhận", "Nguồn"
        ] if c in odf.columns]
        st.dataframe(odf[show_cols], use_container_width=True, height=360)
        st.download_button(
            "📥 Tải danh sách trang gốc (Excel)",
            data=to_excel_bytes(odf, "Trang goc 301"),
            file_name="trang_goc_301.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

# ---------- TAB 3: PHAN TICH BACKLINK QUA API ----------
with tab_api:
    st.subheader("Phân tích toàn bộ backlink của site bất kỳ (qua API)")
    cfg = load_config()  # cau hinh hieu luc (session + fallback key chung)
    disp = config_for_display()  # gia tri hien len o nhap (khong lo key chung cho nguoi khac)
    _multi = is_multi_user()
    _owner_has = bool(_owner_config())

    if _multi:
        st.info(
            "🌐 **Chế độ nhiều người dùng**: key bạn nhập dưới đây chỉ lưu trong **phiên của bạn** "
            "(không ghi lên server, không ai thấy key của bạn), mất khi đóng tab."
            + (
                " Nếu bạn để trống, hệ thống dùng **key chung của chủ web**."
                if _owner_has else ""
            )
        )

    _exp_title = (
        "🔑 Cấu hình API (chỉ lưu trong phiên của bạn)" if _multi
        else "🔑 Cấu hình API (lưu local trên máy bạn)"
    )
    with st.expander(_exp_title, expanded=not disp):
        _prov_options = [
            "DataForSEO",
            "SE Ranking (xoay nhiều key)",
            "Gộp (SE Ranking + DataForSEO)",
        ]
        _saved_prov = disp.get("provider", "DataForSEO")
        provider_name = st.radio(
            "Nguồn dữ liệu",
            _prov_options,
            horizontal=True,
            index=(
                0 if _saved_prov == "DataForSEO" else (1 if _saved_prov == "SE Ranking" else 2)
            ),
            help="Gộp = chạy cả 2 nguồn song song, cộng kết quả + loại trùng → độ phủ cao nhất (tốn phí cả 2 bên; thiếu key 1 bên thì tự chạy bên còn lại và báo warning).",
        )
        col_a, col_b = st.columns(2)
        with col_a:
            dfs_login = st.text_input(
                "DataForSEO API Login", value=disp.get("dfs_login", "")
            )
        with col_b:
            dfs_password = st.text_input(
                "DataForSEO API Password",
                value=disp.get("dfs_password", ""),
                type="password",
            )
        se_keys_text = st.text_area(
            "SE Ranking API key (mỗi dòng 1 key — key hết credit sẽ TỰ ĐỘNG chuyển sang key kế tiếp)",
            value="\n".join(disp.get("se_keys", [])),
            height=110,
            placeholder="key-thu-nhat\nkey-thu-hai\n...",
        )
        _save_label = "💾 Dùng cho phiên này" if _multi else "💾 Lưu cấu hình"
        if st.button(_save_label, use_container_width=True):
            save_config(
                {
                    "provider": (
                        "DataForSEO"
                        if provider_name == "DataForSEO"
                        else ("SE Ranking" if provider_name.startswith("SE Ranking") else "Gộp")
                    ),
                    "dfs_login": dfs_login.strip(),
                    "dfs_password": dfs_password.strip(),
                    "se_keys": [
                        k.strip() for k in se_keys_text.splitlines() if k.strip()
                    ],
                }
            )
            st.success(
                "Đã lưu cho phiên của bạn (không ghi lên server)." if _multi
                else "Đã lưu vào config.json (chỉ nằm trên máy bạn)."
            )
            st.rerun()

    target_api = st.text_input(
        "Domain / URL cần phân tích",
        placeholder="vd: competitor.com hoặc https://competitor.com/trang",
    )
    col1, col2 = st.columns(2)
    with col1:
        mode = st.selectbox(
            "Phạm vi",
            ["domain", "host", "url"],
            help="domain = tính cả subdomain • host = đúng domain nhập • url = đúng 1 URL",
        )
    with col2:
        max_tier = st.selectbox(
            "Phân tích đến tier",
            [1, 2, 3],
            index=0,
            help="Tier 1: link trỏ thẳng về site bạn nhập • Tier 2: link trỏ về các trang tier 1 • Tier 3: link trỏ về các trang tier 2",
        )
    col3, col4, col5, col6 = st.columns(4)
    with col3:
        tier1_limit = int(st.number_input(
            "Số backlink thu thập ở Tier 1",
            min_value=10, max_value=1000000, value=1000, step=100,
            help="Nhập bao nhiêu lấy bấy nhiêu (đến hết dữ liệu). >10.000: SE Ranking tự phân trang qua /raw (cursor next); DataForSEO tự gộp nhiều lượt 1.000 (offset). Nhớ: 1 backlink = 1 credit SE Ranking.",
        ))
    with col4:
        src_limit = int(st.number_input(
            "Số backlink mỗi nguồn ở Tier 2/3",
            min_value=10, max_value=1000000, value=500, step=100,
            help="Số backlink tối đa lấy cho MỖI trang nguồn được mở rộng (chỉ dùng khi phân tích tier 2/3)",
        ))
    with col5:
        expand_k = int(st.number_input(
            "Số nguồn mở rộng mỗi tier",
            min_value=1, max_value=200, value=10, step=1,
            help="Mỗi tier chọn N trang nguồn rank cao nhất (mỗi domain 1 trang) để tìm tiếp backlink của chúng",
        ))
    with col6:
        api_workers = int(st.number_input(
            "Số luồng gọi API song song",
            min_value=1, max_value=10, value=5, step=1,
        ))

    n_expand = (expand_k if max_tier >= 2 else 0) + (expand_k if max_tier >= 3 else 0)
    est_se = 100 + tier1_limit * 2 + n_expand * src_limit
    est_dfs = 0.024 * (3 + n_expand) + 0.000036 * (tier1_limit * 2 + n_expand * src_limit)
    if provider_name.startswith("SE Ranking"):
        st.caption(
            f"💳 Ước tính tối đa ~{est_se:,} credit SE Ranking cho 1 lần chạy "
            f"(summary 100 + anchor & backlink tier 1 ~{tier1_limit * 2:,}"
            + (f" + {n_expand} lượt mở rộng × {src_limit:,} dòng" if n_expand else "")
            + ")."
        )
    elif provider_name.startswith("Gộp"):
        st.caption(
            f"💳 Nguồn Gộp chạy CẢ 2 bên: ~{est_se:,} credit SE Ranking + ~${est_dfs:.2f} DataForSEO cho 1 lần chạy."
        )
    else:
        st.caption(f"💳 Ước tính tối đa ~${est_dfs:.2f} DataForSEO cho 1 lần chạy.")

    if st.button("🚀 Phân tích Backlink theo Tier", type="primary", use_container_width=True):
        tgt = target_api.strip().rstrip("/")
        if tgt.startswith(("http://", "https://")) and mode != "url":
            tgt = normalize_domain(tgt)
        if not tgt:
            st.error("Vui lòng nhập domain hoặc URL cần phân tích.")
        else:
            provider = None
            try:
                # o nhap trong (mo hinh B: user khong nhap) -> fallback key chung tu load_config()
                _eff = load_config()
                _run_login = dfs_login.strip() or _eff.get("dfs_login", "")
                _run_pass = dfs_password.strip() or _eff.get("dfs_password", "")
                _run_se = [
                    k.strip() for k in se_keys_text.splitlines() if k.strip()
                ] or _eff.get("se_keys", [])
                provider = build_provider(
                    provider_name, _run_login, _run_pass, _run_se
                )
                warnings = []
                target_domain = normalize_domain(tgt)
                bar = st.progress(0.0, text=f"[{provider.name}] Đang lấy tổng quan + anchor...")
                summary_rows = provider.summary(tgt, mode)
                anchor_rows = provider.anchors(tgt, mode, tier1_limit)

                # ---- Tier 1: backlink tro thang ve target ----
                bar.progress(0.15, text=f"[{provider.name}] Tier 1: đang lấy backlink trỏ về {tgt}...")
                seen_pairs = set()
                tiers = {}
                tier1 = []
                fetched_t1 = provider.backlinks(tgt, mode, tier1_limit)
                for r in fetched_t1:
                    pair = (r.get("URL nguồn"), r.get("URL đích"))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    tier1.append({"Tier": 1, "Trỏ về": tgt, **r})
                tiers[1] = tier1
                total_api = max(
                    (
                        v
                        for k, v in summary_rows
                        if str(k).startswith("Tổng backlink") and isinstance(v, (int, float))
                    ),
                    default=None,
                )
                if isinstance(total_api, (int, float)) and len(fetched_t1) < min(
                    tier1_limit, int(total_api)
                ):
                    warnings.append(
                        f"Tier 1: API chỉ trả {len(fetched_t1):,} backlink dù index {provider.name} "
                        f"báo có {int(total_api):,} và bạn yêu cầu {tier1_limit:,} — phần còn lại "
                        f"nguồn dữ liệu chưa cung cấp được (không phải tool bỏ sót)."
                    )
                if len(fetched_t1) > len(tier1):
                    warnings.append(
                        f"Tier 1: đã gộp {len(fetched_t1) - len(tier1):,} dòng trùng "
                        f"(cùng URL nguồn → cùng URL đích)."
                    )

                # ---- Tier 2, 3: backlink tro ve cac trang nguon cua tier truoc ----
                queried = {tgt}
                for tier_n in (2, 3):
                    if tier_n > max_tier or not tiers[tier_n - 1]:
                        break
                    sources = pick_expand_sources(
                        tiers[tier_n - 1], expand_k, target_domain, queried
                    )
                    if not sources:
                        warnings.append(f"Tier {tier_n}: không còn nguồn nào đủ điều kiện để mở rộng.")
                        break
                    queried.update(sources)
                    rows_n = []
                    base = 0.2 + 0.4 * (tier_n - 2)
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=api_workers
                    ) as ex:
                        futs = {
                            ex.submit(provider.backlinks, src, "url", src_limit): src
                            for src in sources
                        }
                        done = 0
                        for fut in concurrent.futures.as_completed(futs):
                            src = futs[fut]
                            done += 1
                            bar.progress(
                                base + 0.4 * done / len(futs),
                                text=f"[{provider.name}] Tier {tier_n}: {done}/{len(futs)} nguồn ({src[:60]}...)",
                            )
                            try:
                                got = fut.result()
                            except ProviderError as e:
                                warnings.append(f"Tier {tier_n} — {src}: {e}")
                                continue
                            for r in got:
                                pair = (r.get("URL nguồn"), r.get("URL đích"))
                                if pair in seen_pairs:
                                    continue
                                seen_pairs.add(pair)
                                rows_n.append({"Tier": tier_n, "Trỏ về": src, **r})
                    tiers[tier_n] = rows_n

                bar.empty()
                warnings.extend(getattr(provider, "notes", []))
                st.session_state["api_result"] = {
                    "target": tgt,
                    "provider": provider.name,
                    "max_tier": max_tier,
                    "summary": summary_rows,
                    "anchors": anchor_rows,
                    "tiers": tiers,
                    "warnings": warnings,
                    "key_log": dict(provider.key_log),
                }
                _hist_sheets = {
                    "Tong quan": pd.DataFrame(summary_rows, columns=["Chỉ số", "Giá trị"]),
                    "Anchors": pd.DataFrame(anchor_rows),
                }
                for _t in sorted(tiers):
                    _hist_sheets[f"Tier {_t}"] = pd.DataFrame(tiers[_t])
                save_history(
                    "Phân tích API", f"{tgt} — tier {max_tier} — {provider.name}", _hist_sheets
                )
            except ProviderError as e:
                st.error(str(e))
                if provider is not None and provider.key_log:
                    with st.expander("🔁 Trạng thái xoay key", expanded=True):
                        for label, status in provider.key_log.items():
                            st.write(f"- **{label}**: {status}")

    res = st.session_state.get("api_result")
    if res:
        st.markdown(f"### Kết quả: `{res['target']}` — nguồn **{res['provider']}**")

        for w in res.get("warnings", []):
            st.warning(w)

        if res["key_log"]:
            with st.expander("🔁 Trạng thái xoay key", expanded=any(
                "⛔" in v for v in res["key_log"].values()
            )):
                for label, status in res["key_log"].items():
                    st.write(f"- **{label}**: {status}")

        tiers = res["tiers"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🔗 Backlink Tier 1", len(tiers.get(1, [])))
        c2.metric("🔗 Backlink Tier 2", len(tiers.get(2, [])))
        c3.metric("🔗 Backlink Tier 3", len(tiers.get(3, [])))
        total_sum = max(
            (
                v
                for k, v in res["summary"]
                if "Tổng backlink" in str(k) and isinstance(v, (int, float))
            ),
            default=None,
        )
        c4.metric(
            "🌍 Tổng backlink (theo API)",
            f"{total_sum:,}" if isinstance(total_sum, (int, float)) else "—",
        )

        sum_df = pd.DataFrame(res["summary"], columns=["Chỉ số", "Giá trị"])
        an_df = pd.DataFrame(res["anchors"])
        tier_dfs = {t: pd.DataFrame(rows) for t, rows in tiers.items()}
        all_rows = [r for t in sorted(tiers) for r in tiers[t]]
        all_df = pd.DataFrame(all_rows)

        tab_labels = [f"Tier {t} ({len(df)})" for t, df in sorted(tier_dfs.items())]
        tab_labels += [f"⚓ Anchor ({len(an_df)})", "📋 Tổng quan"]
        sub_tabs = st.tabs(tab_labels)
        for i, (t, df) in enumerate(sorted(tier_dfs.items())):
            with sub_tabs[i]:
                st.dataframe(df, use_container_width=True, height=420)
        with sub_tabs[-2]:
            st.dataframe(an_df, use_container_width=True, height=420)
        with sub_tabs[-1]:
            st.dataframe(sum_df, use_container_width=True)

        sheets = {"Tong quan": sum_df, "Anchors": an_df}
        for t, df in sorted(tier_dfs.items()):
            sheets[f"Tier {t}"] = df
        sheets["Tat ca (gop tier)"] = all_df
        st.download_button(
            f"📥 Tải báo cáo Excel ({len(sheets)} sheet: Tổng quan, Anchor, từng Tier, Gộp)",
            data=to_excel_multi(sheets),
            file_name=f"backlink_tier_{res['target'].replace('/', '_').replace(':', '')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

# ---------- TAB 4: LICH SU TRACKING 24H ----------
with tab_history:
    st.subheader("📜 Lịch sử tracking (tự xóa sau 24 giờ)")
    st.caption(
        "Mỗi lần chạy ở 3 tab kia đều được lưu lại đây (file `history.db` cạnh app). "
        "Quá 24 giờ bản ghi tự bị xóa. Lưu ý khi chạy trên web: host miễn phí có thể reset "
        "ổ đĩa khi app khởi động lại — lịch sử khi đó mất sớm hơn 24h."
    )
    runs = list_history()
    if not runs:
        st.info("Chưa có lịch sử nào trong 24 giờ qua — chạy check ở các tab kia rồi quay lại đây.")
    else:
        labels = {
            f"{datetime.fromtimestamp(ts).strftime('%d/%m %H:%M:%S')} — {kind} — {label}": rid
            for rid, ts, kind, label in runs
        }
        pick = st.selectbox(f"Chọn lần chạy để xem lại ({len(runs)} bản ghi)", list(labels.keys()))
        sheets_h = load_history_sheets(labels[pick])
        if not sheets_h:
            st.warning("Không đọc được bản ghi này.")
        else:
            sub = st.tabs([f"{name} ({len(df)})" for name, df in sheets_h.items()])
            for i, (name, df) in enumerate(sheets_h.items()):
                with sub[i]:
                    st.dataframe(df, use_container_width=True, height=380)
            st.download_button(
                "📥 Tải lại Excel của lần chạy này",
                data=to_excel_multi(sheets_h),
                file_name="lich_su_tracking.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        if st.button("🗑️ Xóa toàn bộ lịch sử", use_container_width=True):
            clear_history()
            st.rerun()
