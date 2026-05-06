# TeraBox Video Downloader Bot — Complete Setup Guide

## What This Bot Does

- Accepts TeraBox video links from authorized users
- Shows video metadata (title, duration, thumbnail, size)
- Offers quality selection via inline keyboard buttons
- Offers subtitle language selection (if subtitles are available)
- Downloads the video and sends it back to the user in Telegram
- Shows live download progress with percentage and speed
- Cleans up temp files automatically
- Supports multiple users simultaneously (fully async)
- Includes a per-user download queue with cancel support

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| FFmpeg | Any recent version |
| pip | Latest |
| A Telegram Bot Token | From @BotFather |

---

## Step 1 — Get Your Bot Token

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Follow prompts, choose a name and username
4. Copy the token (looks like `123456789:ABCdef...`)

---

## Step 2 — Get Your Telegram User ID

1. Open Telegram and search for **@userinfobot**
2. Send `/start`
3. Copy the **Id** number shown (e.g., `987654321`)

---

## Step 3 — Install FFmpeg

### Ubuntu / Debian
```bash
sudo apt update && sudo apt install -y ffmpeg
```

### macOS
```bash
brew install ffmpeg
```

### Windows
Download from https://ffmpeg.org/download.html and add to PATH.

---

## Step 4 — Clone / Download the Bot

```bash
# If using git
git clone <your-repo-url> terabox-bot
cd terabox-bot

# Or simply unzip the downloaded folder
cd terabox-bot
```

---

## Step 5 — Create Virtual Environment & Install Dependencies

```bash
python -m venv venv

# Activate (Linux/macOS)
source venv/bin/activate

# Activate (Windows)
venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt
```

---

## Step 6 — Configure Environment Variables

```bash
cp .env.example .env
nano .env   # or use any text editor
```

Fill in at minimum:
```
BOT_TOKEN=YOUR_TOKEN_HERE
OWNER_ID=YOUR_USER_ID_HERE
```

To allow additional users:
```
ALLOWED_USERS=987654321,111222333,444555666
```

---

## Step 7 — Run the Bot Locally

```bash
python main.py
```

You should see:
```
2024-05-01 12:00:00 | INFO     | TeraBot | Bot starting — polling…
```

Send the bot a TeraBox link on Telegram to test it!

---

## Deployment Options

---

### Option A — VPS (Recommended for 24/7)

Any Ubuntu/Debian VPS (DigitalOcean, Linode, Hetzner, etc.)

#### With Docker (easiest):
```bash
# 1. Install Docker
curl -fsSL https://get.docker.com | sh

# 2. Clone/upload project to VPS
scp -r ./terabox-bot user@your-server:/home/user/

# 3. SSH into server
ssh user@your-server
cd terabox-bot

# 4. Create .env
cp .env.example .env && nano .env

# 5. Build & start (with auto-restart)
docker-compose up -d --build

# View logs
docker-compose logs -f
```

#### Without Docker (systemd service):
```bash
# 1. Install dependencies
sudo apt update && sudo apt install -y python3-pip python3-venv ffmpeg

# 2. Set up project
cd /home/user/terabox-bot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env

# 3. Create systemd service
sudo nano /etc/systemd/system/terabox-bot.service
```

Paste this (update paths as needed):
```ini
[Unit]
Description=TeraBox Telegram Bot
After=network.target

[Service]
Type=simple
User=your_linux_user
WorkingDirectory=/home/your_linux_user/terabox-bot
EnvironmentFile=/home/your_linux_user/terabox-bot/.env
ExecStart=/home/your_linux_user/terabox-bot/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable terabox-bot
sudo systemctl start terabox-bot
sudo systemctl status terabox-bot
```

---

### Option B — Railway

1. Go to https://railway.app and sign up
2. Click **New Project → Deploy from GitHub repo**
3. Connect your GitHub repo (push the bot files to GitHub first)
4. In Railway dashboard → **Variables**, add:
   - `BOT_TOKEN` = your token
   - `OWNER_ID` = your user ID
   - `ALLOWED_USERS` = comma-separated IDs
5. Railway auto-detects the `Procfile` and deploys
6. Go to **Deployments** tab to see logs

> ⚠️ Railway's free tier has a 500-hour/month limit. The $5/month Hobby plan is unlimited.

---

### Option C — Render

1. Go to https://render.com and sign up
2. Click **New → Web Service**
3. Connect your GitHub repo
4. Set:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
5. Under **Environment**, add your env vars
6. Click **Create Web Service**

> ⚠️ Render's free tier spins down after inactivity. Use the $7/month plan for always-on.

---

## Updating the Bot

```bash
# If running with Docker
git pull
docker-compose up -d --build

# If running with systemd
git pull
sudo systemctl restart terabox-bot
```

---

## Adding/Removing Authorized Users

Edit your `.env` file:
```
ALLOWED_USERS=987654321,111222333
```

Then restart the bot:
```bash
# Docker
docker-compose restart

# Systemd
sudo systemctl restart terabox-bot
```

---

## Log Files

| File | Contents |
|---|---|
| `logs/activity.log` | All info-level events (requests, downloads, completions) |
| `logs/error.log` | Errors and stack traces |

```bash
# Tail live logs
tail -f logs/activity.log
tail -f logs/error.log
```

---

## Directory Structure

```
terabox-bot/
├── main.py              # Entrypoint (loads .env, starts bot)
├── bot.py               # Telegram handlers, conversation flow
├── config.py            # All settings from environment variables
├── downloader.py        # yt-dlp wrapper (fetch info, download, subtitles)
├── queue_manager.py     # Per-user async download queue
├── utils.py             # Helpers (URL check, formatting, cleanup)
├── requirements.txt     # Python dependencies
├── .env.example         # Template for environment variables
├── Dockerfile           # Docker image definition
├── docker-compose.yml   # Docker Compose config (with auto-restart)
├── Procfile             # Railway / Render start command
├── downloads/           # Temp video files (auto-deleted after send)
├── cache/               # Cached video metadata (1-hour TTL)
└── logs/
    ├── activity.log
    └── error.log
```

---

## Telegram File Size Limits

| Bot API | Limit |
|---|---|
| Cloud Bot API (default) | **50 MB** upload |
| [Local Bot API Server](https://core.telegram.org/bots/api#using-a-local-bot-api-server) | **2 GB** upload |

If you need to send files larger than 50 MB, run a local Bot API server and set:
```
TELEGRAM_FILE_LIMIT=2147483648
```

---

## Troubleshooting

**"yt-dlp returned no info"**
→ The TeraBox link may be expired or private. Try a fresh link.

**"Download completed but output file not found"**
→ FFmpeg may not be installed. Run `ffmpeg -version` to check.

**Bot doesn't respond**
→ Check that `BOT_TOKEN` is correct and the bot isn't running elsewhere.

**"You are not authorized"**
→ Your user ID is not in `ALLOWED_USERS` or `OWNER_ID`. Add it and restart.

---

## Security Notes

- Never share your `.env` file or commit it to version control
- Add `.env` to `.gitignore`
- The bot only responds to user IDs in your `ALLOWED_USERS` list
- Rate limiting prevents abuse (default: 5 requests per 60 seconds per user)
