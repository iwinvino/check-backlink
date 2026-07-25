# -*- coding: utf-8 -*-
"""Adapter goi API phan tich backlink — TACH ROI khoi 2 tab check thu cong.

- DataForSEOProvider : Basic Auth (API login + password), pay-as-you-go.
- SERankingProvider  : nhan NHIEU API key, tu dong XOAY key khi 1 key
  het credit / sai / bi chan (HTTP 401/402/403/429).

Moi provider tra ve du lieu DA CHUAN HOA (nhan cot tieng Viet) de UI
dung chung, khong phu thuoc provider nao — muon them Ahrefs/Majestic
chi can viet them class cung interface: summary / backlinks / anchors /
referring_domains.
"""

import base64
import concurrent.futures
import threading
import time
from urllib.parse import urlsplit

import requests

TIMEOUT = 60


class ProviderError(Exception):
    """Loi tu API — message hien thang len UI cho end-user."""


# ---------------------------------------------------------------- khop URL
def _exact_url_key(u: str) -> str:
    """Khoa so khop 'dung URL': bo scheme/www/'/' cuoi nhung GIU query."""
    if not u:
        return ""
    if "://" not in u:
        u = "http://" + u
    p = urlsplit(u)
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = (p.path or "/").rstrip("/") or "/"
    q = f"?{p.query}" if p.query else ""
    return f"{host}{path}{q}".lower()


def _norm_url_key(u: str) -> str:
    """Khoa chuan hoa rong: nhu _exact_url_key nhung bo ca query (?ga=...)."""
    return _exact_url_key(u).split("?", 1)[0]


def domain_of(u: str) -> str:
    """'https://www.a.com/x' -> 'a.com'."""
    if not u:
        return ""
    if "://" not in u:
        u = "http://" + u
    host = urlsplit(u).netloc.lower()
    return host[4:] if host.startswith("www.") else host


MATCH_EXACT = "✅ đúng URL nhập"
MATCH_NORM = "≈ khớp sau chuẩn hóa (bỏ www/?tham số)"
MATCH_CHAIN = "🔗 nằm giữa chuỗi redirect"
MATCH_OTHER = "↔️ URL khác cùng domain"
_MATCH_ORDER = {MATCH_EXACT: 0, MATCH_NORM: 1, MATCH_CHAIN: 2, MATCH_OTHER: 3}


def classify_match(input_url: str, url_to: str, chain_urls=None) -> str:
    """Phan loai 1 redirect tim duoc so voi URL user nhap."""
    if _exact_url_key(url_to) == _exact_url_key(input_url):
        return MATCH_EXACT
    if _norm_url_key(url_to) == _norm_url_key(input_url):
        return MATCH_NORM
    for c in chain_urls or []:
        if _norm_url_key(c) == _norm_url_key(input_url):
            return MATCH_CHAIN
    return MATCH_OTHER


def sort_redirect_rows(rows: list) -> list:
    """Nhom khop len tren, trong nhom thi link con song len truoc."""
    return sorted(
        rows,
        key=lambda r: (
            _MATCH_ORDER.get(r.get("Khớp"), 9),
            0 if str(r.get("Trạng thái", "")).startswith("✅") else 1,
        ),
    )


