import json, os, uuid
from functools import wraps
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, request, session, send_file, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from models import (
    get_db, init_db, create_user, get_user_by_username, get_user_by_id,
    get_user_by_phone, get_user_by_email, get_user_by_reset_token, update_user,
    use_free_quota, can_analyze, save_analysis, get_user_analyses, get_analysis,
    create_order, get_order, mark_order_paid
)
from ai_analyzer import generate_resume as ai_generate_resume
from payment import get_plan
from internal_client import backend_post, backend_get

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

_secret_path = os.path.join(BASE_DIR, ".secret_key")
if os.path.exists(_secret_path):
    with open(_secret_path, "rb") as f:
        _secret = f.read()
else:
    _secret = os.urandom(24)
    with open(_secret_path, "wb") as f:
        f.write(_secret)
app.secret_key = os.environ.get("SECRET_KEY", _secret.hex())
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "txt", "md"}
TEACHER_CODE = os.environ.get("TEACHER_CODE", "admin123")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# -- Auth decorators ---------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def quota_required(f):
    """需要剩余免费次数或付费才能访问"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not can_analyze(session["user_id"]):
            return redirect(url_for("pricing"))
        return f(*args, **kwargs)
    return decorated


# -- Context processor -------------------------------------------

@app.context_processor
def inject_now():
    return {"now": datetime.now().strftime("%Y-%m-%d %H:%M")}


# -- Auth routes -------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET" and request.args.get("registered"):
        return render_template("login.html", success="注册成功，请登录")

    if request.method == "POST":
        account = request.form.get("account", "").strip()
        password = request.form.get("password", "")

        if not account or not password:
            return render_template("login.html", error="请输入账号和密码", account=account)

        user = None
        if "@" in account:
            user = get_user_by_email(account)
        elif account.isdigit() and len(account) == 11:
            user = get_user_by_phone(account)
        else:
            user = get_user_by_username(account)

        if not user or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="账号或密码错误", account=account)

        session.clear()
        session.permanent = True
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["realname"] = user["realname"]
        session["free_quota"] = user["free_quota"]
        session["is_paid"] = bool(user["is_paid"])
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()

        if not username or not password:
            return render_template("register.html", error="请填写账号和密码")

        if len(username) < 3 or len(username) > 20:
            return render_template("register.html", error="账号长度3-20位")

        if len(password) < 6:
            return render_template("register.html", error="密码至少6位")

        if phone and get_user_by_phone(phone):
            return render_template("register.html", error="该手机号已被注册")

        if email and get_user_by_email(email):
            return render_template("register.html", error="该邮箱已被注册")

        pw_hash = generate_password_hash(password)
        user = create_user(username, pw_hash, username, phone, email)
        if not user:
            return render_template("register.html", error="账号已被注册")

        return redirect(url_for("login", registered="1"))

    return render_template("register.html")


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        account = request.form.get("account", "").strip()
        if not account:
            return render_template("forgot.html", error="请输入邮箱或手机号")

        user = None
        if "@" in account:
            user = get_user_by_email(account)
        elif account.isdigit() and len(account) == 11:
            user = get_user_by_phone(account)
        else:
            user = get_user_by_email(account) or get_user_by_phone(account)

        if not user:
            return render_template("forgot.html", error="未找到该账号")

        import secrets
        from datetime import datetime as dt
        token = secrets.token_urlsafe(32)
        expiry = dt.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        update_user(user["id"], reset_token=token, reset_token_expiry=expiry)

        reset_url = url_for("reset_password", token=token, _external=True)
        return render_template("forgot.html", success=True, reset_url=reset_url,
                              contact=account)

    return render_template("forgot.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = get_user_by_reset_token(token)
    if not user:
        return render_template("reset_password.html", error="重置链接已失效或不存在", token_valid=False)

    if request.method == "POST":
        password = request.form.get("password", "")
        if len(password) < 6:
            return render_template("reset_password.html", error="密码至少6位", token=token, token_valid=True)

        pw_hash = generate_password_hash(password)
        update_user(user["id"], password_hash=pw_hash, reset_token="", reset_token_expiry=None)
        return render_template("login.html", success="密码重置成功，请登录")

    return render_template("reset_password.html", token=token, token_valid=True)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# -- Main routes -------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
@login_required
@quota_required
def analyze():
    jd_text = request.form.get("jd_text", "").strip()

    # Forward file upload to backend
    files = {}
    file = request.files.get("resume_file")
    if file and file.filename and allowed_file(file.filename):
        files["resume_file"] = (file.filename, file.stream, file.content_type or "application/octet-stream")

    data = {}
    if not files:
        data["resume_text"] = request.form.get("resume_text", "").strip()
    if jd_text:
        data["jd_text"] = jd_text

    result, status = backend_post("/api/v1/analyze", data=data, files=files if files else None,
                                   user_id=session["user_id"])

    if "error" in result:
        return render_template("index.html", error=result["error"])

    # Sync session quota from backend response
    if "quota_remaining" in result and not session.get("is_paid"):
        session["free_quota"] = result["quota_remaining"]

    return redirect(url_for("result", analysis_id=result["analysis_id"]))


@app.route("/result/<int:analysis_id>")
@login_required
def result(analysis_id):
    analysis = get_analysis(analysis_id, session["user_id"])
    if not analysis:
        return "记录不存在", 404

    scores = json.loads(analysis["scores_json"])
    suggestions = json.loads(analysis["suggestions_json"])
    jd_result = json.loads(analysis["jd_analysis"]) if analysis["jd_analysis"] else None

    return render_template(
        "result.html",
        analysis=analysis,
        scores=scores,
        suggestions=suggestions,
        jd_result=jd_result
    )


@app.route("/history")
@login_required
def history():
    analyses = get_user_analyses(session["user_id"])
    return render_template("history.html", analyses=analyses)


@app.route("/pricing")
@login_required
def pricing():
    return render_template("pricing.html")


@app.route("/export/<int:analysis_id>")
@login_required
def export_resume(analysis_id):
    analysis = get_analysis(analysis_id, session["user_id"])
    if not analysis:
        return "记录不存在", 404

    return render_template("export.html",
        optimized_resume=analysis["optimized_resume"],
        created_at=analysis["created_at"]
    )


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/generate", methods=["POST"])
def generate():
    user_input = request.form.get("user_input", "").strip()
    scene = request.form.get("scene", "").strip()

    if not user_input or len(user_input) < 10:
        return render_template("index.html", gen_error="请至少输入10个字描述你的情况")

    if len(user_input) > 3000:
        user_input = user_input[:3000]

    # Guest mode: local call (no backend JWT available)
    if "user_id" not in session:
        guest_gen = session.get("guest_gen_count", 0)
        if guest_gen >= 1:
            return render_template("index.html",
                gen_error="免费次数已用完（每人限1次），请注册登录后继续使用")

        result = ai_generate_resume(user_input, scene)

        if "error" in result:
            return render_template("index.html", gen_error=result["error"])

        session["guest_gen_count"] = session.get("guest_gen_count", 0) + 1
        session.modified = True

        return render_template("generate_result.html",
            resume_text=result["resume_text"],
            tips=result["tips"],
            user_input=user_input,
            scene=scene,
            analysis_id=None
        )

    # Logged-in: forward to backend
    result, status = backend_post("/api/v1/generate",
        data={"user_input": user_input, "scene": scene},
        user_id=session["user_id"])

    if "error" in result:
        return render_template("index.html", gen_error=result["error"])

    return render_template("generate_result.html",
        resume_text=result.get("resume_text", ""),
        tips=result.get("tips", ""),
        user_input=user_input,
        scene=scene,
        analysis_id=result.get("analysis_id")
    )


@app.route("/guide")
def guide():
    return render_template("guide.html")


# -- ATS check (delegates to backend) -----------------------------

@app.route("/ats-check", methods=["POST"])
@login_required
def ats_check():
    resume_text = request.form.get("resume_text", "").strip()
    jd_text = request.form.get("jd_text", "").strip()

    if not resume_text or len(resume_text) < 50:
        return render_template("ats_result.html", error="简历内容至少50字才能进行ATS分析")

    result, status = backend_post("/api/v1/ats-check",
        data={"resume_text": resume_text, "jd_text": jd_text},
        user_id=session["user_id"])

    if "error" in result:
        return render_template("ats_result.html", error=result["error"])

    return render_template("ats_result.html", ats=result, resume_text=resume_text, jd_text=jd_text)


# -- Targeted optimize (delegates to backend) ---------------------

@app.route("/targeted-optimize", methods=["POST"])
@login_required
@quota_required
def targeted_optimize():
    resume_text = request.form.get("resume_text", "").strip()
    jd_text = request.form.get("jd_text", "").strip()

    if not resume_text or len(resume_text) < 50:
        return render_template("targeted_result.html", error="简历内容至少50字")

    if not jd_text or len(jd_text) < 30:
        return render_template("targeted_result.html", error="请提供职位描述(JD)以进行定向优化")

    result, status = backend_post("/api/v1/targeted-optimize",
        data={"resume_text": resume_text, "jd_text": jd_text},
        user_id=session["user_id"])

    if "error" in result:
        return render_template("targeted_result.html", error=result["error"])

    # Sync session quota
    if "quota_remaining" in result and not session.get("is_paid"):
        session["free_quota"] = result["quota_remaining"]

    return render_template("targeted_result.html",
        result=result.get("result", result),
        ats=result.get("ats", {}),
        analysis_id=result.get("analysis_id"))


# -- Admin ------------------------------------------------------

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        user = get_user_by_id(session["user_id"])
        if not user or not user["is_admin"]:
            return "Access denied", 403
        return f(*args, **kwargs)
    return decorated


@app.route("/admin")
@admin_required
def admin():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    total_users = len(users)
    paid_users = sum(1 for u in users if u["is_paid"])
    total_analyses = db.execute("SELECT COUNT(*) as c FROM analyses").fetchone()["c"]
    today_users = db.execute(
        "SELECT COUNT(*) as c FROM users WHERE date(created_at)=date('now')"
    ).fetchone()["c"]
    today_analyses = db.execute(
        "SELECT COUNT(*) as c FROM analyses WHERE date(created_at)=date('now')"
    ).fetchone()["c"]
    today_paid = db.execute(
        "SELECT COUNT(*) as c FROM orders WHERE status='paid' AND date(paid_at)=date('now')"
    ).fetchone()["c"]
    recent_orders = db.execute(
        "SELECT o.*, u.username FROM orders o JOIN users u ON o.user_id=u.id ORDER BY o.created_at DESC LIMIT 10"
    ).fetchall()
    codes = db.execute("SELECT * FROM redeem_codes ORDER BY created_at DESC LIMIT 20").fetchall()
    db.close()
    return render_template("admin.html",
        users=users, total_users=total_users, paid_users=paid_users,
        total_analyses=total_analyses, codes=codes,
        today_users=today_users, today_analyses=today_analyses,
        today_paid=today_paid, recent_orders=recent_orders
    )


@app.route("/admin/user/<int:user_id>/add-quota", methods=["POST"])
@admin_required
def admin_add_quota(user_id):
    amount = int(request.form.get("amount", 10))
    db = get_db()
    db.execute("UPDATE users SET free_quota = free_quota + ? WHERE id=?", (amount, user_id))
    db.commit()
    db.close()
    return redirect(url_for("admin"))


@app.route("/admin/user/<int:user_id>/toggle-paid", methods=["POST"])
@admin_required
def admin_toggle_paid(user_id):
    db = get_db()
    user = db.execute("SELECT is_paid FROM users WHERE id=?", (user_id,)).fetchone()
    if user:
        new_val = 0 if user["is_paid"] else 1
        db.execute("UPDATE users SET is_paid=? WHERE id=?", (new_val, user_id))
        db.commit()
    db.close()
    return redirect(url_for("admin"))


@app.route("/admin/generate-codes", methods=["POST"])
@admin_required
def admin_generate_codes():
    count = int(request.form.get("count", 5))
    quota = int(request.form.get("quota", 10))
    db = get_db()
    import secrets
    codes = []
    for _ in range(count):
        code = "RV" + secrets.token_hex(4).upper()
        db.execute("INSERT INTO redeem_codes (code, quota_add) VALUES (?, ?)", (code, quota))
        codes.append(code)
    db.commit()
    db.close()
    return render_template("admin_codes.html", codes=codes, quota=quota)


# -- Redeem ----------------------------------------------------

@app.route("/redeem", methods=["GET", "POST"])
@login_required
def redeem():
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        db = get_db()
        row = db.execute("SELECT * FROM redeem_codes WHERE code=? AND is_used=0", (code,)).fetchone()
        if not row:
            db.close()
            return render_template("redeem.html", error="兑换码无效或已使用")

        db.execute("UPDATE redeem_codes SET is_used=1, used_by=?, used_at=datetime('now') WHERE id=?",
                   (session["user_id"], row["id"]))
        db.execute("UPDATE users SET free_quota = free_quota + ? WHERE id=?",
                   (row["quota_add"], session["user_id"]))
        db.commit()
        session["free_quota"] = session["free_quota"] + row["quota_add"]
        db.close()
        return render_template("redeem.html", success=f"兑换成功！获得 {row['quota_add']} 次分析额度")

    return render_template("redeem.html")


# -- Health check -------------------------------------------------

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# -- Payment (session wrappers that delegate to backend) ----------

@app.route("/api/create-order", methods=["POST"])
@login_required
def api_create_order():
    plan_type = request.form.get("plan_type", "").strip()
    result, status = backend_post("/api/v1/create-order",
        data={"plan_type": plan_type},
        user_id=session["user_id"])
    return jsonify(result), status


@app.route("/api/check-order", methods=["POST"])
@login_required
def api_check_order():
    order_no = request.form.get("order_no", "").strip()
    result, status = backend_get(f"/api/v1/payment/status/{order_no}",
        user_id=session["user_id"])
    return jsonify(result), status


@app.route("/api/payment/simulate/<order_no>", methods=["POST"])
@login_required
def api_simulate_payment(order_no):
    result, status = backend_post(f"/api/v1/payment/simulate/{order_no}",
        user_id=session["user_id"])

    if result.get("status") == "paid":
        plan = get_plan(result.get("plan_type", ""))
        if plan:
            session["free_quota"] = session.get("free_quota", 0) + plan["quota"]
        session["is_paid"] = True
        session.modified = True

    return jsonify(result), status


# -- Main --------------------------------------------------------

if __name__ == "__main__":
    init_db()
    # Ensure admin exists
    admin = get_user_by_username("admin")
    if not admin:
        create_user("admin", generate_password_hash("admin123"), "管理员")
        db = get_db()
        db.execute("UPDATE users SET is_admin=1, free_quota=9999 WHERE username='admin'")
        db.commit()
        db.close()
        print("Admin created: admin / admin123")
    port = int(os.environ.get("PORT", 5001))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("DEBUG", "0") == "1"

    try:
        from waitress import serve
        print(f"Frontend server: http://127.0.0.1:{port}")
        serve(app, host=host, port=port, threads=4)
    except ImportError:
        app.run(host=host, port=port, debug=True)
