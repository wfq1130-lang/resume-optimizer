import os, logging, time
from datetime import datetime
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

ALIPAY_APP_ID = os.environ.get("ALIPAY_APP_ID", "")
ALIPAY_PRIVATE_KEY = os.environ.get("ALIPAY_PRIVATE_KEY", "")
ALIPAY_PUBLIC_KEY = os.environ.get("ALIPAY_PUBLIC_KEY", "")
ALIPAY_NOTIFY_URL = os.environ.get("ALIPAY_NOTIFY_URL", "")
ALIPAY_SANDBOX = os.environ.get("ALIPAY_SANDBOX", "true").lower() == "true"

GATEWAY = "https://openapi.alipaydev.com/gateway.do" if ALIPAY_SANDBOX else "https://openapi.alipay.com/gateway.do"

PLANS = {
    "single":  {"name": "单次简历分析", "price": 9.90, "amount": 990,   "quota": 1},
    "monthly": {"name": "包月无限次",   "price": 29.90, "amount": 2990, "quota": 9999},
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
