import json, os, uuid, requests
from functools import wraps
from datetime import datetime, timedelta

from flask import Flask, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from models import (
    get_db, init_db, create_user, get_user_by_username, get_user_by_id,
    get_user_by_phone, get_user_by_email, get_user_by_wx_openid, update_user,
    use_free_quota, can_analyze, save_analysis, get_user_analyses, get_analysis,
    create_order, get_order, mark_order_paid
)
from resume_parser import parse_resume
from ai_analyzer import analyze_resume, match_jd, generate_resume
from ats_checker import check_ats
from jd_analyzer import generate_targeted_resume
from payment import create_qrcode, verify_notify, get_plan, generate_order_no, ALIPAY_SANDBOX
import jwt

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "txt", "md"}
JWT_SECRET = os.environ.get("JWT_SECRET", "")
if not JWT_SECRET:
    _secret_path = os.path.join(BASE_DIR, ".secret_key")
    if os.path.exists(_secret_path):
        with open(_secret_path, "rb") as f:
            JWT_SECRET = f.read().decode("utf-8", errors="replace")
    if not JWT_SECRET:
        JWT_SECRET = os.urandom(24).hex()
JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "720"))
WX_APPID = os.environ.get("WX_APPID", "")
WX_SECRET = os.environ.get("WX_SECRET", "")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _make_token(user_id):
    exp = datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    return jwt.encode({"user_id": user_id, "exp": exp}, JWT_SECRET, algorithm="HS256")


def api_login_required(f):
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


# -- Auth routes (API v1) ------------------------------------------

@app.route("/api/v1/credentials-login", methods=["POST"])
def api_credentials_login():
    data = request.get_json(silent=True) or request.form
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
    data = request.get_json(silent=True) or request.form
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

    unionid = ""
    if not WX_APPID or not WX_SECRET:
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

    user = get_user_by_wx_openid(openid)
    if not user:
        username = f"wx_{openid[:12]}"
        pw_hash = generate_password_hash(openid)
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


# -- User routes (API v1) ------------------------------------------

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
    phone = (request.get_json(silent=True) or request.form).get("phone", "").strip()
    email = (request.get_json(silent=True) or request.form).get("email", "").strip()
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


# -- Analysis routes (API v1) --------------------------------------

@app.route("/api/v1/analyze", methods=["POST"])
@api_login_required
def api_analyze():
    if not can_analyze(request.api_user_id):
        return jsonify({"error": "次数已用完，请购买套餐"}), 402

    resume_text = ""
    filename = ""

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

    if not resume_text:
        data = request.get_json(silent=True) or request.form
        resume_text = data.get("resume_text", "").strip()

    if not resume_text or len(resume_text) < 20:
        return jsonify({"error": "简历内容至少20个字"}), 400

    if len(resume_text) > 8000:
        resume_text = resume_text[:8000]

    jd_text = (request.get_json(silent=True) or request.form).get("jd_text", "").strip()
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
    data = request.get_json(silent=True) or request.form
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


# -- New: ATS check (extracted from form handler) ------------------

@app.route("/api/v1/ats-check", methods=["POST"])
@api_login_required
def api_ats_check():
    data = request.get_json(silent=True) or request.form
    resume_text = data.get("resume_text", "").strip()
    jd_text = data.get("jd_text", "").strip()

    if not resume_text or len(resume_text) < 50:
        return jsonify({"error": "简历内容至少50字才能进行ATS分析"}), 400

    if len(resume_text) > 8000:
        resume_text = resume_text[:8000]
    if jd_text and len(jd_text) > 4000:
        jd_text = jd_text[:4000]

    result = check_ats(resume_text, jd_text)
    return jsonify(result)


# -- New: Targeted optimize (extracted from form handler) ----------

