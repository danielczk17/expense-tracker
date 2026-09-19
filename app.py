import csv
import io
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime
from flask import Flask, jsonify, request, render_template, send_file

# Load .env so GEMINI_API_KEY can be set there instead of system environment
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PORT = int(os.environ.get("PORT", 5001))

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR   = os.path.join(BASE_DIR, "static")
DB_FILE      = os.path.join(BASE_DIR, "expenses.db")

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
_write_lock = threading.Lock()

DEFAULT_CATEGORIES = [
    "Food & Dining", "Transport", "Shopping", "Entertainment",
    "Health", "Fitness", "Utilities", "Housing", "Education", "Travel", "Subscriptions", "Other",
]


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id          TEXT PRIMARY KEY,
                date        TEXT NOT NULL,
                amount      REAL NOT NULL,
                category    TEXT NOT NULL,
                description TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                category      TEXT PRIMARY KEY,
                monthly_limit REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS merchant_rules (
                pattern  TEXT PRIMARY KEY,
                category TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                name     TEXT PRIMARY KEY,
                sort_order INTEGER NOT NULL DEFAULT 999
            )
        """)
        # Seed defaults only if table is empty
        existing = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        if existing == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO categories (name, sort_order) VALUES (?, ?)",
                [(name, i) for i, name in enumerate(DEFAULT_CATEGORIES)]
            )
        # Add bank column if it doesn't exist yet (migration for existing DBs)
        try:
            conn.execute("ALTER TABLE expenses ADD COLUMN bank TEXT DEFAULT ''")
        except Exception:
            pass  # column already exists
        # Add statement_id column if it doesn't exist yet (migration for existing DBs)
        try:
            conn.execute("ALTER TABLE expenses ADD COLUMN statement_id TEXT DEFAULT ''")
        except Exception:
            pass  # column already exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS statements (
                id                TEXT PRIMARY KEY,
                bank              TEXT DEFAULT '',
                filename          TEXT DEFAULT '',
                period            TEXT DEFAULT '',
                uploaded_at       TEXT NOT NULL,
                transaction_count INTEGER DEFAULT 0,
                total_amount      REAL DEFAULT 0
            )
        """)
        conn.commit()


init_db()


# ── Statement-parsing helpers ─────────────────────────────────────────────────

_MONTH_ABBR = {
    'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
    'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12,
}

_SKIP_PHRASES = [
    'payment received','payment due','thank you for payment',
    'minimum payment','balance b/f','balance c/f',
    'previous balance','opening balance','closing balance',
    'credit limit','available credit','finance charge',
    'late charge','late payment fee','annual fee',
    'bill payment','giro payment','inter-bank transfer',
    'fund transfer','paynow transfer','paynow to ','fast payment to ','bill pay',
    'interest charge','gst charged','brought forward',
    'carried forward','total amount due','amount due',
    'statement date','account number',
    # PayLah! / DBS wallet transfers (not real expenses)
    'top up wallet','send money to','receive money from',
    'ref no:',
    # Trust Bank / generic summary lines
    'total outstanding balance','outstanding balance',
]

