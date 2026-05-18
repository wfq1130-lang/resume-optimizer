import sqlite3, os, time, threading

DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "data.db")

# Connection pool — reuse connections per thread
_local = threading.local()

def get_db():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
        _local.conn.execute("PRAGMA busy_timeout=5000")
    return _local.conn

def close_db():
    if hasattr(_local, "conn") and _local.conn is not None:
        _local.conn.close()
        _local.conn = None

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            realname TEXT NOT NULL DEFAULT '',
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            free_quota INTEGER NOT NULL DEFAULT 3,
            is_paid INTEGER NOT NULL DEFAULT 0,
            is_admin INTEGER NOT NULL DEFAULT 0,
            reset_token TEXT DEFAULT '',
            reset_token_expiry TIMESTAMP,
            wx_openid TEXT DEFAULT '',
            wx_unionid TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            resume_filename TEXT DEFAULT '',
            resume_text TEXT NOT NULL DEFAULT '',
            overall_score INTEGER,
            scores_json TEXT DEFAULT '{}',
            suggestions_json TEXT DEFAULT '[]',
            optimized_resume TEXT DEFAULT '',
            jd_text TEXT DEFAULT '',
            jd_match_score INTEGER,
            jd_analysis TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_analyses_user ON analyses(user_id);
        CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at DESC);
        CREATE TABLE IF NOT EXISTS redeem_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            quota_add INTEGER NOT NULL DEFAULT 10,
            is_used INTEGER NOT NULL DEFAULT 0,
            used_by INTEGER,
            used_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            plan_type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            memo TEXT DEFAULT '',
            alipay_trade_no TEXT DEFAULT '',
            alipay_buyer_id TEXT DEFAULT '',
            paid_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
        CREATE INDEX IF NOT EXISTS idx_orders_no ON orders(order_no);
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER,
            code TEXT UNIQUE NOT NULL,
            reward_claimed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (referrer_id) REFERENCES users(id),
            FOREIGN KEY (referred_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS enterprise_api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            api_key TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            calls_used INTEGER DEFAULT 0,
            calls_limit INTEGER DEFAULT 1000,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    db.commit()

    for col, typ in [("wx_openid", "TEXT DEFAULT ''"), ("wx_unionid", "TEXT DEFAULT ''")]:
        try:
            db.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
        except Exception:
            pass

def create_user(username, password_hash, realname="", phone="", email="", wx_openid="", wx_unionid=""):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, password_hash, realname, phone, email, wx_openid, wx_unionid) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (username, password_hash, realname, phone, email, wx_openid, wx_unionid)
        )
        db.commit()
        return db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    except sqlite3.IntegrityError:
        return None

def get_user_by_username(username):
    return get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

def get_user_by_phone(phone):
    return get_db().execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()

def get_user_by_email(email):
    return get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

def get_user_by_wx_openid(openid):
    return get_db().execute("SELECT * FROM users WHERE wx_openid=?", (openid,)).fetchone()

def get_user_by_reset_token(token):
    """Get user by reset token with expiry check"""
    from datetime import datetime as dt
    user = get_db().execute("SELECT * FROM users WHERE reset_token=?", (token,)).fetchone()
    if not user:
        return None
    if user["reset_token_expiry"]:
        try:
            expiry = dt.strptime(user["reset_token_expiry"], "%Y-%m-%d %H:%M:%S")
            if dt.utcnow() > expiry:
                return None
        except (ValueError, TypeError):
            pass
    return user

