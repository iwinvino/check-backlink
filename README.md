# 🔗 Tool Check Backlink SEO

Tool cho end-user (không cần biết code) — 4 tab, mọi thao tác bằng nút bấm:

1. **🔗 Check Backlink** — dán danh sách URL, check link còn trỏ về domain đích không (anchor, dofollow/nofollow, noindex).
2. **↪️ Check Redirect 301** — trace chuỗi redirect từng URL; tự soi **redirect ẩn** (meta refresh / JS); tùy chọn soi **cloaking** (so 3 User-Agent) và tra **lịch sử Wayback Machine**; kèm mục **tìm trang gốc đang trỏ 301 về một URL** (quét rộng toàn domain qua API, tự phân nhóm khớp).
3. **📊 Phân tích Backlink (API)** — phân tích backlink theo tier (1→3) của site bất kỳ. Nguồn dữ liệu chọn trên UI: **DataForSEO**, **SE Ranking** (xoay nhiều key) hoặc **Gộp cả 2** (độ phủ cao nhất). Xuất Excel nhiều sheet.
4. **📜 Lịch sử (24h)** — mọi lần chạy được lưu lại, tự xóa sau 24 giờ, xem lại / tải lại Excel bất kỳ lúc nào.

## Chạy trên máy (Windows)

Double-click `run.bat` → trình duyệt tự mở `localhost:8501`. Xong.

## Deploy lên web (chạy qua website)

> ⚠️ **Streamlit là app Python chạy server** — KHÔNG deploy được lên Vercel / Netlify / GitHub Pages (các nền tảng đó chỉ chạy trang tĩnh/serverless). Dùng các nền tảng dưới đây.

### Bước 0 — đẩy code lên GitHub

```bash
git init
git add .
git commit -m "Tool Check Backlink SEO"
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```

`.gitignore` đã chặn sẵn `config.json` (chứa key API) và `history.db` — **tuyệt đối không commit 2 file này**.

### Cách 1 — Streamlit Community Cloud (miễn phí, dễ nhất) ✅ khuyên dùng

1. Vào <https://share.streamlit.io> → đăng nhập bằng GitHub → **New app** → chọn repo, file `app.py` → Deploy.
2. Vào **App settings → Secrets**, dán (tùy mô hình bên dưới).

### Mô hình dùng chung (khi chia sẻ web cho nhiều người)

App hỗ trợ **mô hình linh hoạt (C)**: mặc định mỗi người tự nhập key của họ (key chỉ nằm trong **phiên** của người đó, KHÔNG ghi lên server, không ai thấy key của ai, mất khi đóng tab); ai không nhập thì fallback dùng **key chung của chủ** (nếu chủ có đặt).

**Bật chế độ nhiều người dùng** — trong Secrets đặt:

```toml
MULTI_USER = "1"                     # BẮT BUỘC khi chia sẻ nhiều người: key user chỉ lưu trong phiên
APP_PASSWORD = "mat-khau-cua-ban"    # nên có, chặn người lạ vào

# (TÙY CHỌN) key chung của chủ — chỉ đặt nếu muốn ai không nhập key vẫn dùng được (xài credit của bạn):
# SE_KEYS = "key-1,key-2"
# DFS_LOGIN = "login-dataforseo"
# DFS_PASSWORD = "password-dataforseo"
# PROVIDER = "Gộp"
```

- Đặt `MULTI_USER=1` **và KHÔNG** đặt key chung → mỗi người bắt buộc nhập key riêng, bạn không tốn credit (mô hình A).
- Đặt `MULTI_USER=1` **và có** key chung → ai nhập key riêng thì dùng key đó, ai không nhập thì xài key chung của bạn (mô hình C).
- Không đặt `MULTI_USER` mà chỉ đặt key chung + `APP_PASSWORD` → mọi người xài chung credit của bạn, không cần nhập gì (mô hình B).

### Cách 2 — Railway / Render (có Procfile sẵn)

1. Railway: <https://railway.app> → **New Project → Deploy from GitHub repo** → tự nhận `Procfile` + `requirements.txt`.
2. Vào **Variables**, thêm các biến y hệt phần Secrets ở trên.
3. Render tương tự: **New → Web Service**, Start Command lấy từ `Procfile`.

### Bảo mật khi chạy public — BẮT BUỘC đọc

- **Chia sẻ nhiều người: LUÔN đặt `MULTI_USER=1`** — nếu không, key một người nhập sẽ ghi vào `config.json` dùng chung trên server và lộ sang người khác.
- **Nên đặt `APP_PASSWORD`**: app hiện màn hình đăng nhập trước. Thiếu nó = ai có link cũng vào được (và nếu bạn có đặt key chung thì họ tiêu credit của bạn).
- Key chung của chủ (`SE_KEYS`...) không bao giờ hiển thị lên ô nhập của người khác — chỉ dùng ngầm làm fallback.
- Lịch sử 24h lưu `history.db` trên ổ đĩa server; host miễn phí reset ổ khi restart → lịch sử có thể mất sớm hơn 24h (muốn bền: gắn Volume trên Railway).

## Bảng biến cấu hình (bản web)

| Biến | Ý nghĩa |
|---|---|
| `MULTI_USER` | `1` = chế độ nhiều người (key user chỉ lưu trong phiên). Bỏ trống = 1 người, lưu `config.json` |
| `APP_PASSWORD` | Mật khẩu vào app (bỏ trống = không khóa) |
| `SE_KEYS` | (tùy chọn) Key chung SE Ranking của chủ, phân cách dấu phẩy — làm fallback |
| `DFS_LOGIN` / `DFS_PASSWORD` | (tùy chọn) Key chung DataForSEO của chủ — làm fallback |
| `PROVIDER` | (tùy chọn) `SE Ranking` / `DataForSEO` / `Gộp` — nguồn mặc định |

Chạy local 1 mình thì bỏ qua bảng trên — nhập key ngay trên giao diện (mục 🔑 Cấu hình API), lưu vào `config.json` trên máy.