@app.route("/api/v1/targeted-optimize", methods=["POST"])
@api_login_required
def api_targeted_optimize():
    if not can_analyze(request.api_user_id):
        return jsonify({"error": "次数已用完，请购买套餐"}), 402

    data = request.get_json(silent=True) or request.form
    resume_text = data.get("resume_text", "").strip()
    jd_text = data.get("jd_text", "").strip()

    if not resume_text or len(resume_text) < 50:
        return jsonify({"error": "简历内容至少50字"}), 400
    if not jd_text or len(jd_text) < 30:
        return jsonify({"error": "请提供职位描述(JD)以进行定向优化"}), 400

    if len(resume_text) > 6000:
        resume_text = resume_text[:6000]
    if len(jd_text) > 4000:
        jd_text = jd_text[:4000]

    ats_result = check_ats(resume_text, jd_text)
    result = generate_targeted_resume(resume_text, jd_text)

    user = get_user_by_id(request.api_user_id)
    if not user.get("is_paid"):
        new_quota = use_free_quota(request.api_user_id)
    else:
        new_quota = user["free_quota"]

    analysis_id = save_analysis(
        user_id=request.api_user_id,
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

    return jsonify({
        "analysis_id": analysis_id,
        "result": result,
        "ats": ats_result,
        "quota_remaining": new_quota
    })


# -- Payment routes (API v1) ---------------------------------------

@app.route("/api/v1/create-order", methods=["POST"])
@api_login_required
def api_v1_create_order():
    plan_type = (request.get_json(silent=True) or request.form).get("plan_type", "").strip()
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


# -- New: Simulate payment (JWT auth, extracted from session route) -

@app.route("/api/v1/payment/simulate/<order_no>", methods=["POST"])
@api_login_required
def api_v1_simulate_payment(order_no):
    order = get_order(order_no)
    if not order:
        return jsonify({"error": "订单不存在"}), 404
    if order["user_id"] != request.api_user_id:
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
                (plan["quota"], request.api_user_id))
    db2.commit()
    db2.close()

    return jsonify({"status": "paid", "order_no": order_no, "plan_type": order["plan_type"]})


# -- Alipay notification (no auth, called by Alipay server) --------

@app.route("/api/payment/notify", methods=["POST"])
def api_payment_notify():
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


# -- Status page ---------------------------------------------------