_CATEGORY_KEYWORDS = {
    'Food & Dining': [
        # Fast food
        'mcdonald','kfc','subway','burger king','mos burger','popeyes',
        'pizza hut','domino','jollibee','long john','a&w','carl\'s jr',
        'fish & co','swensen','pepper lunch','ichiban','ootoya','waraku',
        'din tai fung','hai di lao','the soup spoon','eighteen chefs',
        'pastamania','saizeriya','yoshinoya','ajisen',
        # Coffee & beverages
        'starbucks','toast box','ya kun','coffee bean','the coffee',
        'gong cha','koi ','liho','playmade','tiger sugar','the alley',
        'heytea','nayuki','r&b tea','chatime','tealive','each a cup',
        'ding tea','machi machi','daboba',
        # Bakery & desserts
        'breadtalk','bengawan','prima deli','bread garden','four leaves',
        'old chang kee','polar puffs','lim chee guan','bee cheng hiang',
        # Delivery
        'foodpanda','deliveroo','grabfood','grab food','mcdelivery',
        'pandamart','grab mart',
        # Dining general
        'restaurant','cafe','kopitiam','hawker','bakery','food court',
        'food republic','food junction','koufu','banquet','foodclique',
        'select group','eatery','kitchen','bistro','catering',
        # Chinese
        'putien','crystal jade','paradise dynasty','paradise inn',
        'imperial treasure','tunglok','tung lok','man fu yuan',
        'canton paradise','dragon phoenix',
        # Japanese
        'sushi','ramen','udon','tonkatsu','yakiniku','sakae sushi',
        'sushiro','itacho','genki sushi',
        # Supermarkets / Grocery
        'fairprice','ntuc','giant','cold storage','sheng siong',
        'coldstorage','supermarket','grocery','don don donki',
        'redmart','prime supermarket','7-eleven','7eleven','cheers',
        'amazon fresh','marketplace by',
        # Local misc
        'chagee','twyst','kopi','tze char','zi char','cai png',
        'texas chicken','popeye','nando','mos food',
        'tori-q','tori q','wok','ding dong','maki-san','stuff\'d',
        'collin\'s','astons','bornga','korean bbq','japanese cuisine',
        # Generic food terms — catches "FOOD DYNASTY", "GOLDEN WOK", etc.
        'food','eatery','diner','grill','brasserie',
        # Others
        'noodle','bbq','steamboat','hot pot','dim sum','mala hotpot',
        'economy rice','chicken rice','mixed rice','laksa','wanton',
        'porridge','western food',
    ],
    'Transport': [
        'grab','gojek','comfortdelgro','comfort delgro','citycab',
        'trans-cab','transcab','tada','ryde','mvl','bluesg',
        'prime taxi','premier taxi','silver cab','london cab',
        'limousine','maxi cab','maxicab',
        'smrt','sbs transit','go-ahead','tower transit',
        'bus/mrt','bus','mrt','lrt','ez-link','nets flash','concession',
        'parking','carpark','car park','wilson parking',
        'esso','shell','caltex','sinopec','spc','petron',
        'petrol','diesel','fuel','erp',
        'hertz','avis','budget rent','car rental','shariot',
        'cycle & carriage','vicom','changi recommend',
    ],
    'Shopping': [
        # Online
        'lazada','shopee','amazon','taobao','qoo10','carousell',
        'zalora','asos','ezbuy','aliexpress','shein',
        # Electronics
        'challenger','harvey norman','best denki','courts','gain city',
        'sim lim','apple store',
        # Department / Fashion
        'isetan','metro','og ','bhg','robinsons','tangs','takashimaya',
        'marks & spencer','muji','uniqlo','zara','h&m','forever 21',
        'cotton on','bershka','pull & bear','mango','gap','levi',
        'tommy','polo ralph','calvin klein',
        # Footwear / Accessories
        'charles & keith','pedro','nine west','steve madden','aldo',
        'foot locker','new balance store','adidas store','nike store',
        # Home / Lifestyle
        'ikea','spotlight','home-fix','daiso','miniso','mr diy',
        # Books
        'popular','kinokuniya','typo',
        # Cosmetics
        'sephora','mac cosmetics','benefit','kiehl','laneige','innisfree',
        'watsons','guardian',
        # Other
        'mustafa',
    ],
    'Entertainment': [
        # Gaming
        'steam','playstation','xbox','nintendo','garena','razer gold',
        'google play','app store','roblox','riot games','epic games',
        'twitch',
        # Cinema / Shows
        'cathay','shaw','golden village','gv cinema','cinema',
        'sistic','ticketmaster','peatix',
        # Attractions
        'klook','kkday','universal studio','sentosa','zoo','bird park',
        'aquarium','science centre','sports hub',
        'bowling','arcade','karaoke','escape room','trampoline',
    ],
    'Subscriptions': [
        # Streaming
        'netflix','spotify','disney+','disneyplus','hbo','amazon prime',
        'youtube premium','crunchyroll','viu','iflix','tidal','apple tv',
        'apple music','deezer','paramount',
        # Software / Cloud
        'canva','figma','dropbox','icloud','google one','onedrive',
        'notion','zoom','microsoft 365','office 365','adobe',
        'github','jetbrains','1password','lastpass','dashlane',
        'grammarly','chatgpt','claude','openai',
        # Memberships
        'membership','subscription','annual fee','renewal',
    ],
    'Health': [
        # Hospitals
        'nuh ','national university hospital','sgh ','singapore general',
        'tan tock seng','ttsh','kkh ','kk hospital',
        'thomson medical','mount elizabeth','gleneagles','parkway',
        'mount alvernia','farrer park','columbia asia','raffles hospital',
        # Clinics
        'clinic','polyclinic','medical centre','healthway','ntuc health',
        'fullerton health','shenton medical','onecare','minmed',
        # Dental
        'dental','q&m','national dental','ndcs','pacific dental',
        'smilepoint','tooth club',
        # Pharmacy
        'unity pharmacy','guardian pharmacy','watsons health','pharmacy',
        # Allied health
        'physiotherapy','physio','chiropractor','tcm','acupuncture',
        # Optical
        'eyewear','optical','owndays','nanyang optical','spectacle hut',
    ],
    'Fitness': [
        # Gyms
        'gym','anytime fitness','pure fitness','virgin active','fitness first',
        'f45','barry\'s','crossfit','snap fitness','true fitness','planet fitness',
        # Classes / Studios
        'yoga','pilates','barre','spinning','cycling studio','muay thai',
        'bjj','boxing','martial arts','kickboxing','jiu jitsu',
        'dance studio','swim class','personal trainer',
        # Sports
        'badminton','tennis','squash','golf','bowling alley','sports complex',
        'activesg','safra','onepapa','hometeamns',
        # Nutrition
        'whey','protein','myprotein','gnc','supplement',
    ],
    'Utilities': [
        'singapore power','sp group','sp services','city gas',
        'pub ','utilities board',
        'senoko','tuas power','pacific light','sembcorp','union power',
        'keppel electric','geneco','iswitch','sunseap',
        'singtel','starhub','m1 ','circle life','giga','simba',
        'broadband','mobile plan','internet service','fibre',
        'myrepublic','viewqwest',
    ],
    'Housing': [
        'hdb ','town council','conservancy','property tax',
        'management fee','sinking fund','maintenance fee',
        'rent ','rental ','condo fee',
        'renovation','interior design',
        'aircon service','air-con service','pest control',
        'laundry','maid agency','domestic helper',
    ],
    'Education': [
        'nus ','ntu ','smu ','sutd ','sit ','sim ','kaplan','mdis',
        'temasek poly','ngee ann poly','singapore poly','republic poly',
        'nanyang poly','ite college',
        'tuition','enrichment','mindchamps','berries','learning lab',
        'newton learning','geniebook','snapask','kumon',
        'coursera','udemy','skillsfuture','linkedin learning',
        'masterclass','edx','datacamp',
        'british council','ielts','toefl','pearson vue',
    ],
    'Travel': [
        # Overseas spending (Amaze card routes foreign currency charges here)
        'amaze',
        # Airlines
        'singapore airlines','sia ','scoot','jetstar','air asia',
        'cathay pacific','emirates','qatar airways','british airways',
        'lufthansa','klm','thai airways','malaysia airlines',
        'batik air','lion air','vietjet','indigo air',
        # Booking
        'booking.com','agoda','airbnb','expedia','trip.com','trip com',
        'hotels.com','traveloka','ctrip','skyscanner','kayak',
        # Hotels
        'marriott','hilton','hyatt','sheraton','westin',
        'intercontinental','holiday inn','crowne plaza',
        'ibis','novotel','mercure',
        'mandarin oriental','raffles hotel','st regis','four seasons',
        'ritz-carlton','marina bay sands','hard rock hotel',
        # Travel services
        'changi airport','chan brothers','travel insurance',
        'allianz travel','axa travel','dfs','duty free',
    ],
}


