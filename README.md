# Expense Tracker

A personal expense tracker built with Python + Flask and SQLite. Import bank and credit card statements from PDF, categorise spending automatically, and track it against monthly budgets.

## Features

- Dashboard with monthly spending, budget usage, top category and merchant, and trends
- Expenses list with sorting and editable categories
- Budget tab with per-category budgets
- PDF statement import (including Citibank and Trust Bank) with a statements history page
- Automatic categorisation with Singapore-specific keyword rules, merchant memory, and optional Gemini AI
- Configurable categories in Settings
- All data is stored locally in `expenses.db`

## Setup

Requires Python 3.10 or later.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5001. Set the `PORT` environment variable to use a different port.

## Gemini AI categorisation (optional)

The app can use Google Gemini to categorise transactions that the keyword rules can't classify.

**This is off by default.** Without an API key, the app still works, but categorisation uses the keyword rules only, and anything unmatched is labelled `Other`.

To turn it on, each user needs their own API key:

1. Get a free key at [Google AI Studio](https://aistudio.google.com/apikey).
2. Copy the template and add your key:

   ```bash
   cp .env.example .env
   ```

   Then edit `.env`:

   ```
   GEMINI_API_KEY=your_key_here
   ```

3. Restart the app.

### Keep your key private

- `.env` is listed in `.gitignore`, so it is never committed. Don't remove it from there.
- Never paste your key into the code, an issue, or a commit. A key pushed to a public repo can be found and abused within minutes, and stays in git history even after you delete it. If that happens, revoke the key in Google AI Studio and create a new one.
- Keys aren't shared between installs. Anyone who downloads this app from GitHub needs to add their own.

## Data and privacy

- Your expenses are stored locally in `expenses.db`, which is also git-ignored.
- When Gemini is enabled, transaction descriptions from imported statements are sent to Google's API for categorisation. Leave the key unset if you don't want that.