@app.route("/")
def backend_status():
    db = get_db()

    # Stats
    total_users = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    paid_users = db.execute("SELECT COUNT(*) as c FROM users WHERE is_paid=1").fetchone()["c"]
    total_analyses = db.execute("SELECT COUNT(*) as c FROM analyses").fetchone()["c"]
    today_analyses = db.execute("SELECT COUNT(*) as c FROM analyses WHERE date(created_at)=date('now')").fetchone()["c"]
    total_orders = db.execute("SELECT COUNT(*) as c FROM orders WHERE status='paid'").fetchone()["c"]
    revenue = db.execute("SELECT COALESCE(SUM(amount),0) as c FROM orders WHERE status='paid'").fetchone()["c"]
    avg_score = db.execute("SELECT ROUND(AVG(overall_score),1) as c FROM analyses WHERE overall_score IS NOT NULL").fetchone()["c"] or 0
    today_users = db.execute("SELECT COUNT(*) as c FROM users WHERE date(created_at)=date('now')").fetchone()["c"]

    # Score distribution
    dist = db.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN overall_score BETWEEN 0 AND 19 THEN 1 ELSE 0 END),0) as s0,
            COALESCE(SUM(CASE WHEN overall_score BETWEEN 20 AND 39 THEN 1 ELSE 0 END),0) as s20,
            COALESCE(SUM(CASE WHEN overall_score BETWEEN 40 AND 59 THEN 1 ELSE 0 END),0) as s40,
            COALESCE(SUM(CASE WHEN overall_score BETWEEN 60 AND 79 THEN 1 ELSE 0 END),0) as s60,
            COALESCE(SUM(CASE WHEN overall_score BETWEEN 80 AND 100 THEN 1 ELSE 0 END),0) as s80
        FROM analyses WHERE overall_score IS NOT NULL
    """).fetchone()
    score_bars = [
        ("0-19", dist["s0"], "#ef4444"),
        ("20-39", dist["s20"], "#f59e0b"),
        ("40-59", dist["s40"], "#eab308"),
        ("60-79", dist["s60"], "#22c55e"),
        ("80-100", dist["s80"], "#10b981"),
    ]
    max_count = max(b[1] for b in score_bars) or 1

    # Recent users
    recent_users = db.execute(
        "SELECT username, realname, is_paid, created_at FROM users ORDER BY created_at DESC LIMIT 8"
    ).fetchall()

    # Recent analyses
    recent_analyses = db.execute("""
        SELECT a.overall_score, a.resume_filename, a.created_at, u.username
        FROM analyses a JOIN users u ON a.user_id=u.id
        ORDER BY a.created_at DESC LIMIT 8
    """).fetchall()

    # Daily trend (last 7 days)
    daily = db.execute("""
        SELECT date(created_at) as d,
               COUNT(*) as cnt,
               ROUND(AVG(overall_score),1) as avg_s
        FROM analyses
        WHERE created_at >= date('now','-6 days')
        GROUP BY date(created_at)
        ORDER BY d
    """).fetchall()
    max_daily = max((r["cnt"] for r in daily), default=1)

    # Payment trend
    pay_daily = db.execute("""
        SELECT date(paid_at) as d, COUNT(*) as cnt, SUM(amount)/100.0 as amount
        FROM orders WHERE status='paid' AND paid_at >= date('now','-6 days')
        GROUP BY date(paid_at) ORDER BY d
    """).fetchall()
    max_pay = max((r["cnt"] for r in pay_daily), default=1)

    db.close()

    # -- Render helpers --
    def stat_card(label, value, color="#22c55e"):
        return f'<div style="background:#1e293b;border-radius:10px;padding:16px 20px;text-align:center"><div style="color:#64748b;font-size:.78rem;margin-bottom:4px">{label}</div><div style="color:{color};font-size:1.6rem;font-weight:800">{value}</div></div>'

    def bar_row(label, count, color, max_val):
        pct = round(count / max_val * 100) if max_val else 0
        return f'<tr><td style="color:#94a3b8;font-size:.8rem;width:60px">{label}</td><td style="width:100%;padding:4px 8px"><div style="background:#334155;border-radius:4px;height:18px;overflow:hidden"><div style="background:{color};height:100%;width:{pct}%;border-radius:4px;transition:width .5s"></div></div></td><td style="color:#e2e8f0;font-size:.8rem;font-weight:700;text-align:right;width:40px">{count}</td></tr>'

    def spark_bars(rows, key, max_val, color="#4f6ef7"):
        if not rows:
            return '<span style="color:#475569;font-size:.75rem">暂无数据</span>'
        bars = ""
        for r in rows:
            h = round(r[key] / max_val * 40) if max_val else 0
            d = r["d"][-5:] if r["d"] else "-"
            bars += f'<div style="display:flex;align-items:center;gap:4px;margin-bottom:2px"><span style="color:#475569;font-size:.65rem;width:38px;text-align:right">{d}</span><div style="background:#334155;border-radius:2px;height:12px;flex:1;overflow:hidden"><div style="background:{color};height:100%;width:{"{:.0f}".format(r[key]/max_val*100) if max_val else 0}%;border-radius:2px"></div></div><span style="color:#94a3b8;font-size:.65rem;width:28px;text-align:right">{r[key]}</span></div>'
        return bars

    # -- Build HTML --
    stats_html = "".join([
        stat_card("总用户", total_users, "#4f6ef7"),
        stat_card("今日新增用户", today_users, "#a78bfa"),
        stat_card("付费用户", paid_users, "#f59e0b"),
        stat_card("总分析次数", total_analyses, "#22c55e"),
        stat_card("今日分析", today_analyses, "#10b981"),
        stat_card("成功订单", total_orders, "#f59e0b"),
        stat_card("收入", f"¥{revenue/100:.2f}", "#ef4444"),
        stat_card("平均评分", avg_score, "#4f6ef7"),
    ])

    score_rows = "".join(bar_row(*b, max_count) for b in score_bars)

    user_rows = "".join(
        f'<tr><td style="color:#e2e8f0;font-weight:600">{u["username"]}</td><td style="color:#94a3b8">{u["realname"]}</td><td style="color:{"#22c55e" if u["is_paid"] else "#64748b"}">{"付费" if u["is_paid"] else "免费"}</td><td style="color:#64748b;font-size:.8rem">{u["created_at"][:16] if u["created_at"] else "-"}</td></tr>'
        for u in recent_users
    )

    analysis_rows = "".join(
        f'<tr><td style="color:#e2e8f0">{a["username"]}</td><td style="color:#94a3b8;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{a["resume_filename"] or "-"}</td><td style="color:{"#22c55e" if (a["overall_score"] or 0) >= 60 else "#f59e0b" if (a["overall_score"] or 0) >= 40 else "#ef4444"};font-weight:700">{a["overall_score"] or "-"}</td><td style="color:#64748b;font-size:.8rem">{a["created_at"][:16] if a["created_at"] else "-"}</td></tr>'
        for a in recent_analyses
    )

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>简历优化 API 服务 · 数据看板</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0b1121; color:#e2e8f0; font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif; padding:32px; min-height:100vh; }}
h1 {{ font-size:1.3rem; color:#fff; }}
h2 {{ font-size:1rem; color:#cbd5e1; margin-bottom:12px; }}
a {{ color:#4f6ef7; text-decoration:none; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ text-align:left; color:#64748b; font-size:.78rem; font-weight:500; padding:8px 10px; border-bottom:1px solid #1e293b; }}
td {{ padding:8px 10px; border-bottom:1px solid #0f172a; font-size:.85rem; }}
tr:hover td {{ background:rgba(79,110,247,.05); }}
.card {{ background:#111827; border-radius:12px; padding:20px; border:1px solid #1e293b; }}
.stats-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:12px; margin-bottom:24px; }}
.panels {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:24px; }}
@media(max-width:768px){{ .panels{{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>

<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:24px">
  <div>
    <h1>简历优化分析平台 <span style="color:#22c55e;font-size:.9rem;font-weight:400">API 后端 · 数据看板</span></h1>
    <p style="color:#475569;font-size:.78rem;margin-top:4px">端口 5002 · JWT 认证 · <span style="color:#22c55e">●</span> 运行中</p>
  </div>
  <a href="http://127.0.0.1:5001" style="background:#4f6ef7;color:#fff;padding:8px 20px;border-radius:8px;font-size:.85rem;font-weight:600">打开前台 →</a>
</div>

<div class="stats-grid">{stats_html}</div>

<div class="panels">
  <div class="card">
    <h2>📊 评分分布</h2>
    <table><tbody>{score_rows}</tbody></table>
  </div>
  <div class="card">
    <h2>📈 7天分析趋势（次数）</h2>
    {spark_bars(daily, "cnt", max_daily, "#4f6ef7")}
    <div style="margin-top:20px">
      <h2 style="margin-bottom:8px">💰 7天支付趋势（笔数）</h2>
      {spark_bars(pay_daily, "cnt", max_pay, "#f59e0b")}
    </div>
  </div>
</div>

<div class="panels">
  <div class="card">
    <h2>👤 最近注册用户</h2>
    <table><thead><tr><th>账号</th><th>昵称</th><th>状态</th><th>注册时间</th></tr></thead><tbody>{user_rows}</tbody></table>
  </div>
  <div class="card">
    <h2>📝 最近分析记录</h2>
    <table><thead><tr><th>用户</th><th>简历</th><th>评分</th><th>时间</th></tr></thead><tbody>{analysis_rows}</tbody></table>
  </div>
</div>

<details style="margin-top:24px;cursor:pointer">
  <summary style="color:#64748b;font-size:.9rem;margin-bottom:12px">📋 API 端点列表（共 17 个）</summary>
  <table style="margin-top:8px">
    <thead><tr><th>方法</th><th>路径</th><th>说明</th></tr></thead>
    <tbody>
      <tr><td style="color:#22c55e;font-weight:700">GET</td><td style="font-family:monospace;color:#e2e8f0">/health</td><td style="color:#94a3b8">健康检查</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">POST</td><td style="font-family:monospace;color:#e2e8f0">/api/v1/credentials-login</td><td style="color:#94a3b8">账号密码登录</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">POST</td><td style="font-family:monospace;color:#e2e8f0">/api/v1/register</td><td style="color:#94a3b8">注册</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">POST</td><td style="font-family:monospace;color:#e2e8f0">/api/v1/wx-login</td><td style="color:#94a3b8">微信登录</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">GET</td><td style="font-family:monospace;color:#e2e8f0">/api/v1/user/info</td><td style="color:#94a3b8">用户信息</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">POST</td><td style="font-family:monospace;color:#e2e8f0">/api/v1/user/bind</td><td style="color:#94a3b8">绑定手机/邮箱</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">POST</td><td style="font-family:monospace;color:#e2e8f0">/api/v1/analyze</td><td style="color:#94a3b8">简历分析</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">POST</td><td style="font-family:monospace;color:#e2e8f0">/api/v1/generate</td><td style="color:#94a3b8">AI 生成简历</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">POST</td><td style="font-family:monospace;color:#e2e8f0">/api/v1/ats-check</td><td style="color:#94a3b8">ATS 兼容性检查</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">POST</td><td style="font-family:monospace;color:#e2e8f0">/api/v1/targeted-optimize</td><td style="color:#94a3b8">JD 定向优化</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">GET</td><td style="font-family:monospace;color:#e2e8f0">/api/v1/history</td><td style="color:#94a3b8">历史记录</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">GET</td><td style="font-family:monospace;color:#e2e8f0">/api/v1/result/&lt;id&gt;</td><td style="color:#94a3b8">分析详情</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">POST</td><td style="font-family:monospace;color:#e2e8f0">/api/v1/create-order</td><td style="color:#94a3b8">创建支付订单</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">GET</td><td style="font-family:monospace;color:#e2e8f0">/api/v1/payment/status/&lt;id&gt;</td><td style="color:#94a3b8">订单状态</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">POST</td><td style="font-family:monospace;color:#e2e8f0">/api/v1/payment/simulate/&lt;id&gt;</td><td style="color:#94a3b8">模拟支付</td></tr>
      <tr><td style="color:#22c55e;font-weight:700">POST</td><td style="font-family:monospace;color:#e2e8f0">/api/payment/notify</td><td style="color:#94a3b8">支付宝回调</td></tr>
    </tbody>
  </table>
</details>

<p style="color:#334155;font-size:.75rem;margin-top:32px;text-align:center">数据实时刷新 · 刷新页面更新</p>

</body></html>"""


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# -- Main ----------------------------------------------------------

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("BACKEND_PORT", 5002))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("DEBUG", "0") == "1"

    try:
        from waitress import serve
        print(f"Backend API server: http://127.0.0.1:{port}")
        serve(app, host=host, port=port, threads=4)
    except ImportError:
        app.run(host=host, port=port, debug=True)
