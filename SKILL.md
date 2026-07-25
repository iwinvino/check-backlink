# SKILL: Tool Check Backlink SEO

## Mục đích
Tool cho end-user (không biết code) kiểm tra:
1. **Backlink**: danh sách URL chứa backlink có còn trỏ về domain đích không — anchor text, dofollow/nofollow, trang có noindex không.
2. **Redirect 301**: bất kỳ URL nào — trace toàn bộ chuỗi redirect (301/302/303/307/308), URL đích cuối cùng, phát hiện chuỗi dài/vòng lặp; luôn tự soi **redirect ẩn** (meta refresh / JS) ở trang cuối; 2 tùy chọn soi sâu **đa nguồn, user tự chọn**: **soi cloaking** (chọn nhiều User-Agent bot để so: Chrome/Googlebot/Bingbot/Ahrefs/Semrush... + thêm UA riêng — lệch nhau là nghi giấu redirect với bot) và **tra lịch sử redirect** (chọn nguồn: Wayback Machine — chuẩn nhất; hoặc archive.today — dùng khi ISP chặn archive.org). Kèm mục **Tìm domain trỏ 301 về đây** (chiều ngược lại): nhập domain đích → chọn nguồn ngay tại chỗ (**Gộp** nhiều nguồn API / SE Ranking / DataForSEO) → liệt kê mọi trang/domain đang (hoặc từng) 301 về domain đó, bảng đơn giản (Trang gốc → Redirect đến → Trạng thái → Nguồn). **Luôn nên chọn Gộp**: mỗi index API biết khác nhau, 1 nguồn sẽ sót — gộp nhiều nguồn phủ rộng nhất.
3. **Phân tích Backlink theo Tier (API)**: nhập 1 domain/URL → tool tự tìm:
   - **Tier 1** = tất cả backlink + anchor đang trỏ thẳng về domain/URL đó
   - **Tier 2** = backlink trỏ về các trang nguồn của tier 1
   - **Tier 3** = backlink trỏ về các trang nguồn của tier 2
   → Excel nhiều sheet: Tổng quan, Anchor, Tier 1, Tier 2, Tier 3, Gộp tất cả. Nguồn dữ liệu chọn trên UI: **DataForSEO** (login/password), **SE Ranking** (nhiều key, tự xoay khi hết credit), hoặc **Gộp** (chạy cả 2 song song, cộng kết quả + loại trùng → độ phủ cao nhất; thiếu key 1 bên thì tự chạy bên còn lại).
4. **Lịch sử tracking (24h)**: mọi lần chạy ở 3 tab trên tự lưu vào `history.db`, xem lại/tải lại Excel bất kỳ lúc nào, bản ghi quá 24 giờ tự xóa.
   Cách mở rộng tier: mỗi tier chọn N trang nguồn rank cao nhất (mỗi domain 1 trang, loại trang thuộc chính site đích, không query trùng) — N chỉnh bằng thanh trượt "Số nguồn mở rộng mỗi tier".

