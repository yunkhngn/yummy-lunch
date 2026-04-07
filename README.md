# Hôm nay ăn gì — Telegram bot

Bot gợi ý một món ăn theo thời tiết, vị trí trong `.env`, lịch sử tuần (Thứ 2–Thứ 6), kèm link Google Maps chỉ đường. Dùng Gemini và Open-Meteo (free, không cần API key thời tiết).

## API keys

| Dịch vụ | Đăng ký |
|--------|---------|
| Telegram | [@BotFather](https://t.me/BotFather) — `/newbot` |
| Gemini | [Google AI Studio](https://aistudio.google.com/apikey) |
| Geoapify (khuyến nghị) | [Geoapify](https://www.geoapify.com/) |

## Chạy local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Sửa .env: token, GEMINI key, GEOAPIFY key (khuyến nghị), địa chỉ, MY_LATITUDE, MY_LONGITUDE

python -m src.cli   # thử terminal
python -m src.bot   # chạy bot
```

## Deploy Docker (VPS)

```bash
cp .env.example .env && nano .env
docker compose up -d --build
docker compose logs -f bot
```

## Lệnh Telegram

| Lệnh | Mô tả |
|------|--------|
| `/start` | Hướng dẫn |
| `/eat` | Gợi ý (một món, có dấu tiếng Việt) |
| `/history` | Lịch sử tuần |
| `/reset` | Xóa lịch sử tuần |