# Pre-compile keyword patterns with word boundaries to prevent false matches
# e.g. 'gap' must not match 'singapore'
_CATEGORY_PATTERNS = {
    cat: [re.compile(r'\b' + re.escape(kw.strip()) + r'\b') for kw in kws]
    for cat, kws in _CATEGORY_KEYWORDS.items()
}

def _guess_category(description: str) -> str:
    d = description.lower()
    for cat, patterns in _CATEGORY_PATTERNS.items():
        for pat in patterns:
            if pat.search(d):
                return cat
    return 'Other'


def _ai_categorize_batch(descriptions: list) -> list:
    """Call Gemini to categorize a batch of descriptions that keywords couldn't classify.
    Returns a list of category strings in the same order as the input."""
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key or not descriptions:
        return ['Other'] * len(descriptions)
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = (
            "You are categorizing Singapore credit card transactions.\n\n"
            f"Categories (pick exactly one per transaction): {', '.join(DEFAULT_CATEGORIES)}\n\n"
            "Rules:\n"
            "- BUS/MRT, Grab, taxi, ERP, petrol → Transport\n"
            "- Restaurants, cafes, food courts, grocery, delivery → Food & Dining\n"
            "- Flights, hotels, booking platforms → Travel\n"
            "- Games, cinemas, attractions → Entertainment\n"
            "- Netflix, Spotify, Adobe, iCloud, SaaS, memberships → Subscriptions\n"
            "- Hospitals, clinics, pharmacy, dental, physiotherapy → Health\n"
            "- Gym, yoga, pilates, sports, protein supplements → Fitness\n"
            "- Telco, electricity, gas, internet → Utilities\n"
            "- Online shopping, retail, department stores → Shopping\n"
            "- School fees, courses, tuition → Education\n"
            "- Rent, condo, renovation → Housing\n"
            "- Anything unclear → Other\n\n"
            "Transaction descriptions (one per line):\n"
            + "\n".join(f"{i+1}. {d}" for i, d in enumerate(descriptions))
            + "\n\nRespond with a JSON array of category strings only, "
            "same count and order as the input. Example: [\"Transport\", \"Food & Dining\"]"
        )
        response = client.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=prompt,
        )
        text = response.text.strip()
        # Strip markdown code fences if present
        if text.startswith('```'):
            text = re.sub(r'^```[^\n]*\n', '', text)
            text = re.sub(r'\n```$', '', text.strip())
        result = json.loads(text)
        if not isinstance(result, list) or len(result) != len(descriptions):
            return ['Other'] * len(descriptions)
        return [r if r in DEFAULT_CATEGORIES else 'Other' for r in result]
    except Exception as e:
        app.logger.warning(f"Gemini categorization failed: {e}")
        return ['Other'] * len(descriptions)


def _detect_statement_year(lines: list) -> int:
    """Detect the statement year from the due date or statement date printed on the bill."""
    # Look for labeled date fields that carry the authoritative year
    _DATE_LABEL_RE = re.compile(
        r'(?:payment\s*due\s*date|due\s*date|statement\s*date|bill\s*date|as\s+of)'
        r'.{0,30}?\b(20\d{2})\b',
        re.IGNORECASE,
    )
    current_year = datetime.now().year
    for line in lines:
        m = _DATE_LABEL_RE.search(line)
        if m:
            return int(m.group(1))
    # Fallback: use current year if no labeled date found
    return current_year


def _clamp_year(year: int, ref_year: int, month: int = 0) -> int:
    """Replace years that don't match the statement period with the statement year.
    Only allows ±1 for Dec/Jan cross-year boundaries; all other months are forced
    to ref_year so 2-digit years like '25' in an Aug 2026 statement don't misparse."""
    if year == ref_year:
        return year
    if abs(year - ref_year) == 1 and month in (1, 12):
        return year
    return ref_year


