# Minute.ly -- LinkedIn Outreach Automation

Automated LinkedIn outreach tool for **Minute.ly**, a video AI company helping broadcasters and media companies monetize vertical video.

The tool reads prospect LinkedIn profiles from a CSV, uses **Google Gemini AI** to classify them by industry (Sports / News / Entertainment), and executes a personalized multi-step outreach sequence.

---

## Safety Features

| Feature | Detail |
|---|---|
| **Daily Limit** | Hard cap of **20 leads per run**. Stops automatically. |
| **Human-Like Delays** | Random **60-120 second** pause between every single action. |
| **CAPTCHA Detection** | If LinkedIn shows a security challenge, the script aborts immediately. |
| **Crash Recovery** | CSV is saved after every action -- at most 1 action lost on crash. |
| **Anti-Detection** | Headed browser, realistic user agent, webdriver flag masking. |
| **Audit Trail** | Every action logged to console + daily log file in `logs/`. |

---

## Outreach Flow

```
1. New Lead       --> Send connection request (with personalized industry note)
2. ConnectionSent --> Wait for acceptance (checked on next run)
3. Connected      --> After 2+ hours, send Message 1 (Video Hook)
4. Message1Sent   --> After 3+ days with no reply, send Message 2 (Gentle Nudge)
5. Replied        --> Flagged for manual follow-up
```

Messages are automatically personalized based on Gemini AI classification:
- **Sports** -- focuses on verticalizing sports highlights for better yield
- **News** -- focuses on automating vertical video for breaking news
- **Entertainment** -- focuses on boosting engagement with vertical content

---

## Prerequisites

- **Python 3.10+** (tested with 3.12)
- **Google Gemini API key** (free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey))
- **LinkedIn account**

---

## Setup Instructions

### Step 1: Clone the repo

```bash
git clone https://github.com/raniop/Minute.ly.git
cd Minute.ly
```

### Step 2: Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Install the browser engine

Playwright needs its own Chromium browser:

```bash
playwright install chromium
```

> On Linux you may also need: `playwright install-deps chromium`

### Step 4: Configure your Gemini API key

Copy the example environment file and add your key:

```bash
# Windows
copy .env.example .env

# Mac/Linux
cp .env.example .env
```

Open `.env` in any text editor and replace the placeholder:

```
GEMINI_API_KEY=your_actual_gemini_api_key_here
```

### Step 5: Add your leads

Edit `leads.csv` with your prospect data:

```csv
Profile_URL,Name,Status,Last_Contact_Date,Industry,Company
https://www.linkedin.com/in/john-doe/,John,New,,,
https://www.linkedin.com/in/jane-smith/,Jane,New,,,
```

**Required columns:**
| Column | Description |
|---|---|
| `Profile_URL` | Full LinkedIn profile URL |
| `Name` | First name (used in message personalization) |
| `Status` | Set to `New` for fresh leads |
| `Last_Contact_Date` | Leave empty for new leads |
| `Industry` | Leave empty -- filled automatically by Gemini AI |
| `Company` | Leave empty -- scraped automatically from profile |

---

## Running the Tool

```bash
python main.py
```

### First Run (Manual Login)

1. The script opens a Chromium browser window
2. Navigate to LinkedIn and **log in manually** (including 2FA if prompted)
3. Return to the terminal and **press ENTER**
4. Your session cookies are saved to `cookies/linkedin_cookies.json`

### Subsequent Runs

Cookies are loaded automatically -- no login needed (cookies last 1-3 months).

### What Happens During a Run

```
============================================================
  Minute.ly Outreach -- LinkedIn Automation Tool
============================================================
  Daily limit:  20 leads per run
  Delay range:  60-120 seconds between actions
  Input file:   leads.csv
============================================================

2026-02-17 13:18:50 | INFO     | Processing: John | Status: New | URL: https://...
2026-02-17 13:18:50 | INFO     | Safety delay: waiting 87 seconds...
2026-02-17 13:20:17 | INFO     | Gemini classified John as: Sports
2026-02-17 13:20:20 | INFO     | Action 1/20: Connection request sent to John (Sports)
...
2026-02-17 14:05:30 | INFO     | Daily safety limit reached. Stopping.
```

---

## Project Structure

```
Minute.ly/
├── main.py              # Complete application (all logic in one file)
├── requirements.txt     # Python dependencies
├── .env.example         # Template for API key (commit-safe)
├── .env                 # Your actual API key (git-ignored, never committed)
├── leads.csv            # Your prospect data
├── .gitignore           # Protects sensitive files from being committed
├── cookies/             # Auto-created: saved LinkedIn session (git-ignored)
│   └── linkedin_cookies.json
└── logs/                # Auto-created: daily log files (git-ignored)
    └── outreach_2026-02-17.log
```

---

## Customizing Message Templates

Demo link placeholders are defined at the top of `main.py`:

```python
SPORTS_DEMO_LINK = "[SPORTS_DEMO_LINK]"
NEWS_DEMO_LINK = "[NEWS_DEMO_LINK]"
```

Replace these with your actual demo URLs before running.

To modify message templates, edit the `build_connection_note()`, `build_message_1()`, and `build_message_2()` methods in the `OutreachOrchestrator` class.

---

## Adjusting Safety Limits

At the top of `main.py`:

```python
DAILY_LIMIT = 20    # Max leads per run (do NOT exceed 50)
MIN_DELAY = 60      # Minimum seconds between actions
MAX_DELAY = 120     # Maximum seconds between actions
```

> **Warning:** Reducing delays or increasing the daily limit significantly raises the risk of LinkedIn account restrictions.

---

## Troubleshooting

| Issue | Solution |
|---|---|
| `GEMINI_API_KEY not found` | Make sure `.env` file exists with your key (copy from `.env.example`) |
| `playwright install chromium` fails | Try running as administrator, or check your internet connection |
| Browser won't open | Make sure you're running from a desktop terminal (not SSH/headless) |
| `Cookies expired` | The script will prompt for manual login again. This is normal every 1-3 months. |
| LinkedIn security challenge | Stop the script, resolve the challenge manually in a regular browser, wait 24h, then retry |
| CSV not updating | Check file permissions -- the script needs write access to `leads.csv` |

---

## Tech Stack

- **Python 3.12** -- core runtime
- **Playwright** -- browser automation (Chromium)
- **Google Gemini AI** (gemini-1.5-flash) -- prospect industry classification
- **python-dotenv** -- environment variable management

---

## License

Internal tool for Minute.ly. All rights reserved.
