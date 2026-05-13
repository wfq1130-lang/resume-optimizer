import json, os, uuid
from functools import wraps
from datetime import datetime, timedelta

from flask import Flask, g, jsonify, redirect, render_template, request, session, send_file, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from models import (
    get_db, init_db, create_user, get_user_by_username, get_user_by_id,
    get_user_by_phone, get_user_by_email, get_user_by_reset_token, update_user,
    use_free_quota, can_analyze, save_analysis, get_user_analyses, get_analysis
)
from resume_parser import parse_resume
from ai_analyzer import analyze_resume, match_jd, generate_resume

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
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
    if request.method == "POST":
        account = request.form.get("account", "").strip()
        password = request.form.get("password", "")

        if not account or not password:
            return render_template("login.html", error="请输入账号和密码")

        # Support login by username, phone, or email
        user = None
        if "@" in account:
            user = get_user_by_email(account)
        elif account.isdigit() and len(account) == 11:
            user = get_user_by_phone(account)
        else:
            user = get_user_by_username(account)

        if not user or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="账号或密码错误")

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

        return render_template("login.html", success="注册成功，请登录")

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
    """AI resume generation — works for both guests and logged-in users"""
    user_input = request.form.get("user_input", "").strip()
    scene = request.form.get("scene", "").strip()

    if not user_input or len(user_input) < 10:
        return render_template("index.html", gen_error="请至少输入10个字描述你的情况")

    if len(user_input) > 3000:
        user_input = user_input[:3000]

    result = generate_resume(user_input, scene)

    if "error" in result:
        return render_template("index.html", gen_error=result["error"])

    # For logged-in users, save to history as well
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


# -- Health check ------------------------------------------------

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# -- Main --------------------------------------------------------

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5001))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("DEBUG", "0") == "1"

    try:
        from waitress import serve
        print(f"AI resume optimizer: http://127.0.0.1:{port}")
        serve(app, host=host, port=port, threads=4)
    except ImportError:
        app.run(host=host, port=port, debug=True)
