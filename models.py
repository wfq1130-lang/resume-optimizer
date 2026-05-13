import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

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
    """)
    db.commit()
    db.close()

def create_user(username, password_hash, realname="", phone="", email=""):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, password_hash, realname, phone, email) VALUES (?, ?, ?, ?, ?)",
            (username, password_hash, realname, phone, email)
        )
        db.commit()
        return db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    except sqlite3.IntegrityError:
        return None
    finally:
        db.close()

def get_user_by_username(username):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    db.close()
    return row

def get_user_by_phone(phone):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
    db.close()
    return row

def get_user_by_email(email):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    db.close()
    return row

def get_user_by_reset_token(token):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE reset_token=?", (token,)).fetchone()
    db.close()
    return row

def update_user(user_id, **kwargs):
    """Update user fields by kwargs"""
    db = get_db()
    allowed = {"username", "password_hash", "realname", "phone", "email", "reset_token", "reset_token_expiry"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        db.close()
        return
    cols = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [user_id]
    db.execute(f"UPDATE users SET {cols} WHERE id=?", vals)
    db.commit()
    db.close()

def get_user_by_id(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    return row

def use_free_quota(user_id):
    """减一次免费额度，返回减后的剩余值"""
    db = get_db()
    db.execute("UPDATE users SET free_quota = free_quota - 1 WHERE id=? AND free_quota > 0", (user_id,))
    db.commit()
    row = db.execute("SELECT free_quota FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    return row["free_quota"] if row else 0

def can_analyze(user_id):
    """检查用户是否还能分析"""
    db = get_db()
    user = db.execute("SELECT free_quota, is_paid FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
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
    analysis_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return analysis_id

def get_user_analyses(user_id):
    db = get_db()
    rows = db.execute(
        "SELECT id, resume_filename, overall_score, jd_match_score, created_at FROM analyses WHERE user_id=? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    db.close()
    return rows

def get_analysis(analysis_id, user_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM analyses WHERE id=? AND user_id=?", (analysis_id, user_id)
    ).fetchone()
    db.close()
    return row
