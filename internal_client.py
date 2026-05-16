import os
import json
import requests
from datetime import datetime, timedelta
import jwt

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:5002").rstrip("/")

_JWT_SECRET = os.environ.get("JWT_SECRET", "")
if not _JWT_SECRET:
    # Fallback: read from shared secret file (same as Flask app)
    _secret_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")
    if os.path.exists(_secret_path):
        with open(_secret_path, "rb") as f:
            _JWT_SECRET = f.read().decode("utf-8", errors="replace")
    if not _JWT_SECRET:
        _JWT_SECRET = os.environ.get("SECRET_KEY", os.urandom(24).hex())

JWT_SECRET = _JWT_SECRET
JWT_EXPIRY_MINUTES = 5  # short-lived internal tokens


def _make_internal_token(user_id):
    exp = datetime.utcnow() + timedelta(minutes=JWT_EXPIRY_MINUTES)
    return jwt.encode({"user_id": user_id, "exp": exp}, JWT_SECRET, algorithm="HS256")


def _headers(user_id):
    return {"Authorization": f"Bearer {_make_internal_token(user_id)}"}


def backend_post(path, data=None, files=None, user_id=None):
    """POST to backend. Returns (parsed_json, status_code)."""
    url = f"{BACKEND_URL}{path}"
    headers = _headers(user_id) if user_id else {}
    try:
        if files:
            resp = requests.post(url, data=data, files=files, headers=headers, timeout=120)
        elif data:
            resp = requests.post(url, data=data, headers=headers, timeout=120)
        else:
            resp = requests.post(url, headers=headers, timeout=120)
        try:
            return resp.json(), resp.status_code
        except ValueError:
            return {"error": resp.text or "后端返回异常"}, resp.status_code
    except requests.exceptions.ConnectionError:
        return {"error": "后端服务不可用，请稍后重试"}, 503
    except requests.exceptions.Timeout:
        return {"error": "后端服务超时，请重试"}, 504
    except Exception as e:
        return {"error": f"请求异常: {str(e)}"}, 500


def backend_get(path, user_id=None):
    """GET from backend. Returns (parsed_json, status_code)."""
    url = f"{BACKEND_URL}{path}"
    headers = _headers(user_id) if user_id else {}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        try:
            return resp.json(), resp.status_code
        except ValueError:
            return {"error": resp.text or "后端返回异常"}, resp.status_code
    except requests.exceptions.ConnectionError:
        return {"error": "后端服务不可用，请稍后重试"}, 503
    except requests.exceptions.Timeout:
        return {"error": "后端服务超时，请重试"}, 504
    except Exception as e:
        return {"error": f"请求异常: {str(e)}"}, 500
