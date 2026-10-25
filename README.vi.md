# Comment Reply Bot

🇬🇧 [English](README.md) · 🇻🇳 Tiếng Việt

Tự động lấy comment mới trên **Instagram** và **Facebook Page**, nhờ **Claude** lọc spam và soạn sẵn câu trả lời (đúng giọng từng tài khoản), rồi gửi vào **Slack** để mọi người copy và đăng. Bot **chỉ đọc** từ Meta, không tự đăng, ẩn hay xóa comment nào.

## Cách hoạt động

```
Lịch (mỗi giờ)  →  Claude đọc skill/SKILL.md
                      │
                      ├─ python3 comment_bot.py fetch   (lấy + lọc comment mới từ Meta)
                      ├─ Claude phân loại (cần reply / cần người xử lý / spam) và viết reply
                      └─ python3 comment_bot.py post -  (gửi từng comment vào Slack)
```

Mỗi comment vào Slack thành **hai tin liền nhau**:

1. icon nền tảng, `Tài khoản · Nền tảng`, `@user · Post` (link bấm được), comment in nghiêng
2. chỉ có câu reply (nhấn giữ trên điện thoại → *Copy text*)

Comment cần người xử lý (khiếu nại, hoàn tiền…) chỉ có tin 1 kèm dòng ⚠️ *Needs human*.

Chống gửi trùng không cần database: mỗi tin gắn ID comment vào `block_id`, và trước khi gửi, script đọc lịch sử kênh rồi bỏ comment đã có.

## Gồm những gì

| File | Vai trò |
|---|---|
| `comment_bot.py` | Script (Python 3, không cần cài thêm thư viện). Lệnh `fetch` và `post` |
| `skill/SKILL.md` | Hướng dẫn cho Claude (nội dung của scheduled task / routine) |
| `rules.example.md` | Mẫu quy tắc lọc spam và giọng văn. Copy thành `rules.md` (không đẩy lên GitHub) |
| `.env.example` | Mẫu cấu hình. Copy thành `.env` và điền token |

## Yêu cầu

- Python 3.8+
- Tài khoản Instagram **Business/Creator** nối với một **Page Facebook**
- App Meta với token Page có quyền `instagram_basic`, `instagram_manage_comments`, `pages_show_list`, `pages_read_engagement`, `pages_read_user_content`
- Slack app có bot token (`xoxb-...`), scope `chat:write` và `channels:history` (kênh riêng: `groups:history`), bot đã được mời vào kênh
- Claude Code / app Claude để chạy scheduled task, hoặc routine trên Claude web

## Cài đặt

1. Clone repo vào máy, ví dụ:
   ```bash
   git clone <repo-url> ~/comment-reply-bot
   cd ~/comment-reply-bot
   cp .env.example .env
   ```
2. Điền `.env` (xem `.env.example`). **Không bao giờ commit `.env`** (đã có trong `.gitignore`).
   - **Instagram ID, Page ID, Page token:** Graph API Explorer → chọn app → `GET /me/accounts` cho Page token; Instagram ID lấy từ `GET /{page-id}?fields=instagram_business_account`.
   - **Slack:** api.slack.com/apps → app của bạn → *OAuth & Permissions* → Bot User OAuth Token. Channel ID: chuột phải kênh → *View channel details*.
3. Copy `rules.example.md` thành `rules.md` và mô tả quy tắc lọc spam và giọng văn từng tài khoản (xem phần *Tùy chỉnh*).

## Chạy thử bằng tay

```bash
cd ~/comment-reply-bot && set -a && . ./.env && set +a

# 1) Xem comment mới (chỉ đọc). Tăng LOOKBACK_HOURS để thấy comment cũ hơn.
LOOKBACK_HOURS=168 python3 comment_bot.py fetch

# 2) Gửi thử một comment mẫu vào Slack
python3 comment_bot.py post - <<'JSON'
{"sections":[{"account":"Brand","platform":"Instagram","items":[
 {"id":"TEST-1","user":"@test","link":"https://www.instagram.com/p/EXAMPLE/",
  "comment":"[TEST] Is now a good time to buy property?","reply":"Great question! ...",
  "needs_human":false,"reason":""}]}]}
JSON
```