def _parse_date_raw(raw: str, ref_year: int):
    raw = raw.strip()
    # Citibank format: DDMMm no space e.g. "19JUN", "04JUL"
    m = re.match(r'^(\d{1,2})(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$', raw, re.IGNORECASE)
    if m:
        month = _MONTH_ABBR.get(m.group(2)[:3].lower())
        if month:
            try:
                return datetime(ref_year, month, int(m.group(1))).strftime('%Y-%m-%d')
            except ValueError:
                pass
    m = re.match(r'(\d{1,2})\s+([A-Za-z]{3})\w*(?:\s+(\d{2,4}))?$', raw)
    if m:
        d, mo, yr = m.group(1), m.group(2), m.group(3)
        month = _MONTH_ABBR.get(mo[:3].lower())
        if month:
            year = ref_year if not yr else (int(yr) + 2000 if int(yr) < 100 else int(yr))
            year = _clamp_year(year, ref_year, month)
            try:
                return datetime(year, month, int(d)).strftime('%Y-%m-%d')
            except ValueError:
                pass
    m = re.match(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$', raw)
    if m:
        d, mo, yr = m.groups()
        yr = int(yr); yr = yr + 2000 if yr < 100 else yr
        yr = _clamp_year(yr, ref_year, int(mo))
        try:
            return datetime(yr, int(mo), int(d)).strftime('%Y-%m-%d')
        except ValueError:
            pass
    m = re.match(r'(\d{1,2})/(\d{1,2})$', raw)
    if m:
        mo, d = m.groups()
        try:
            return datetime(ref_year, int(mo), int(d)).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return None


_DATE_PART = (
    r'(?:\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w{0,6}(?:\s+\d{2,4})?'
    r'|\d{1,2}(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'  # Citibank: 19JUN
    r'|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}'
    r'|\d{1,2}/\d{1,2})'
)
_DEBIT_CREDIT_SUFFIX = r'(?:CR|DB|Dr|Cr|DB\.)?\s*'
_LINE_RE = re.compile(
    r'^(' + _DATE_PART + r')\s+(.+?)\s+([\d,]+\.\d{2})\s*' + _DEBIT_CREDIT_SUFFIX + r'$',
    re.IGNORECASE,
)
# DBS/POSB savings: date  description  withdrawal  [deposit]  balance
_LINE_RE_WITH_BALANCE = re.compile(
    r'^(' + _DATE_PART + r')\s+(.+?)\s+([\d,]+\.\d{2})\s+[\d,]+\.\d{2}\s*$',
    re.IGNORECASE,
)
# Two-date format (Trust/DBS credit card): PostDate  TransDate  description  amount
# Capture the SECOND date (transaction date) as group 1.
_LINE_RE_TWO_DATES = re.compile(
    r'^' + _DATE_PART + r'\s+(' + _DATE_PART + r')\s+(.+?)\s+([\d,]+\.\d{2})\s*' + _DEBIT_CREDIT_SUFFIX + r'$',
    re.IGNORECASE,
)


def _apply_merchant_rules(transactions: list) -> list:
    with get_db() as conn:
        rules = conn.execute("SELECT pattern, category FROM merchant_rules").fetchall()
    rules_list = [(r["pattern"], r["category"]) for r in rules]
    if not rules_list:
        return transactions
    for txn in transactions:
        d = txn["description"].lower()
        matched = next((cat for pat, cat in rules_list if pat == d), None)
        if not matched:
            matched = next((cat for pat, cat in rules_list if pat in d), None)
        if matched:
            txn["category"] = matched
    return transactions


def _detect_bank(lines: list) -> str:
    text = ' '.join(lines[:40]).lower()
    if 'citibank' in text or 'citi bank' in text:
        return 'Citibank'
    if 'uob' in text or 'united overseas bank' in text:
        return 'UOB'
    if 'trust bank' in text or ('trust' in text and 'bank' in text):
        return 'Trust'
    if 'dbs' in text or 'posb' in text:
        return 'DBS/POSB'
    if 'ocbc' in text:
        return 'OCBC'
    if 'standard chartered' in text or 'stanchart' in text:
        return 'Standard Chartered'
    if 'hsbc' in text:
        return 'HSBC'
    if 'maybank' in text:
        return 'Maybank'
    if 'american express' in text or 'amex' in text:
        return 'Amex'
    return ''


def parse_pdf_statement(pdf_bytes: bytes) -> list:
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError(
            "pdfplumber is not installed — restart the server after running: "
            "pip install pdfplumber"
        )
    all_lines = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            all_lines.extend(text.splitlines())

    if not any(ln.strip() for ln in all_lines):
        raise RuntimeError(
            "No text could be extracted — this may be a scanned PDF. "
            "Try downloading a CSV from your bank's internet banking portal instead."
        )

    ref_year = _detect_statement_year(all_lines)
    bank     = _detect_bank(all_lines)

    _has_date   = re.compile(r'^\s*' + _DATE_PART, re.IGNORECASE)
    _has_amount = re.compile(r'[\d,]+\.\d{2}')
    # Pre-processing pass: handle multi-line transaction formats.
    # Trust Bank places the merchant name on the line BEFORE the date+amount line.
    # Pattern: [desc-only line] → [date + amount, no description] → [optional city line]
    # Strategy: when a date+amount line has nothing between the last date and the amount,
    # look back at the previous non-empty line for the description.
    processed = []
    for raw_ln in all_lines:
        ln = raw_ln.strip()
        if not ln:
            processed.append(ln)
            continue
        # Detect "date(s) then immediately amount" — no merchant description
        m_bare = re.match(
            r'^(' + _DATE_PART + r'(?:\s+' + _DATE_PART + r')?)\s+([\d,]+\.\d{2}\s*(?:CR|DB|Dr|Cr)?\s*)$',
            ln, re.IGNORECASE
        )
        if m_bare:
            # Find the last non-empty preceding line as the description
            for prev in reversed(processed):
                if prev.strip() and not _has_date.match(prev) and not _has_amount.search(prev):
                    desc_part = prev.strip()
                    processed.append(m_bare.group(1) + ' ' + desc_part + ' ' + m_bare.group(2))
                    break
            else:
                processed.append(ln)
            continue
        processed.append(ln)
    all_lines = processed
    results  = []
    for line in all_lines:
        line = line.strip()
        if len(line) < 10:
            continue
        m = _LINE_RE.match(line)
        if m:
            date_raw, desc, amount_raw = m.group(1).strip(), m.group(2).strip(), m.group(3)
        else:
            # Try two-date format (DBS credit card: PostDate TransDate description amount)
            m2 = _LINE_RE_TWO_DATES.match(line)
            if m2:
                date_raw, desc, amount_raw = m2.group(1).strip(), m2.group(2).strip(), m2.group(3)
            else:
                # Try balance-column format (DBS/POSB savings: date desc amount balance)
                m3 = _LINE_RE_WITH_BALANCE.match(line)
                if not m3:
                    continue
                date_raw, desc, amount_raw = m3.group(1).strip(), m3.group(2).strip(), m3.group(3)
        # Strip any leading residual date token from description (two-date lines)
        desc = re.sub(r'^\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s*', '', desc, flags=re.IGNORECASE).strip()
        # Strip leading standalone month name (Trust Bank column layout bleeds month into desc)
        desc = re.sub(r'^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+', '', desc, flags=re.IGNORECASE).strip()
        # Strip trailing payment-channel tags Trust Bank appends (e.g. "TOWKAY KIA KOPI PTE LTD PAYNOW")
        desc = re.sub(r'\s+PAYNOW\s*$', '', desc, flags=re.IGNORECASE).strip()
        # Skip if description is nothing but a month name after cleanup
        if re.fullmatch(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*', desc, re.IGNORECASE):
            continue
        # Skip credits: CR can appear as "1,234.56 CR" or "1,234.56CR" (no word boundary)
        if re.search(r'CR\s*$', line, re.IGNORECASE):
            continue
        dl = desc.lower()
        if any(ph in dl for ph in _SKIP_PHRASES):
            continue
        if len(desc) < 3:
            continue
        amount = round(float(amount_raw.replace(',', '')), 2)
        if amount <= 0 or amount > 50_000:
            continue
        date_str = _parse_date_raw(date_raw, ref_year)
        if not date_str:
            continue
        results.append({
            'date':        date_str,
            'amount':      amount,
            'description': desc,
            'category':    _guess_category(desc),
            'bank':        bank,
        })

    # Upgrade uncategorized items using Gemini in a single batch call
    other_indices = [i for i, r in enumerate(results) if r['category'] == 'Other']
    if other_indices:
        ai_cats = _ai_categorize_batch([results[i]['description'] for i in other_indices])
        for i, cat in zip(other_indices, ai_cats):
            results[i]['category'] = cat

    return results, all_lines


@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

@app.route("/api/expenses")
def api_get_expenses():
    month = request.args.get("month")
    with get_db() as conn:
        if month:
            rows = conn.execute(
                "SELECT * FROM expenses WHERE date LIKE ? ORDER BY date DESC, rowid DESC",
                (f"{month}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM expenses ORDER BY date DESC, rowid DESC"
            ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/expense", methods=["POST"])
def api_add_expense():
    data = request.get_json(force=True) or {}
    for field in ("date", "amount", "category"):
        if not str(data.get(field, "")).strip():
            return jsonify({"error": f"Missing field: {field}"}), 400
    try:
        amount = float(data["amount"])
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Amount must be a positive number"}), 400

    expense = {
        "id":          str(uuid.uuid4()),
        "date":        str(data["date"]).strip(),
        "amount":      amount,
        "category":    str(data["category"]).strip(),
        "description": str(data.get("description") or "").strip(),
        "bank":        str(data.get("bank") or "").strip(),
    }
    with _write_lock:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO expenses VALUES (:id, :date, :amount, :category, :description, :bank)",
                expense,
            )
            conn.commit()
    return jsonify({"success": True, "expense": expense}), 201


@app.route("/api/expense/<string:record_id>", methods=["PUT"])
def api_update_expense(record_id):
    data = request.get_json(force=True) or {}
    for field in ("date", "amount", "category"):
        if not str(data.get(field, "")).strip():
            return jsonify({"error": f"Missing field: {field}"}), 400
    try:
        amount = float(data["amount"])
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Amount must be a positive number"}), 400

    with _write_lock:
        with get_db() as conn:
            result = conn.execute(
                "UPDATE expenses SET date=?, amount=?, category=?, description=?, bank=? WHERE id=?",
                (str(data["date"]).strip(), amount,
                 str(data["category"]).strip(),
                 str(data.get("description") or "").strip(),
                 str(data.get("bank") or "").strip(),
                 record_id),
            )
            if result.rowcount == 0:
                return jsonify({"error": "Record not found"}), 404
            conn.commit()
    return jsonify({"success": True})


@app.route("/api/expense/<string:record_id>", methods=["DELETE"])
def api_delete_expense(record_id):
    with _write_lock:
        with get_db() as conn:
            result = conn.execute("DELETE FROM expenses WHERE id=?", (record_id,))
            if result.rowcount == 0:
                return jsonify({"error": "Record not found"}), 404
            conn.commit()
    return jsonify({"success": True})


@app.route("/api/expenses/all", methods=["DELETE"])
def api_delete_all_expenses():
    with _write_lock:
        with get_db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
            conn.execute("DELETE FROM expenses")
            conn.execute("DELETE FROM statements")
            conn.commit()
    return jsonify({"deleted": count})


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

@app.route("/api/budgets")
def api_get_budgets():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM budgets ORDER BY category").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/budget", methods=["PUT"])
def api_set_budget():
    data     = request.get_json(force=True) or {}
    category = str(data.get("category", "")).strip()
    limit_raw = data.get("monthly_limit")
    if not category or limit_raw is None:
        return jsonify({"error": "category and monthly_limit required"}), 400
    try:
        limit = float(limit_raw)
        if limit < 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "monthly_limit must be a non-negative number"}), 400
    with _write_lock:
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO budgets VALUES (?, ?)", (category, limit)
            )
            conn.commit()
    return jsonify({"success": True})