# ================================================================ DataForSEO
class DataForSEOProvider:
    name = "DataForSEO"
    BASE = "https://api.dataforseo.com/v3/backlinks"

    def __init__(self, login: str, password: str):
        if not login or not password:
            raise ProviderError(
                "Chưa nhập DataForSEO API login/password — mở mục '🔑 Cấu hình API' để nhập."
            )
        token = base64.b64encode(f"{login}:{password}".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}"}
        self.key_log = {}  # DataForSEO chi 1 tai khoan, khong xoay key

    def _post(self, endpoint: str, payload: dict) -> dict:
        try:
            r = requests.post(
                f"{self.BASE}/{endpoint}/live",
                json=[payload],
                headers=self._headers,
                timeout=TIMEOUT,
            )
        except requests.exceptions.RequestException as e:
            raise ProviderError(f"Không kết nối được DataForSEO: {type(e).__name__}")
        if r.status_code == 401:
            raise ProviderError("DataForSEO: sai API login hoặc password.")
        try:
            data = r.json()
        except ValueError:
            raise ProviderError(f"DataForSEO trả về dữ liệu lạ (HTTP {r.status_code}).")
        if data.get("status_code") != 20000:
            raise ProviderError(
                f"DataForSEO: {data.get('status_message')} (code {data.get('status_code')})"
            )
        task = (data.get("tasks") or [{}])[0]
        if task.get("status_code") != 20000:
            raise ProviderError(
                f"DataForSEO: {task.get('status_message')} (code {task.get('status_code')}) "
                "— nếu code 402xx thì tài khoản hết tiền, cần nạp thêm."
            )
        result = task.get("result") or []
        return result[0] if result else {}

    @staticmethod
    def _payload(target: str, mode: str, extra: dict = None) -> dict:
        p = {"target": target, "include_subdomains": mode != "host"}
        if extra:
            p.update(extra)
        return p

    def summary(self, target: str, mode: str) -> list:
        r = self._post("summary", self._payload(target, mode, {"internal_list_limit": 10}))
        attrs = r.get("referring_links_attributes") or {}
        rows = [
            ("Rank (DataForSEO)", r.get("rank")),
            ("Tổng backlink", r.get("backlinks")),
            ("Referring domains", r.get("referring_domains")),
            ("Referring main domains", r.get("referring_main_domains")),
            ("Referring IPs", r.get("referring_ips")),
            ("Referring subnets", r.get("referring_subnets")),
            ("Backlink hỏng (broken)", r.get("broken_backlinks")),
            ("Trang đích hỏng (broken pages)", r.get("broken_pages")),
            ("Link nofollow", attrs.get("nofollow")),
            ("First seen", r.get("first_seen")),
        ]
        return [(k, v) for k, v in rows if v is not None]

    MAX_LIMIT = 1000  # DataForSEO toi da 1000 dong / 1 request — vuot thi phan trang bang offset

    def backlinks(self, target: str, mode: str, limit: int) -> list:
        items = []
        offset = 0
        while len(items) < limit:
            chunk = min(limit - len(items), self.MAX_LIMIT)
            r = self._post(
                "backlinks",
                self._payload(
                    target, mode, {"limit": chunk, "offset": offset, "mode": "as_is"}
                ),
            )
            batch = r.get("items") or []
            items.extend(batch)
            if len(batch) < chunk:  # het du lieu
                break
            offset += len(batch)
        return [
            {
                "URL nguồn": it.get("url_from"),
                "URL đích": it.get("url_to"),
                "Anchor": it.get("anchor"),
                "Loại link": "dofollow" if it.get("dofollow") else "nofollow",
                "Rank trang nguồn": it.get("rank"),
                "First seen": it.get("first_seen"),
                "Last seen": it.get("last_seen"),
            }
            for it in items[:limit]
        ]

    def redirect_sources(self, url: str, limit: int) -> list:
        """Tim trang goc tro 301 ve `url`: QUET RONG toan domain cua `url`
        (filter item_type=redirect) roi tu phan nhom kem cot 'Khớp' — bat duoc
        ca redirect dap xuong bien the www/?tham so ma khop chinh xac se truot."""
        target_domain = domain_of(url)
        items = []
        offset = 0
        while len(items) < limit:
            chunk = min(limit - len(items), self.MAX_LIMIT)
            r = self._post(
                "backlinks",
                self._payload(
                    target_domain,
                    "domain",
                    {
                        "limit": chunk,
                        "offset": offset,
                        "mode": "as_is",
                        "filters": ["item_type", "=", "redirect"],
                    },
                ),
            )
            batch = r.get("items") or []
            items.extend(batch)
            if len(batch) < chunk:  # het du lieu
                break
            offset += len(batch)
        out, seen = [], set()
        for it in items[:limit]:
            u = it.get("url_from")
            to = it.get("url_to")
            final = it.get("url_to_redirect_target")
            key = (_exact_url_key(u), _exact_url_key(to))
            if not u or key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "Khớp": classify_match(url, to, [final] if final else None),
                    "Trang gốc (trỏ 301 về)": u,
                    "Redirect đến": to,
                    "Đích cuối chuỗi": final or "",
                    "Trạng thái": "❌ đã mất" if it.get("is_lost") else "✅ đang trỏ",
                    "Ngày ghi nhận": it.get("last_seen"),
                    "Chuỗi trung gian": "",
                    "Rank domain gốc": it.get("domain_from_rank"),
                    "First seen": it.get("first_seen"),
                }
            )
        return sort_redirect_rows(out)

    def anchors(self, target: str, mode: str, limit: int) -> list:
        r = self._post("anchors", self._payload(target, mode, {"limit": min(limit, self.MAX_LIMIT)}))
        return [
            {
                "Anchor": it.get("anchor"),
                "Số backlink": it.get("backlinks"),
                "Referring domains": it.get("referring_domains"),
            }
            for it in r.get("items") or []
        ]

    def referring_domains(self, target: str, mode: str, limit: int) -> list:
        r = self._post(
            "referring_domains", self._payload(target, mode, {"limit": min(limit, self.MAX_LIMIT)})
        )
        return [
            {
                "Domain": it.get("domain"),
                "Rank": it.get("rank"),
                "Số backlink": it.get("backlinks"),
                "Referring pages": it.get("referring_pages"),
            }
            for it in r.get("items") or []
        ]