Chạy lại cùng `id` sẽ báo `posted 0, skipped 1 already in channel`.

## Chạy tự động

### Cách A: Scheduled task trên máy (app Claude)

Cần máy bật và app Claude đang mở. Tạo task mới trong app Claude, lịch ví dụ mỗi giờ từ 8h đến 23h (`0 8-23 * * *`, giờ máy), và dán nội dung `skill/SKILL.md` làm hướng dẫn. Sửa đường dẫn `$HOME/comment-reply-bot` trong skill nếu bạn clone ở chỗ khác.

### Cách B: Routine trên Claude web (chạy 24/7, tắt máy vẫn chạy)

Lịch tối thiểu 1 giờ. Cloud không có file `.env` và file script của bạn nên:

1. Đặt các biến trong `.env.example` vào **biến môi trường** của môi trường cloud trên claude.ai.
2. Cho phép mạng tới `graph.facebook.com` và `slack.com`.
3. Đưa `comment_bot.py` vào routine: để repo này làm nguồn (GitHub) cho routine, hoặc dán nội dung script vào hướng dẫn và dặn Claude ghi ra file rồi chạy.
4. Dán `skill/SKILL.md` làm hướng dẫn, bỏ dòng nạp `.env`.

Lưu ý: token Meta và Slack nằm trong cấu hình môi trường cloud. Hãy chắc là tổ chức của bạn cho phép.

## Tùy chỉnh

- **Tài khoản và tên hiển thị:** đặt `ACCOUNT_NAME` và `ACCOUNT_NAME_PERSONAL` trong `.env`; ID và token Meta/Slack là các biến còn lại trong `.env.example`. Danh sách tài khoản nằm trong hàm `sources()` của `comment_bot.py`.
- **Giọng văn, quy tắc lọc spam, độ dài reply:** copy `rules.example.md` thành `rules.md` (đã nằm trong `.gitignore` nên quy tắc của bạn không bị đẩy lên GitHub) rồi chỉnh. `skill/SKILL.md` bảo Claude đọc `rules.md`.
- **Khoảng thời gian lấy comment:** biến `LOOKBACK_HOURS` (mặc định 24 giờ).
- **Nhịp gửi Slack:** biến `SLACK_PAUSE` (mặc định 4 giây giữa các comment).
- **Kênh Slack:** `SLACK_CHANNEL_ID`.

## Lưu ý và giới hạn

- Chỉ lấy comment trong `LOOKBACK_HOURS` giờ gần nhất và 15 bài gần nhất của Instagram, 10 bài gần nhất của Facebook.
- Comment spam (loại SKIP) không vào Slack nên được Claude xét lại ở các lần chạy sau trong khoảng thời gian lấy comment. Chi phí nhỏ.
- Slack giới hạn khoảng 1 tin/giây mỗi kênh; script nghỉ giữa các comment và tự thử lại khi bị giới hạn.
- Token Meta lấy từ Graph API Explorer hết hạn nhanh. Dùng token Page dài hạn hoặc System User token để chạy lâu dài.
- Reply nhân danh chuyên gia chỉ mang tính giáo dục, không tư vấn đầu tư cá nhân. Nên xem lại trước khi đăng.

## Xử lý lỗi thường gặp

| Hiện tượng | Nguyên nhân thường gặp |
|---|---|
| `fetch` báo `Meta HTTP 400 code=190` | Token hết hạn hoặc sai |
| `fetch` báo `code=100 ... nonexisting field` | ID Page/Instagram sai (ví dụ dùng ID Instagram làm Page ID) |
| `Slack ... not_in_channel` | Chưa mời bot vào kênh |
| `Slack ... missing_scope` | Thiếu `chat:write` hoặc `channels:history`; thêm quyền rồi *Reinstall to Workspace* |
| Không có tin nào trong Slack | Không có comment mới trong khoảng lấy comment, hoặc tất cả là spam |