@app.route("/api/budget/<path:category>", methods=["DELETE"])
def api_delete_budget(category):
    with _write_lock:
        with get_db() as conn:
            conn.execute("DELETE FROM budgets WHERE category=?", (category,))
            conn.commit()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

@app.route("/api/category-trend")
def api_category_trend():
    """Monthly totals for one category over the N months ending at `end` (zero-filled)."""
    category = request.args.get("category", "")
    end      = request.args.get("end", datetime.now().strftime("%Y-%m"))
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", end):
        return jsonify({"error": "end must be YYYY-MM"}), 400
    try:
        n = max(1, min(24, int(request.args.get("months", 6))))
    except ValueError:
        n = 6

    y, m = int(end[:4]), int(end[5:7])
    months = []
    for i in range(n - 1, -1, -1):
        idx = y * 12 + (m - 1) - i
        months.append(f"{idx // 12}-{idx % 12 + 1:02d}")

    with get_db() as conn:
        rows = conn.execute(
            """SELECT substr(date,1,7) AS month, SUM(amount) AS total, COUNT(*) AS count
               FROM expenses
               WHERE category = ? AND substr(date,1,7) BETWEEN ? AND ?
               GROUP BY month""",
            (category, months[0], months[-1]),
        ).fetchall()
    found = {r["month"]: r for r in rows}
    return jsonify({
        "category": category,
        "months": [
            {"month": mo,
             "total": round(found[mo]["total"], 2) if mo in found else 0,
             "count": found[mo]["count"] if mo in found else 0}
            for mo in months
        ],
    })


