import os, logging, time
from datetime import datetime
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# -- Alipay (生产环境) --
ALIPAY_APP_ID = os.environ.get("ALIPAY_APP_ID", "")
ALIPAY_PRIVATE_KEY = os.environ.get("ALIPAY_PRIVATE_KEY", "")
ALIPAY_PUBLIC_KEY = os.environ.get("ALIPAY_PUBLIC_KEY", "")
ALIPAY_NOTIFY_URL = os.environ.get("ALIPAY_NOTIFY_URL", "")
ALIPAY_SANDBOX = os.environ.get("ALIPAY_SANDBOX", "false").lower() == "true"

# -- WeChat Pay (Native 扫码) --
WX_APPID = os.environ.get("WX_APPID", "")
WX_MCHID = os.environ.get("WX_MCHID", "")
WX_API_KEY = os.environ.get("WX_API_KEY", "")
WX_NOTIFY_URL = os.environ.get("WX_NOTIFY_URL", "")

GATEWAY = "https://openapi.alipaydev.com/gateway.do" if ALIPAY_SANDBOX else "https://openapi.alipay.com/gateway.do"

# ============ 新增多档定价 ============
# price: 展示价格
# amount: 分（支付宝最小单位）
# quota: 赠送次数（-1 = 无限）
PLANS = {
    "single":      {"name": "单次简历分析",   "price": 29.90,  "amount": 2900,  "quota": 1,    "desc": "一次完整ATS+JD分析"},
    "triple":      {"name": "5次分析包",      "price": 69.00,  "amount": 6900,  "quota": 5,    "desc": "5次分析包·省¥80"},
    "monthly":     {"name": "包月无限次",      "price": 39.00,  "amount": 3900,  "quota": -1,   "desc": "包月无限次"},
    "quarterly":   {"name": "季度畅享",        "price": 89.00,  "amount": 8900,  "quota": -1,   "desc": "季度畅享·省¥28"},
    "yearly":      {"name": "年度VIP",         "price": 199.00, "amount": 19900, "quota": -1,   "desc": "年度VIP·优先队列"},
    "interview":   {"name": "AI面试模拟",      "price": 19.90,  "amount": 1990,  "quota": 1,    "desc": "JD针对性面试题+评分"},
    "english":     {"name": "英文简历优化",     "price": 39.90,  "amount": 3990,  "quota": 1,    "desc": "中英双语简历+ATS优化"},
    "cover_letter":{"name": "求职信生成",      "price": 9.90,   "amount": 990,   "quota": 1,    "desc": "AI生成定制求职信"},
}


def _get_alipay_client():
    """Lazy-load the Alipay client (avoids import error if SDK not installed)."""
    try:
        from alipay import AliPay
    except ImportError:
        logger.error("alipay-sdk-python not installed. Run: pip install alipay-sdk-python")
        return None

    key = ALIPAY_PRIVATE_KEY
    pub = ALIPAY_PUBLIC_KEY

    if not key or not pub or not ALIPAY_APP_ID:
        logger.warning("Alipay keys not configured. Payment will use mock mode.")
        return None

    return AliPay(
        appid=ALIPAY_APP_ID,
        app_notify_url=ALIPAY_NOTIFY_URL,
        app_private_key_string=key,
        alipay_public_key_string=pub,
        sign_type="RSA2",
        debug=ALIPAY_SANDBOX,
    )


def generate_order_no():
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    rand = os.urandom(3).hex()
    return f"RV{ts}{rand}"


def create_qrcode(order_no, plan_type):
    """Create an order and return QR code payment URL (or error)."""
    plan = PLANS.get(plan_type)
    if not plan:
        return {"error": "无效的套餐类型"}

    alipay = _get_alipay_client()
    if not alipay:
        return {"error": "支付服务未配置，请联系管理员"}

    try:
        resp = alipay.api_alipay_trade_precreate(
            subject=plan["name"],
            out_trade_no=order_no,
            total_amount=plan["price"],
            timeout_express="15m",
        )
        logger.info("Alipay precreate response: %s", resp)

        if resp.get("code") == "10000":
            return {"qr_code": resp.get("qr_code", ""), "order_no": order_no}
        else:
            logger.error("Alipay error: %s", resp)
            return {"error": f"创建支付订单失败: {resp.get('msg', '请重试')}"}

    except Exception as e:
        logger.exception("Alipay API call failed")
        return {"error": f"支付服务异常: {str(e)}"}


def verify_notify(data, signature):
    """Verify Alipay async notification signature. Returns dict with trade info or None."""
    alipay = _get_alipay_client()
    if not alipay:
        return None

    try:
        ok = alipay.verify(data, signature)
        if not ok:
            return None

        trade_status = data.get("trade_status", "")
        if trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
            return {
                "order_no": data.get("out_trade_no", ""),
                "trade_no": data.get("trade_no", ""),
                "buyer_id": data.get("buyer_id", ""),
                "total_amount": data.get("total_amount", ""),
            }
        return None
    except Exception:
        logger.exception("Alipay notify verification failed")
        return None


def get_plan(plan_type):
    return PLANS.get(plan_type)


# ============ 微信支付 Native ============
def create_wxpay_qrcode(order_no, plan_type):
    """调用微信Native下单API，返回code_url（用户扫码）"""
    plan = PLANS.get(plan_type)
    if not plan:
        return {"error": "无效的套餐类型"}

    if not WX_APPID or not WX_MCHID or not WX_API_KEY:
        return {"error": "微信支付未配置"}

    import hashlib, xml.etree.ElementTree as ET
    import requests as req

    nonce_str = os.urandom(8).hex()
    total_fee = int(plan["amount"])  # 分
    params = {
        "appid": WX_APPID,
        "mch_id": WX_MCHID,
        "nonce_str": nonce_str,
        "body": plan["name"],
        "out_trade_no": order_no,
        "total_fee": str(total_fee),
        "spbill_create_ip": os.environ.get("SERVER_IP", "127.0.0.1"),
        "notify_url": WX_NOTIFY_URL,
        "trade_type": "NATIVE",
    }
    # 签名
    keys = sorted(params.keys())
    raw = "&".join(f"{k}={params[k]}" for k in keys) + f"&key={WX_API_KEY}"
    sign = hashlib.md5(raw.encode("utf-8")).hexdigest().upper()
    params["sign"] = sign

    xml_parts = ["<xml>"]
    for k, v in params.items():
        xml_parts.append(f"<{k}>{v}</{k}>")
    xml_parts.append("</xml>")
    xml_body = "".join(xml_parts)

    try:
        resp = req.post(
            "https://api.mch.weixin.qq.com/pay/unifiedorder",
            data=xml_body.encode("utf-8"),
            headers={"Content-Type": "text/xml"},
            timeout=10,
        )
        root = ET.fromstring(resp.content)
        return_code = root.findtext("return_code", "")
        result_code = root.findtext("result_code", "")

        if return_code == "SUCCESS" and result_code == "SUCCESS":
            code_url = root.findtext("code_url", "")
            return {"wx_code_url": code_url, "order_no": order_no}
        else:
            err_msg = root.findtext("err_code_des", "下单失败")
            logger.error("WxPay error: %s", resp.content)
            return {"error": f"微信支付下单失败: {err_msg}"}
    except Exception as e:
        logger.exception("WxPay API call failed")
        return {"error": f"微信支付服务异常: {str(e)}"}
