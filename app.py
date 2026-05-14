import json, os, uuid, requests
from functools import wraps
from datetime import datetime, timedelta

from flask import Flask, g, jsonify, make_response, redirect, render_template, request, session, send_file, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from models import (
    get_db, init_db, create_user, get_user_by_username, get_user_by_id,
    get_user_by_phone, get_user_by_email, get_user_by_reset_token, update_user,
    use_free_quota, can_analyze, save_analysis, get_user_analyses, get_analysis,
    create_order, get_order, mark_order_paid, get_user_by_wx_openid
)
import jwt
from resume_parser import parse_resume
from ai_analyzer import analyze_resume, match_jd, generate_resume
from ats_checker import check_ats
from jd_analyzer import parse_jd, analyze_gap, generate_targeted_resume
from payment import create_qrcode, verify_notify, get_plan, generate_order_no, ALIPAY_SANDBOX

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
WX_APPID = os.environ.get("WX_APPID", "")
WX_SECRET = os.environ.get("WX_SECRET", "")
JWT_SECRET = os.environ.get("JWT_SECRET", app.secret_key)
JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "720"))


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


def api_login_required(f):
    """API auth via Bearer JWT token"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "未登录"}), 401
        try:
            token = auth[7:]
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            request.api_user_id = payload["user_id"]
        except Exception:
            return jsonify({"error": "登录已过期"}), 401
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

        # Support login by username, phone, or email
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

        # Check phone uniqueness if provided
        if phone and get_user_by_phone(phone):
            return render_template("register.html", error="该手机号已被注册")

        # Check email uniqueness if provided
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

        # Find user by email or phone
        user = None
        if "@" in account:
            user = get_user_by_email(account)
        elif account.isdigit() and len(account) == 11:
            user = get_user_by_phone(account)
        else:
            user = get_user_by_email(account) or get_user_by_phone(account)

        if not user:
            return render_template("forgot.html", error="未找到该账号")

        # Generate reset token (in production, send via email/SMS)
        import secrets
        from datetime import datetime as dt
        token = secrets.token_urlsafe(32)
        expiry = dt.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        update_user(user["id"], reset_token=token, reset_token_expiry=expiry)

        # For MVP, show the reset link directly (in production, email it)
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
    resume_text = ""
    filename = ""
    jd_text = request.form.get("jd_text", "").strip()

    # Get resume from file upload
    file = request.files.get("resume_file")
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        save_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        filepath = os.path.join(UPLOAD_DIR, save_name)
        file.save(filepath)
        resume_text = parse_resume(filepath, filename)
        try:
            os.remove(filepath)
        except Exception:
            pass

    # Get resume from textarea
    if not resume_text:
        resume_text = request.form.get("resume_text", "").strip()

    if not resume_text or len(resume_text) < 20:
        if "showToast" not in request.form:
            return render_template("index.html", error="请上传简历文件或粘贴简历内容（至少20个字）")

    if len(resume_text) > 8000:
        resume_text = resume_text[:8000]

    do_jd_match = bool(jd_text and len(jd_text) > 20)
    if do_jd_match and len(jd_text) > 4000:
        jd_text = jd_text[:4000]

    result = analyze_resume(resume_text)
    if "error" in result:
        return render_template("index.html", error=result["error"])

    jd_result = None
    if do_jd_match:
        jd_result = match_jd(resume_text, jd_text)

    if not session.get("is_paid"):
        new_quota = use_free_quota(session["user_id"])
        session["free_quota"] = new_quota

    scores_json = json.dumps(result["scores"], ensure_ascii=False)
    suggestions_json = json.dumps(result["suggestions"], ensure_ascii=False)
    jd_match_score = jd_result["match_score"] if jd_result and "error" not in jd_result else None
    jd_analysis = json.dumps(jd_result, ensure_ascii=False) if jd_result and "error" not in jd_result else ""

    analysis_id = save_analysis(
        user_id=session["user_id"],
        resume_filename=filename,
        resume_text=resume_text,
        overall_score=result["overall_score"],
        scores_json=scores_json,
        suggestions_json=suggestions_json,
        optimized_resume=result["optimized_resume"],
        jd_text=jd_text if do_jd_match else "",
        jd_match_score=jd_match_score,
        jd_analysis=jd_analysis
    )

    return redirect(url_for("result", analysis_id=analysis_id))


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
    """Clean printable resume page"""
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
    """AI resume generation — 1 free for guests, quota-limited for users"""
    user_input = request.form.get("user_input", "").strip()
    scene = request.form.get("scene", "").strip()

    if not user_input or len(user_input) < 10:
        return render_template("index.html", gen_error="请至少输入10个字描述你的情况")

    if len(user_input) > 3000:
        user_input = user_input[:3000]

    # Limit guest usage to 1 free generation
    if "user_id" not in session:
        guest_gen = session.get("guest_gen_count", 0)
        if guest_gen >= 1:
            return render_template("index.html",
                gen_error="免费次数已用完（每人限1次），请注册登录后继续使用")

    result = generate_resume(user_input, scene)

    if "error" in result:
        return render_template("index.html", gen_error=result["error"])

    # Save for logged-in users
    analysis_id = None
    if "user_id" in session:
        analysis_id = save_analysis(
            user_id=session["user_id"],
            resume_filename="",
            resume_text=user_input,
            overall_score=None,
            scores_json="{}",
            suggestions_json="[]",
            optimized_resume=result["resume_text"],
            jd_text="",
            jd_match_score=None,
            jd_analysis=""
        )

    # Increment guest counter via session
    if "user_id" not in session:
        session["guest_gen_count"] = session.get("guest_gen_count", 0) + 1
        session.modified = True

    return render_template("generate_result.html",
        resume_text=result["resume_text"],
        tips=result["tips"],
        user_input=user_input,
        scene=scene,
        analysis_id=analysis_id
    )


@app.route("/guide")
def guide():
    return render_template("guide.html")


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
    from flask import flash
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


@app.route("/ats-check", methods=["POST"])
@login_required
def ats_check():
    """ATS compatibility check — the key differentiator from generic AI chat"""
    resume_text = request.form.get("resume_text", "").strip()
    jd_text = request.form.get("jd_text", "").strip()

    if not resume_text or len(resume_text) < 50:
        return render_template("ats_result.html", error="简历内容至少50字才能进行ATS分析")

    if len(resume_text) > 8000:
        resume_text = resume_text[:8000]
    if jd_text and len(jd_text) > 4000:
        jd_text = jd_text[:4000]

    result = check_ats(resume_text, jd_text)
    return render_template("ats_result.html", ats=result, resume_text=resume_text, jd_text=jd_text)


@app.route("/targeted-optimize", methods=["POST"])
@login_required
@quota_required
def targeted_optimize():
    """Deep JD analysis + targeted resume optimization"""
    resume_text = request.form.get("resume_text", "").strip()
    jd_text = request.form.get("jd_text", "").strip()

    if not resume_text or len(resume_text) < 50:
        return render_template("targeted_result.html", error="简历内容至少50字")

    if not jd_text or len(jd_text) < 30:
        return render_template("targeted_result.html", error="请提供职位描述(JD)以进行定向优化")

    if len(resume_text) > 6000:
        resume_text = resume_text[:6000]
    if len(jd_text) > 4000:
        jd_text = jd_text[:4000]

    # Run ATS check in parallel
    ats_result = check_ats(resume_text, jd_text)

    # Generate targeted resume
    result = generate_targeted_resume(resume_text, jd_text)

    if not session.get("is_paid"):
        new_quota = use_free_quota(session["user_id"])
        session["free_quota"] = new_quota

    analysis_id = save_analysis(
        user_id=session["user_id"],
        resume_filename="",
        resume_text=resume_text,
        overall_score=result.get("ats_score_estimate"),
        scores_json=json.dumps({"keyword_coverage": result.get("keyword_coverage", 0)}),
        suggestions_json=json.dumps(result.get("changes_summary", []), ensure_ascii=False),
        optimized_resume=result.get("optimized_resume", ""),
        jd_text=jd_text,
        jd_match_score=result.get("keyword_coverage"),
        jd_analysis=json.dumps(result.get("gap_analysis", {}), ensure_ascii=False)
    )

    return render_template("targeted_result.html",
        result=result, ats=ats_result, analysis_id=analysis_id)


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


# -- Payment ----------------------------------------------------

@app.route("/api/create-order", methods=["POST"])
@login_required
def api_create_order():
    plan_type = request.form.get("plan_type", "").strip()
    plan = get_plan(plan_type)
    if not plan:
        return jsonify({"error": "无效的套餐类型"}), 400

    order_no = generate_order_no()
    create_order(order_no, session["user_id"], plan_type, plan["amount"])

    # Try real payment; fall back to mock for dev
    result = create_qrcode(order_no, plan_type)
    if "error" in result:
        # In dev/sandbox without keys, return a mock flow
        if ALIPAY_SANDBOX and "未配置" in result.get("error", ""):
            return jsonify({
                "order_no": order_no,
                "qr_code": "",
                "mock": True,
                "amount": plan["price"],
                "plan_name": plan["name"]
            })
        return jsonify(result), 500

    return jsonify(result)


@app.route("/api/check-order", methods=["POST"])
@login_required
def api_check_order():
    order_no = request.form.get("order_no", "").strip()
    order = get_order(order_no)
    if not order:
        return jsonify({"error": "订单不存在"}), 404
    if order["user_id"] != session["user_id"]:
        return jsonify({"error": "无权查看此订单"}), 403

    return jsonify({"status": order["status"], "order_no": order_no})


@app.route("/api/payment/simulate/<order_no>", methods=["POST"])
@login_required
def api_simulate_payment(order_no):
    """Dev-only: simulate payment completion for testing."""
    order = get_order(order_no)
    if not order:
        return jsonify({"error": "订单不存在"}), 404
    if order["user_id"] != session["user_id"]:
        return jsonify({"error": "无权操作此订单"}), 403
    if order["status"] == "paid":
        return jsonify({"error": "订单已支付"}), 400

    plan = get_plan(order["plan_type"])
    if not plan:
        return jsonify({"error": "套餐类型无效"}), 400

    db = get_db()
    mark_order_paid(order_no, alipay_trade_no="SIMULATED", alipay_buyer_id="dev")
    db2 = get_db()
    db2.execute("UPDATE users SET free_quota = free_quota + ?, is_paid = 1 WHERE id = ?",
                (plan["quota"], session["user_id"]))
    db2.commit()
    db2.close()

    session["free_quota"] = session.get("free_quota", 0) + plan["quota"]
    session["is_paid"] = True
    session.modified = True

    return jsonify({"status": "paid", "order_no": order_no})


@app.route("/api/payment/notify", methods=["POST"])
def api_payment_notify():
    """Alipay async notification — no auth required."""
    data = request.form.to_dict()
    signature = data.pop("sign", "")

    result = verify_notify(data, signature)
    if not result:
        return "fail", 400

    order = get_order(result["order_no"])
    if not order:
        return "fail", 404
    if order["status"] == "paid":
        return "success"

    plan = get_plan(order["plan_type"])
    mark_order_paid(result["order_no"], result["trade_no"], result["buyer_id"])

    db = get_db()
    db.execute("UPDATE users SET free_quota = free_quota + ?, is_paid = 1 WHERE id = ?",
               (plan["quota"], order["user_id"]))
    db.commit()
    db.close()

    return "success"


# -- Mini Program API v1 -----------------------------------------

def _make_token(user_id):
    exp = datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    return jwt.encode({"user_id": user_id, "exp": exp}, JWT_SECRET, algorithm="HS256")


@app.route("/api/v1/credentials-login", methods=["POST"])
def api_credentials_login():
    """Extension/browser login with username/email/phone + password, returns JWT."""
    data = request.json or request.form
    account = data.get("account", "").strip()
    password = data.get("password", "").strip()
    if not account or not password:
        return jsonify({"error": "请输入账号和密码"}), 400

    user = None
    if "@" in account:
        user = get_user_by_email(account)
    elif account.isdigit() and len(account) == 11:
        user = get_user_by_phone(account)
    else:
        user = get_user_by_username(account)

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "账号或密码错误"}), 401

    token = _make_token(user["id"])
    return jsonify({
        "token": token, "user_id": user["id"], "username": user["username"],
        "realname": user["realname"], "free_quota": user["free_quota"],
        "is_paid": bool(user["is_paid"])
    })


@app.route("/api/v1/register", methods=["POST"])
def api_register():
    """Extension/browser registration."""
    data = request.json or request.form
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    email = data.get("email", "").strip()

    if not username or not password:
        return jsonify({"error": "请填写账号和密码"}), 400
    if len(username) < 3 or len(username) > 20:
        return jsonify({"error": "账号长度3-20位"}), 400
    if len(password) < 6:
        return jsonify({"error": "密码至少6位"}), 400
    if email and get_user_by_email(email):
        return jsonify({"error": "该邮箱已被注册"}), 409

    pw_hash = generate_password_hash(password)
    user = create_user(username, pw_hash, username, "", email)
    if not user:
        return jsonify({"error": "账号已被注册"}), 409

    token = _make_token(user["id"])
    return jsonify({
        "token": token, "user_id": user["id"], "username": user["username"],
        "realname": user["realname"], "free_quota": user["free_quota"],
        "is_paid": bool(user["is_paid"])
    })


@app.route("/api/v1/wx-login", methods=["POST"])
def api_wx_login():
    code = request.json.get("code", "") if request.is_json else request.form.get("code", "")
    if not code:
        return jsonify({"error": "缺少登录凭证"}), 400

    # Exchange code for openid via WeChat API
    unionid = ""
    if not WX_APPID or not WX_SECRET:
        # Dev mode: use code directly as mock openid
        openid = f"wx_dev_{code}"
    else:
        try:
            wx_url = "https://api.weixin.qq.com/sns/jscode2session"
            wx_resp = requests.get(wx_url, params={
                "appid": WX_APPID, "secret": WX_SECRET,
                "js_code": code, "grant_type": "authorization_code"
            }, timeout=10)
            wx_data = wx_resp.json()
            openid = wx_data.get("openid")
            unionid = wx_data.get("unionid", "")
            if not openid:
                return jsonify({"error": wx_data.get("errmsg", "微信登录失败")}), 400
        except Exception as e:
            return jsonify({"error": f"微信服务异常: {str(e)}"}), 500

    # Find or create user
    user = get_user_by_wx_openid(openid)
    if not user:
        username = f"wx_{openid[:12]}"
        pw_hash = generate_password_hash(openid)  # placeholder
        user = create_user(username, pw_hash, "微信用户", wx_openid=openid, wx_unionid=unionid)

    token = _make_token(user["id"])
    return jsonify({
        "token": token,
        "user_id": user["id"],
        "username": user["username"],
        "realname": user["realname"],
        "free_quota": user["free_quota"],
        "is_paid": bool(user["is_paid"])
    })


@app.route("/api/v1/user/info")
@api_login_required
def api_user_info():
    user = get_user_by_id(request.api_user_id)
    if not user:
        return jsonify({"error": "用户不存在"}), 404
    return jsonify({
        "user_id": user["id"],
        "username": user["username"],
        "realname": user["realname"],
        "phone": user["phone"] or "",
        "email": user["email"] or "",
        "free_quota": user["free_quota"],
        "is_paid": bool(user["is_paid"])
    })


@app.route("/api/v1/user/bind", methods=["POST"])
@api_login_required
def api_user_bind():
    phone = (request.json or request.form).get("phone", "").strip()
    email = (request.json or request.form).get("email", "").strip()
    if not phone and not email:
        return jsonify({"error": "请提供手机号或邮箱"}), 400
    if phone and get_user_by_phone(phone):
        return jsonify({"error": "该手机号已被绑定"}), 409
    if email and get_user_by_email(email):
        return jsonify({"error": "该邮箱已被绑定"}), 409
    kwargs = {}
    if phone:
        kwargs["phone"] = phone
    if email:
        kwargs["email"] = email
    update_user(request.api_user_id, **kwargs)
    return jsonify({"ok": True})


@app.route("/api/v1/analyze", methods=["POST"])
@api_login_required
def api_analyze():
    if not can_analyze(request.api_user_id):
        return jsonify({"error": "次数已用完，请购买套餐"}), 402

    resume_text = ""
    filename = ""

    # File upload
    file = request.files.get("resume_file")
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        save_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        filepath = os.path.join(UPLOAD_DIR, save_name)
        file.save(filepath)
        resume_text = parse_resume(filepath, filename)
        try:
            os.remove(filepath)
        except Exception:
            pass

    # Text
    if not resume_text:
        data = request.json or request.form
        resume_text = data.get("resume_text", "").strip()

    if not resume_text or len(resume_text) < 20:
        return jsonify({"error": "简历内容至少20个字"}), 400

    if len(resume_text) > 8000:
        resume_text = resume_text[:8000]

    jd_text = (request.json or request.form).get("jd_text", "").strip()
    do_jd = bool(jd_text and len(jd_text) > 20)
    if do_jd and len(jd_text) > 4000:
        jd_text = jd_text[:4000]

    result = analyze_resume(resume_text)
    if "error" in result:
        return jsonify(result), 500

    jd_result = None
    if do_jd:
        jd_result = match_jd(resume_text, jd_text)

    user = get_user_by_id(request.api_user_id)
    if not user.get("is_paid"):
        new_quota = use_free_quota(request.api_user_id)
    else:
        new_quota = user["free_quota"]

    scores_json = json.dumps(result["scores"], ensure_ascii=False)
    suggestions_json = json.dumps(result["suggestions"], ensure_ascii=False)
    jd_match_score = jd_result["match_score"] if jd_result and "error" not in jd_result else None
    jd_analysis = json.dumps(jd_result, ensure_ascii=False) if jd_result and "error" not in jd_result else ""

    analysis_id = save_analysis(
        user_id=request.api_user_id, resume_filename=filename,
        resume_text=resume_text, overall_score=result["overall_score"],
        scores_json=scores_json, suggestions_json=suggestions_json,
        optimized_resume=result["optimized_resume"],
        jd_text=jd_text if do_jd else "", jd_match_score=jd_match_score,
        jd_analysis=jd_analysis
    )

    return jsonify({
        "analysis_id": analysis_id,
        "overall_score": result["overall_score"],
        "scores": result["scores"],
        "suggestions": result["suggestions"],
        "optimized_resume": result["optimized_resume"],
        "jd_result": jd_result,
        "quota_remaining": new_quota
    })


@app.route("/api/v1/generate", methods=["POST"])
@api_login_required
def api_generate():
    data = request.json or request.form
    user_input = data.get("user_input", "").strip()
    scene = data.get("scene", "").strip()

    if not user_input or len(user_input) < 10:
        return jsonify({"error": "请至少输入10个字"}), 400
    if len(user_input) > 3000:
        user_input = user_input[:3000]

    result = generate_resume(user_input, scene)
    if "error" in result:
        return jsonify(result), 500

    analysis_id = save_analysis(
        user_id=request.api_user_id, resume_filename="",
        resume_text=user_input, overall_score=None,
        scores_json="{}", suggestions_json="[]",
        optimized_resume=result["resume_text"],
        jd_text="", jd_match_score=None, jd_analysis=""
    )

    return jsonify({
        "analysis_id": analysis_id,
        "resume_text": result["resume_text"],
        "tips": result["tips"]
    })


@app.route("/api/v1/history")
@api_login_required
def api_history():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    analyses = get_user_analyses(request.api_user_id)
    total = len(analyses)
    start = (page - 1) * per_page
    items = analyses[start:start + per_page]
    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": [{
            "id": a["id"],
            "resume_filename": a["resume_filename"],
            "overall_score": a["overall_score"],
            "jd_match_score": a["jd_match_score"],
            "created_at": a["created_at"]
        } for a in items]
    })


@app.route("/api/v1/result/<int:analysis_id>")
@api_login_required
def api_result(analysis_id):
    analysis = get_analysis(analysis_id, request.api_user_id)
    if not analysis:
        return jsonify({"error": "记录不存在"}), 404

    return jsonify({
        "id": analysis["id"],
        "resume_filename": analysis["resume_filename"],
        "overall_score": analysis["overall_score"],
        "scores": json.loads(analysis["scores_json"]),
        "suggestions": json.loads(analysis["suggestions_json"]),
        "optimized_resume": analysis["optimized_resume"],
        "jd_text": analysis["jd_text"],
        "jd_match_score": analysis["jd_match_score"],
        "jd_analysis": json.loads(analysis["jd_analysis"]) if analysis["jd_analysis"] else None,
        "created_at": analysis["created_at"]
    })


@app.route("/api/v1/create-order", methods=["POST"])
@api_login_required
def api_v1_create_order():
    plan_type = (request.json or request.form).get("plan_type", "").strip()
    plan = get_plan(plan_type)
    if not plan:
        return jsonify({"error": "无效的套餐类型"}), 400

    order_no = generate_order_no()
    create_order(order_no, request.api_user_id, plan_type, plan["amount"])

    result = create_qrcode(order_no, plan_type)
    if "error" in result:
        if ALIPAY_SANDBOX and "未配置" in result.get("error", ""):
            return jsonify({
                "order_no": order_no, "qr_code": "",
                "mock": True, "amount": plan["price"], "plan_name": plan["name"]
            })
        return jsonify(result), 500

    return jsonify(result)


@app.route("/api/v1/payment/status/<order_no>")
@api_login_required
def api_v1_payment_status(order_no):
    order = get_order(order_no)
    if not order:
        return jsonify({"error": "订单不存在"}), 404
    if order["user_id"] != request.api_user_id:
        return jsonify({"error": "无权查看此订单"}), 403
    return jsonify({"status": order["status"], "order_no": order_no})


# -- Health check ------------------------------------------------

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


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
        print(f"AI resume optimizer: http://127.0.0.1:{port}")
        serve(app, host=host, port=port, threads=4)
    except ImportError:
        app.run(host=host, port=port, debug=True)