## Luồng sử dụng (end-user, chỉ bấm nút)
1. Double-click `run.bat` → giao diện web mở tự động.
2. **Tab Check Backlink**: nhập domain đích + dán danh sách URL (hoặc upload .txt/.csv) → bấm "🚀 Check Backlink" → xem bảng + số liệu tổng → bấm "📥 Tải kết quả Excel".
3. **Tab Check Redirect 301**: dán danh sách URL → bấm "🚀 Check Redirect" → xem chuỗi redirect từng URL → tải Excel. Bên dưới, mục "🔎 Tìm trang gốc đang trỏ 301 về một URL": nhập URL hiện tại + số dòng tối đa → bấm "🔎 Tìm trang gốc trỏ 301 về URL này" → bảng trang gốc (✅ đang trỏ / ❌ đã mất theo API) → tải Excel. Mục này cần key API đã lưu ở tab "Phân tích Backlink (API)" và tốn phí như tab đó (SE Ranking ~1 credit/dòng).
4. **Tab Phân tích Backlink (API)**: lần đầu mở mục "🔑 Cấu hình API" → chọn nguồn + nhập key → bấm "💾 Lưu cấu hình" (lưu `config.json` local, chỉ nhập 1 lần). Sau đó nhập domain/URL → chọn phạm vi (domain/host/url), **phân tích đến tier** (mặc định 1) và các Ô NHẬP SỐ trực tiếp: "Số backlink thu thập ở Tier 1" (mặc định 1.000, nhập bao nhiêu lấy bấy nhiêu — tool tự phân trang), "Số backlink mỗi nguồn ở Tier 2/3", "Số nguồn mở rộng mỗi tier", "Số luồng gọi API song song" → xem ước tính phí → bấm "🚀 Phân tích Backlink theo Tier" → xem bảng từng tier + tải Excel. Mục "🔁 Trạng thái xoay key" cho biết key nào đang dùng / key nào hết credit.
5. Số luồng chạy song song của tab 1/2: ô nhập số ngay trong từng tab (mặc định 10). KHÔNG dùng sidebar cho bất kỳ cấu hình nào.

## Giới hạn đã biết (không phải bug)
- Tab 1/2: trang render link bằng JavaScript (SPA) có thể báo "mất link" dù link hiển thị trên trình duyệt — vì tool đọc HTML gốc; site chặn bot (Cloudflare challenge...) sẽ báo lỗi truy cập hoặc 403.
- Tra lịch sử redirect Wayback: nhiều ISP Việt Nam chặn đích danh archive.org (tầng IP/SNI) → báo "không vào được archive.org". Cách xử lý: chọn thêm nguồn archive.today, dùng VPN, hoặc chạy bản deploy web (server ngoài VN vào Wayback bình thường). archive.today vào được nhưng chỉ cho link bản lưu, không đọc được header 301 gốc như Wayback.
- Tab phân tích API + mục "Tìm trang gốc 301": chỉ thấy được những gì **index của nguồn dữ liệu** (SE Ranking/DataForSEO) đã crawl — có thể ít hơn số backlink thực tế trên mạng; nếu API trả ít hơn cả số mà chính nó báo có, tool hiện cảnh báo ngay trên UI.
- Tab 3: tốn phí theo nguồn — DataForSEO ~$0.10–0.15/lần phân tích; SE Ranking ~100 + (số dòng × 3) credit/lần. Trial SE Ranking 100K credit, mỗi tài khoản chỉ được 1 trial — tính năng xoay key dành cho các key hợp lệ user có (nhiều tài khoản trong team...), việc lập hàng loạt tài khoản ảo để lách trial là vi phạm điều khoản SE Ranking, tool không hỗ trợ tự tạo tài khoản.

## Deploy web (bản chạy qua website)
- Streamlit là app server Python → **KHÔNG** deploy Vercel/Netlify/GitHub Pages (chỉ trang tĩnh). Dùng **Streamlit Community Cloud** (miễn phí, khuyên dùng), Railway hoặc Render (`Procfile` sẵn).
- Key API + mật khẩu nhập qua **Secrets/Variables** của nền tảng (biến `APP_PASSWORD`, `SE_KEYS`, `DFS_LOGIN`, `DFS_PASSWORD`, `PROVIDER`) — app tự đọc, không cần `config.json` trên server.
- **Bắt buộc đặt `APP_PASSWORD`** khi chạy public: app hiện màn hình đăng nhập trước, tránh người lạ tiêu credit API của bạn.
- `.gitignore` đã chặn `config.json` + `history.db` — tuyệt đối không commit. Chi tiết trong README.md.

## Quy tắc khi sửa/mở rộng
- Đọc lại file này + CLAUDE.md trước mỗi lệnh.
- Mọi tính năng mới phải có nút/ô nhập trên UI, không thêm bước thủ công cho user.