# ================================================================ SE Ranking
ROTATE_STATUSES = {
    401: "key không hợp lệ",
    402: "hết credit",
    403: "key bị từ chối",
}
# 429 KHONG nam trong ROTATE: la rate limit tam thoi -> gian nhip + thu lai cung key
MIN_INTERVAL = 1.5  # giay giua 2 request (SE Ranking chan goi lien tiep)
MAX_429_RETRIES = 5


class SERankingProvider:
    name = "SE Ranking"
    BASE = "https://api.seranking.com/v1/backlinks"
    MAX_PER_CALL = 10000   # tran 1 luot goi cua /all, /anchors, /refdomains
    MAX_RAW_CALL = 100000  # tran 1 luot goi cua /raw (co phan trang cursor `next`)

    def __init__(self, keys: list):
        self.keys = [k.strip() for k in keys if k and k.strip()]
        if not self.keys:
            raise ProviderError(
                "Chưa nhập SE Ranking API key nào — mở mục '🔑 Cấu hình API' để nhập (mỗi dòng 1 key)."
            )
        self.notes = []  # ghi chu hien len UI (vd: fallback khi /raw loi)
        self._idx = 0
        self._lock = threading.Lock()  # nhieu luong (tier 2/3) cung xoay key an toan
        self._throttle_lock = threading.Lock()
        self._next_slot = 0.0
        self.key_log = {self._label(k): "chưa dùng" for k in self.keys}

    @staticmethod
    def _label(key: str) -> str:
        return f"key ...{key[-6:]}" if len(key) > 6 else f"key {key}"

    def _wait_slot(self):
        """Gian nhip: dam bao 2 request cach nhau >= MIN_INTERVAL giay (ke ca da luong)."""
        with self._throttle_lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + MIN_INTERVAL
        if wait > 0:
            time.sleep(wait)

    def _get(self, endpoint: str, params: dict):
        """Goi API voi key hien tai; 429 (rate limit) -> doi roi thu lai cung key;
        401/402/403 -> XOAY sang key ke tiep."""
        retries_429 = 0
        while True:
            with self._lock:
                if self._idx >= len(self.keys):
                    break
                idx = self._idx
            key = self.keys[idx]
            label = self._label(key)
            self._wait_slot()
            try:
                r = requests.get(
                    f"{self.BASE}/{endpoint}",
                    params=params,
                    headers={"Authorization": f"Token {key}"},
                    timeout=TIMEOUT,
                )
            except requests.exceptions.RequestException as e:
                raise ProviderError(f"Không kết nối được SE Ranking: {type(e).__name__}")
            if r.status_code == 200:
                self.key_log[label] = "✅ đang dùng"
                try:
                    return r.json()
                except ValueError:
                    raise ProviderError("SE Ranking trả về dữ liệu không phải JSON.")
            if r.status_code == 429:
                retries_429 += 1
                if retries_429 > MAX_429_RETRIES:
                    self.key_log[label] = "⛔ rate limit kéo dài → tự chuyển key kế tiếp"
                    with self._lock:
                        if self._idx == idx:
                            self._idx += 1
                    retries_429 = 0
                    continue
                try:
                    wait = int(r.headers.get("Retry-After") or 0)
                except ValueError:
                    wait = 0
                time.sleep(min(wait, 30) or 3 * retries_429)
                continue  # thu lai CUNG key
            if r.status_code in ROTATE_STATUSES:
                self.key_log[label] = (
                    f"⛔ {ROTATE_STATUSES[r.status_code]} (HTTP {r.status_code}) → tự chuyển key kế tiếp"
                )
                with self._lock:
                    if self._idx == idx:  # luong khac co the da chuyen roi
                        self._idx += 1
                continue
            raise ProviderError(f"SE Ranking HTTP {r.status_code}: {r.text[:200]}")
        raise ProviderError(
            "Tất cả SE Ranking key đều hết credit hoặc lỗi — thêm key mới ở mục '🔑 Cấu hình API'."
        )

    @staticmethod
    def _rows(data, *keys) -> list:
        """Response co the la list truc tiep hoac boc trong dict — lay list dau tien tim thay."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in keys:
                v = data.get(k)
                if isinstance(v, list):
                    return v
        return []

    def summary(self, target: str, mode: str) -> list:
        data = self._get("summary", {"target": target, "mode": mode, "output": "json"})
        # response thuc te: {"summary": [{...}]} (da xac nhan bang key that 2026-07-23)
        if isinstance(data, dict) and isinstance(data.get("summary"), list):
            data = data["summary"][0] if data["summary"] else {}
        elif isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            data = {}
        wanted = [
            ("Tổng backlink", ("backlinks", "total_backlinks")),
            ("Referring domains", ("refdomains", "referring_domains")),
            ("Backlink dofollow", ("dofollow_backlinks", "dofollow")),
            ("Backlink nofollow", ("nofollow_backlinks", "nofollow")),
            ("Domain InLink Rank", ("domain_inlink_rank", "domain_trust")),
            ("InLink Rank (trang)", ("inlink_rank",)),
            ("Referring IPs", ("ips", "referring_ips")),
            ("Referring subnets", ("subnets", "referring_subnets")),
            ("Backlink .edu", ("edu_backlinks",)),
            ("Backlink .gov", ("gov_backlinks",)),
            ("Backlink từ trang chủ", ("from_home_page_backlinks",)),
            ("Số anchor khác nhau", ("anchors",)),
            ("Trang đích có backlink", ("pages_with_backlinks",)),
        ]
        rows = []
        for label, names in wanted:
            for n in names:
                if data.get(n) is not None:
                    rows.append((label, data[n]))
                    break
        if not rows and data:  # phong khi SE Ranking doi ten field
            rows = [
                (k, v) for k, v in data.items() if isinstance(v, (int, float, str))
            ][:12]
        return rows

    @staticmethod
    def _norm_backlink(it: dict) -> dict:
        return {
            "URL nguồn": it.get("url_from"),
            "URL đích": it.get("url_to"),
            "Anchor": it.get("anchor"),
            "Loại link": "nofollow" if it.get("nofollow") else "dofollow",
            "Rank trang nguồn": it.get("inlink_rank"),
            "Rank domain nguồn": it.get("domain_inlink_rank"),
            "First seen": it.get("first_seen"),
            "Last seen": it.get("last_visited"),
        }

    def backlinks(self, target: str, mode: str, limit: int) -> list:
        # LUON dung /raw — endpoint "complete backlink retrieval" (docs SE Ranking),
        # tra du lieu day du; /all chi la view loc/sap xep nen co the tra it hon
        # thuc te -> chi dung lam fallback khi /raw loi 40x.
        items = []
        next_token = None
        try:
            while len(items) < limit:
                params = {
                    "target": target,
                    "mode": mode,
                    "limit": min(limit - len(items), self.MAX_RAW_CALL),
                }
                if next_token:
                    params["next"] = next_token
                data = self._get("raw", params)
                batch = self._rows(data, "backlinks", "items", "data")
                if not batch:
                    break
                items.extend(batch)
                next_token = data.get("next") if isinstance(data, dict) else None
                if not next_token:  # het trang
                    break
        except ProviderError as e:
            if items:  # co du lieu roi thi tra ve phan da lay duoc
                self.notes.append(f"Lấy được {len(items):,} backlink thì gặp lỗi: {e}")
            elif "HTTP 40" in str(e):  # /raw khong kha dung -> fallback /all
                cap = min(limit, self.MAX_PER_CALL)
                self.notes.append(
                    f"Endpoint /raw không khả dụng với key này ({e}) — fallback lấy tối đa {cap:,} backlink qua /all."
                )
                data = self._get("all", {"target": target, "mode": mode, "limit": cap})
                items = self._rows(data, "backlinks", "items", "data")
            else:
                raise
        return [self._norm_backlink(it) for it in items[:limit]]

    def redirect_sources(self, url: str, limit: int) -> list:
        """Tim trang goc tro 301 ve `url`: QUET RONG toan domain qua /history
        mode=domain + link_type=redirect (response boc trong `new_lost_backlinks`,
        xac nhan key that 2026-07-25) roi tu phan nhom kem cot 'Khớp' — bat duoc
        redirect dap xuong bien the www/?ga=... va ca URL nam giua chuoi.
        Dedupe theo cap (trang goc, dich), giu su kien moi nhat."""
        data = self._get(
            "history",
            {
                "target": domain_of(url),
                "mode": "domain",
                "link_type": "redirect",
                "date_from": "2000-01-01",
                "limit": min(limit, self.MAX_PER_CALL),
            },
        )
        rows = self._rows(data, "new_lost_backlinks", "backlinks", "items", "data")
        rows.sort(key=lambda it: it.get("new_lost_date") or "", reverse=True)
        out, seen = [], set()
        for it in rows:
            u = it.get("url_from")
            to = it.get("url_to")
            key = (_exact_url_key(u), _exact_url_key(to))
            if not u or key in seen:
                continue
            seen.add(key)
            lost = it.get("new_lost_type") == "lost"
            chain = it.get("redirect_chain_urls") or []
            out.append(
                {
                    "Khớp": classify_match(url, to, chain),
                    "Trang gốc (trỏ 301 về)": u,
                    "Redirect đến": to,
                    "Đích cuối chuỗi": chain[-1] if chain else "",
                    "Trạng thái": (
                        f"❌ đã mất ({it.get('reason_lost') or 'không rõ'})" if lost else "✅ đang trỏ"
                    ),
                    "Ngày ghi nhận": it.get("new_lost_date"),
                    "Chuỗi trung gian": " → ".join(chain),
                    "Rank domain gốc": it.get("domain_inlink_rank"),
                    "First seen": it.get("first_seen"),
                }
            )
        return sort_redirect_rows(out)

    def anchors(self, target: str, mode: str, limit: int) -> list:
        data = self._get(
            "anchors",
            {"target": target, "mode": mode, "limit": min(limit, self.MAX_PER_CALL)},
        )
        return [
            {
                "Anchor": it.get("anchor"),
                "Số backlink": it.get("backlinks"),
                "Referring domains": it.get("refdomains"),
                "Dofollow": it.get("dofollow_backlinks"),
                "Nofollow": it.get("nofollow_backlinks"),
            }
            for it in self._rows(data, "anchors", "items", "data")
        ]

    def referring_domains(self, target: str, mode: str, limit: int) -> list:
        data = self._get(
            "refdomains",
            {"target": target, "mode": mode, "limit": min(limit, self.MAX_PER_CALL)},
        )
        return [
            {
                "Domain": it.get("refdomain") or it.get("domain"),
                "Rank": it.get("domain_inlink_rank"),
                "Số backlink": it.get("backlinks"),
                "Dofollow": it.get("dofollow_backlinks"),
                "First seen": it.get("first_seen"),
            }
            for it in self._rows(data, "refdomains", "items", "data")
        ]


# ================================================================ Gop nguon
class AggregateProvider:
    """Chay NHIEU nguon song song, gop ket qua + loai trung — do phu cao hon
    bat ky nguon don nao. 1 nguon loi thi ghi notes va tiep tuc voi nguon con lai;
    chi raise khi TAT CA nguon deu loi."""

    name = "Gộp (SE Ranking + DataForSEO)"

    def __init__(self, providers: list):
        self.providers = [p for p in providers if p is not None]
        if not self.providers:
            raise ProviderError(
                "Nguồn Gộp cần ít nhất 1 nguồn hợp lệ — kiểm tra key ở mục '🔑 Cấu hình API'."
            )
        self._notes = []

    @property
    def notes(self) -> list:
        merged = list(self._notes)
        for p in self.providers:
            merged.extend(f"[{p.name}] {n}" for n in getattr(p, "notes", []))
        return merged

    @property
    def key_log(self) -> dict:
        merged = {}
        for p in self.providers:
            for k, v in p.key_log.items():
                merged[f"[{p.name}] {k}"] = v
        return merged

    def _fanout(self, method: str, *args) -> list:
        """Goi method tren moi nguon song song -> list (provider, rows) thanh cong."""
        results, errors = [], []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.providers)) as ex:
            futs = {ex.submit(getattr(p, method), *args): p for p in self.providers}
            for fut in concurrent.futures.as_completed(futs):
                p = futs[fut]
                try:
                    results.append((p, fut.result()))
                except ProviderError as e:
                    errors.append((p, e))
        for p, e in errors:
            self._notes.append(f"Nguồn {p.name} lỗi ({e}) — dùng kết quả nguồn còn lại.")
        if not results:
            raise ProviderError(
                "Tất cả nguồn trong Gộp đều lỗi: "
                + " | ".join(f"{p.name}: {e}" for p, e in errors)
            )
        return results

    def summary(self, target: str, mode: str) -> list:
        rows = []
        for p, r in self._fanout("summary", target, mode):
            rows.extend((f"{k} — {p.name}", v) for k, v in r)
        return rows

    def _merge_backlinks(self, results: list, limit: int) -> list:
        merged, seen = [], set()
        per_src = {}
        for p, rows in results:
            per_src[p.name] = len(rows)
            for r in rows:
                key = (_exact_url_key(r.get("URL nguồn")), _exact_url_key(r.get("URL đích")))
                if key in seen:
                    continue
                seen.add(key)
                merged.append({**r, "Nguồn": p.name})
        if len(per_src) > 1:
            detail = " + ".join(f"{n} ({v:,})" for n, v in per_src.items())
            self._notes.append(
                f"Gộp: {detail} → sau loại trùng còn {len(merged):,} backlink."
            )
        return merged

    def backlinks(self, target: str, mode: str, limit: int) -> list:
        return self._merge_backlinks(self._fanout("backlinks", target, mode, limit), limit)

    def anchors(self, target: str, mode: str, limit: int) -> list:
        rows = []
        for p, r in self._fanout("anchors", target, mode, limit):
            rows.extend({**it, "Nguồn": p.name} for it in r)
        return rows

    def referring_domains(self, target: str, mode: str, limit: int) -> list:
        rows = []
        for p, r in self._fanout("referring_domains", target, mode, limit):
            rows.extend({**it, "Nguồn": p.name} for it in r)
        return rows

    def redirect_sources(self, url: str, limit: int) -> list:
        merged, seen = [], set()
        for p, rows in self._fanout("redirect_sources", url, limit):
            for r in rows:
                key = (
                    _exact_url_key(r.get("Trang gốc (trỏ 301 về)")),
                    _exact_url_key(r.get("Redirect đến")),
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append({**r, "Nguồn": p.name})
        return sort_redirect_rows(merged)


# ================================================================ factory
def build_provider(provider_name: str, dfs_login: str, dfs_password: str, se_keys: list):
    if provider_name.startswith("Gộp"):
        subs, errs = [], []
        for maker in (
            lambda: SERankingProvider(se_keys),
            lambda: DataForSEOProvider(dfs_login, dfs_password),
        ):
            try:
                subs.append(maker())
            except ProviderError as e:
                errs.append(str(e))
        agg = AggregateProvider(subs)  # raise neu ca 2 deu thieu key
        for e in errs:
            agg._notes.append(f"⚠️ {e} — Gộp đang chạy thiếu 1 nguồn.")
        return agg
    if provider_name.startswith("SE Ranking"):
        return SERankingProvider(se_keys)
    return DataForSEOProvider(dfs_login, dfs_password)