def update_user(user_id, **kwargs):
    allowed = {"username", "password_hash", "realname", "phone", "email", "reset_token",
               "reset_token_expiry", "free_quota", "is_paid"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    db = get_db()
    cols = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [user_id]
    db.execute(f"UPDATE users SET {cols} WHERE id=?", vals)
    db.commit()

def get_user_by_id(user_id):
    return get_db().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

def use_free_quota(user_id):
    db = get_db()
    db.execute("UPDATE users SET free_quota = free_quota - 1 WHERE id=? AND free_quota > 0", (user_id,))
    db.commit()
    row = db.execute("SELECT free_quota FROM users WHERE id=?", (user_id,)).fetchone()
    return row["free_quota"] if row else 0

def can_analyze(user_id):
    user = get_db().execute("SELECT free_quota, is_paid FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        return False
    return user["free_quota"] > 0 or user["is_paid"] == 1

def save_analysis(user_id, resume_filename, resume_text, overall_score, scores_json,
                  suggestions_json, optimized_resume, jd_text="", jd_match_score=None, jd_analysis=""):
    db = get_db()
    db.execute(
        """INSERT INTO analyses (user_id, resume_filename, resume_text, overall_score, scores_json,
           suggestions_json, optimized_resume, jd_text, jd_match_score, jd_analysis)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, resume_filename, resume_text, overall_score, scores_json,
         suggestions_json, optimized_resume, jd_text, jd_match_score, jd_analysis)
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]

def get_user_analyses(user_id):
    return get_db().execute(
        "SELECT id, resume_filename, overall_score, jd_match_score, created_at FROM analyses WHERE user_id=? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()

def get_analysis(analysis_id, user_id):
    return get_db().execute(
        "SELECT * FROM analyses WHERE id=? AND user_id=?", (analysis_id, user_id)
    ).fetchone()

def create_order(order_no, user_id, plan_type, amount):
    db = get_db()
    db.execute("INSERT INTO orders (order_no, user_id, plan_type, amount) VALUES (?, ?, ?, ?)",
               (order_no, user_id, plan_type, amount))
    db.commit()

def get_order(order_no):
    return get_db().execute("SELECT * FROM orders WHERE order_no=?", (order_no,)).fetchone()

def mark_order_paid(order_no, alipay_trade_no="", alipay_buyer_id=""):
    db = get_db()
    db.execute(
        """UPDATE orders SET status='paid', alipay_trade_no=?, alipay_buyer_id=?,
           paid_at=datetime('now') WHERE order_no=?""",
        (alipay_trade_no, alipay_buyer_id, order_no))
    db.commit()

# ============ 推荐系统 ============
def create_referral_code(user_id):
    """Generates a unique 8-char referral code and returns it."""
    import secrets, string
    db = get_db()
    for _ in range(10):
        code = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        existing = db.execute("SELECT id FROM referrals WHERE code=?", (code,)).fetchone()
        if not existing:
            break
    else:
        return None
    db.execute(
        "INSERT INTO referrals (referrer_id, code) VALUES (?, ?)",
        (user_id, code)
    )
    db.commit()
    return code

def get_referral_by_code(code):
    """Returns referral row or None."""
    return get_db().execute(
        "SELECT * FROM referrals WHERE code=?", (code,)
    ).fetchone()

def use_referral_code(code, referred_user_id):
    """Marks a referral as used by setting referred_id."""
    db = get_db()
    db.execute(
        "UPDATE referrals SET referred_id=? WHERE code=? AND referred_id IS NULL",
        (referred_user_id, code)
    )
    db.commit()
    return db.execute("SELECT * FROM referrals WHERE code=?", (code,)).fetchone()

def get_referral_stats(user_id):
    """Returns count of successful referrals (where referred_id is set)."""
    row = get_db().execute(
        "SELECT COUNT(*) as cnt FROM referrals WHERE referrer_id=? AND referred_id IS NOT NULL",
        (user_id,)
    ).fetchone()
    return row["cnt"] if row else 0

# ============ 企业API Key ============
def create_enterprise_key(user_id, name, calls_limit=1000):
    """Creates an enterprise API key and returns the key string."""
    import secrets, string
    db = get_db()
    for _ in range(10):
        api_key = "ev_" + ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
        existing = db.execute("SELECT id FROM enterprise_api_keys WHERE api_key=?", (api_key,)).fetchone()
        if not existing:
            break
    else:
        return None
    db.execute(
        "INSERT INTO enterprise_api_keys (user_id, api_key, name, calls_limit) VALUES (?, ?, ?, ?)",
        (user_id, api_key, name, calls_limit)
    )
    db.commit()
    return api_key

def get_enterprise_key(api_key):
    """Returns enterprise API key row or None."""
    return get_db().execute(
        "SELECT * FROM enterprise_api_keys WHERE api_key=? AND is_active=1", (api_key,)
    ).fetchone()

def use_enterprise_call(api_key):
    """Increments calls_used. Returns True if under limit, False if exceeded or key not found."""
    db = get_db()
    row = db.execute(
        "SELECT calls_used, calls_limit FROM enterprise_api_keys WHERE api_key=? AND is_active=1",
        (api_key,)
    ).fetchone()
    if not row:
        return False
    if row["calls_used"] >= row["calls_limit"]:
        return False
    db.execute(
        "UPDATE enterprise_api_keys SET calls_used = calls_used + 1 WHERE api_key=?",
        (api_key,)
    )
    db.commit()
    return True