@app.route("/api/summary")
def api_summary():
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    with get_db() as conn:
        by_category = conn.execute(
            """SELECT category, SUM(amount) AS total, COUNT(*) AS count
               FROM expenses WHERE date LIKE ? GROUP BY category ORDER BY total DESC""",
            (f"{month}%",),
        ).fetchall()

        monthly = conn.execute(
            """SELECT substr(date,1,7) AS month, SUM(amount) AS total
               FROM expenses GROUP BY month ORDER BY month ASC"""
        ).fetchall()

        month_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE date LIKE ?",
            (f"{month}%",),
        ).fetchone()

        # Baseline for "biggest mover": each category's average over up to 3 earlier months
        # that have data (same window as the Average Month tile).
        prior_months = [r["m"] for r in conn.execute(
            """SELECT DISTINCT substr(date,1,7) AS m FROM expenses
               WHERE substr(date,1,7) < ? ORDER BY m DESC LIMIT 3""", (month,)
        ).fetchall()]
        category_avg = []
        if prior_months:
            marks = ",".join("?" * len(prior_months))
            category_avg = [
                {"category": r["category"], "avg": r["total"] / len(prior_months)}
                for r in conn.execute(
                    f"""SELECT category, SUM(amount) AS total FROM expenses
                        WHERE substr(date,1,7) IN ({marks}) GROUP BY category""", prior_months
                ).fetchall()
            ]

        largest_expense = conn.execute(
            """SELECT date, description, category, amount FROM expenses
               WHERE date LIKE ? ORDER BY amount DESC, date DESC LIMIT 1""",
            (f"{month}%",),
        ).fetchone()

        by_bank = conn.execute(
            """SELECT COALESCE(NULLIF(TRIM(bank),''), 'Untagged') AS bank,
                      SUM(amount) AS total
               FROM expenses WHERE date LIKE ?
               GROUP BY bank ORDER BY total DESC""",
            (f"{month}%",),
        ).fetchall()

        budgets = conn.execute("SELECT * FROM budgets").fetchall()

    budgets_dict  = {b["category"]: b["monthly_limit"] for b in budgets}
    by_cat_list   = [dict(r) for r in by_category]
    for item in by_cat_list:
        item["budget"] = budgets_dict.get(item["category"])

    total_budget = sum(budgets_dict.values()) if budgets_dict else None

    return jsonify({
        "month":          month,
        "total":          month_total["total"],
        "category_avg":     category_avg,
        "avg_months":       len(prior_months),
        "largest_expense":  dict(largest_expense) if largest_expense else None,
        "total_budget":   total_budget,
        "by_category":      by_cat_list,
        "by_bank":          [dict(r) for r in by_bank],
        "monthly_totals": [dict(r) for r in monthly],
        "budgets":        budgets_dict,
    })


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@app.route("/api/categories", methods=["GET"])
def api_categories():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT name FROM categories ORDER BY sort_order, name"
        ).fetchall()
    return jsonify([r["name"] for r in rows])


@app.route("/api/categories", methods=["POST"])
def api_add_category():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Category name is required"}), 400
    with get_db() as conn:
        existing = conn.execute(
            "SELECT COUNT(*) FROM categories WHERE LOWER(name)=LOWER(?)", (name,)
        ).fetchone()[0]
        if existing:
            return jsonify({"error": "Category already exists"}), 409
        max_order = conn.execute("SELECT MAX(sort_order) FROM categories").fetchone()[0] or 0
        conn.execute(
            "INSERT INTO categories (name, sort_order) VALUES (?, ?)", (name, max_order + 1)
        )
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/categories/<name>", methods=["DELETE"])
def api_delete_category(name):
    with get_db() as conn:
        conn.execute("DELETE FROM categories WHERE name=?", (name,))
        conn.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------

@app.route("/api/export")
def api_export():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT date, amount, category, description FROM expenses ORDER BY date DESC, rowid DESC"
        ).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Amount", "Category", "Description"])
    for row in rows:
        writer.writerow([row["date"], row["amount"], row["category"], row["description"]])
    output   = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    filename = f"expenses_{datetime.now().strftime('%Y%m%d')}.csv"
    return send_file(output, mimetype="text/csv", as_attachment=True, download_name=filename)


@app.route("/api/import", methods=["POST"])
def api_import():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith(".csv"):
        return jsonify({"error": "File must be a .csv"}), 400
    try:
        content = f.read().decode("utf-8-sig")
    except Exception:
        return jsonify({"error": "Could not read file — ensure it is UTF-8 encoded"}), 400

    reader = csv.DictReader(io.StringIO(content))
    added  = 0
    errors = []

    def _get(row, *keys):
        for k in keys:
            for rk in row:
                if rk.strip().lower() == k.lower():
                    return str(row[rk]).strip()
        return ""

    with _write_lock:
        with get_db() as conn:
            for row_idx, row in enumerate(reader, start=2):
                try:
                    date_str    = _get(row, "date")
                    amount_str  = _get(row, "amount")
                    category    = _get(row, "category")
                    description = _get(row, "description", "notes")
                    if not date_str and not amount_str and not category:
                        continue
                    if not date_str:
                        raise ValueError("Date is required")
                    if not category:
                        raise ValueError("Category is required")
                    datetime.strptime(date_str, "%Y-%m-%d")
                    amount = float(amount_str)
                    if amount <= 0:
                        raise ValueError("Amount must be greater than 0")
                    conn.execute(
                        "INSERT INTO expenses VALUES (?,?,?,?,?)",
                        (str(uuid.uuid4()), date_str, amount, category, description),
                    )
                    added += 1
                except Exception as e:
                    errors.append(f"Row {row_idx}: {e}")
            conn.commit()

    return jsonify({"added": added, "errors": errors})


# ---------------------------------------------------------------------------
# Merchant rules
# ---------------------------------------------------------------------------

@app.route("/api/merchant-rules")
def api_get_merchant_rules():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM merchant_rules ORDER BY pattern").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/merchant-rule", methods=["POST"])
def api_set_merchant_rule():
    data     = request.get_json(force=True) or {}
    pattern  = str(data.get("pattern", "")).strip().lower()
    category = str(data.get("category", "")).strip()
    if not pattern or not category:
        return jsonify({"error": "pattern and category required"}), 400
    with _write_lock:
        with get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO merchant_rules VALUES (?,?)", (pattern, category))
            conn.commit()
    return jsonify({"success": True})


@app.route("/api/merchant-rule/<path:pattern>", methods=["DELETE"])
def api_delete_merchant_rule(pattern):
    with _write_lock:
        with get_db() as conn:
            conn.execute("DELETE FROM merchant_rules WHERE pattern=?", (pattern,))
            conn.commit()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Statement parsing
# ---------------------------------------------------------------------------

def _flag_duplicates(txns: list) -> dict:
    """Mark parsed transactions that already exist in the expenses table (txn["duplicate"]).

    Matching is one-to-one, so two identical charges on a day only match two saved
    rows. First try date + amount + description; fall back to date + description so a
    row whose amount was edited during the first import is still recognised.
    Returns a summary of what matched and which saved statements it came from."""
    for t in txns:
        t["duplicate"] = False
    summary = {"count": 0, "total": len(txns), "statements": [], "manual": 0}
    if not txns:
        return summary

    norm = lambda d: re.sub(r"\s+", " ", (d or "").strip().lower())
    dates = [t["date"] for t in txns]
    with get_db() as conn:
        rows = conn.execute(
            "SELECT date, amount, description, statement_id FROM expenses WHERE date BETWEEN ? AND ?",
            (min(dates), max(dates)),
        ).fetchall()

        exact, loose = {}, {}
        for r in rows:
            entry = {"sid": r["statement_id"] or "", "used": False}
            exact.setdefault((r["date"], round(r["amount"], 2), norm(r["description"])), []).append(entry)
            loose.setdefault((r["date"], norm(r["description"])), []).append(entry)

        # Two passes so a loose (edited-amount) match can never steal a saved row that
        # another uploaded transaction matches exactly.
        sids = []
        def claim(t, pool):
            match = next((e for e in pool if not e["used"]), None)
            if match:
                match["used"] = True
                t["duplicate"] = True
                sids.append(match["sid"])

        for t in txns:
            claim(t, exact.get((t["date"], round(t["amount"], 2), norm(t["description"])), []))
        for t in txns:
            if not t["duplicate"]:
                claim(t, loose.get((t["date"], norm(t["description"])), []))

        summary["count"]  = len(sids)
        summary["manual"] = sum(1 for x in sids if not x)   # matched hand-entered / CSV rows
        found = sorted({x for x in sids if x})
        if found:
            marks = ",".join("?" * len(found))
            summary["statements"] = [dict(r) for r in conn.execute(
                f"SELECT * FROM statements WHERE id IN ({marks}) ORDER BY uploaded_at DESC", found
            ).fetchall()]
    return summary


@app.route("/api/parse-statement", methods=["POST"])
def api_parse_statement():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400
    try:
        pdf_bytes = f.read()
        txns, raw_lines = parse_pdf_statement(pdf_bytes)
        txns = _apply_merchant_rules(txns)
        duplicates = _flag_duplicates(txns)
        resp = {"transactions": txns, "duplicates": duplicates, "raw_sample": raw_lines[:80]}
        return jsonify(resp)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception as exc:
        return jsonify({"error": f"Could not parse PDF: {exc}"}), 500


@app.route("/api/statements", methods=["GET"])
def api_list_statements():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM statements ORDER BY uploaded_at DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/save-statement", methods=["POST"])
def api_save_statement():
    data = request.get_json(force=True) or {}
    rows     = data.get("rows", [])
    bank     = str(data.get("bank") or "").strip()
    filename = str(data.get("filename") or "").strip()

    if not rows:
        return jsonify({"error": "No rows to save"}), 400

    expenses = []
    for row in rows:
        try:
            amount = round(float(row["amount"]), 2)
            if amount <= 0:
                continue
        except (ValueError, TypeError):
            continue
        if not row.get("date"):
            continue
        expenses.append({
            "id":           str(uuid.uuid4()),
            "date":         str(row["date"]).strip(),
            "amount":       amount,
            "category":     str(row.get("category") or "Other").strip(),
            "description":  str(row.get("description") or "").strip(),
            "bank":         bank,
            "statement_id": "",  # filled in below once stmt_id is known
        })

    if not expenses:
        return jsonify({"error": "No valid rows"}), 400

    # Derive period from date range of transactions
    dates = sorted(e["date"] for e in expenses)
    def _fmt_period(d):
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            return dt.strftime("%b %Y")
        except ValueError:
            return d
    period = _fmt_period(dates[0]) if dates[0][:7] == dates[-1][:7] else \
             f"{_fmt_period(dates[0])} – {_fmt_period(dates[-1])}"

    stmt_id = str(uuid.uuid4())
    for e in expenses:
        e["statement_id"] = stmt_id
    with _write_lock:
        with get_db() as conn:
            conn.executemany(
                "INSERT INTO expenses VALUES (:id,:date,:amount,:category,:description,:bank,:statement_id)",
                expenses,
            )
            conn.execute(
                "INSERT INTO statements VALUES (?,?,?,?,?,?,?)",
                (stmt_id, bank, filename, period,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 len(expenses),
                 round(sum(e["amount"] for e in expenses), 2)),
            )
            conn.commit()

    return jsonify({"saved": len(expenses), "statement_id": stmt_id})


@app.route("/api/statements/<string:stmt_id>", methods=["DELETE"])
def api_delete_statement(stmt_id):
    with _write_lock:
        with get_db() as conn:
            result = conn.execute("DELETE FROM statements WHERE id=?", (stmt_id,))
            if result.rowcount == 0:
                return jsonify({"error": "Statement not found"}), 404
            deleted = conn.execute(
                "DELETE FROM expenses WHERE statement_id=?", (stmt_id,)
            ).rowcount
            conn.commit()
    return jsonify({"deleted_expenses": deleted})


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=PORT)
