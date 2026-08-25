"""飞书推送：优先 webhook 发文本；配置了 app 凭证则上传图片到会话"""
import requests
from app import config, db


def _webhook() -> str:
    """Webhook 可在工作台"配置中心"填写（存 config_kv），未填则退回代码级配置"""
    row = db.get_conn().execute("SELECT value FROM config_kv WHERE key='lark_webhook'").fetchone()
    return (row["value"] if row else "") or config.LARK_WEBHOOK


def send_text(text: str) -> dict:
    """webhook 发送文本消息（自定义机器人）"""
    url = _webhook()
    if not url:
        return {"ok": False, "reason": "未配置飞书webhook(LARK_WEBHOOK)"}
    r = requests.post(url, json={
        "msg_type": "text",
        "content": {"text": text},
    }, timeout=10)
    return {"ok": r.ok, "data": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text}


def send_image_message(image_path: str, caption: str = "") -> dict:
    """配置了 app 凭证 + chat_id 时，上传图片并发送图文消息"""
    if not (config.LARK_APP_ID and config.LARK_APP_SECRET and config.LARK_CHAT_ID):
        return {"ok": False, "reason": "未配置飞书APP凭证(LARK_APP_ID/SECRET/CHAT_ID)"}
    token = _tenant_token()
    if not token:
        return {"ok": False, "reason": "获取tenant_token失败"}
    try:
        with open(image_path, "rb") as f:
            data = f.read()
    except OSError:
        return {"ok": False, "reason": "图片文件不存在"}
    up = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/images",
        headers={"Authorization": f"Bearer {token}"},
        data={"image_type": "message"},
        files={"image": (image_path.split("/")[-1], data,
                         "image/png" if image_path.endswith(".png") else "image/jpeg")},
        timeout=20)
    upj = up.json()
    image_key = upj.get("data", {}).get("image_key")
    if not image_key:
        return {"ok": False, "reason": f"上传图片失败: {upj}"}
    msg_content = {
        "post": {"zh_cn": {"title": caption or "发货推送",
                           "content": [[{"tag": "img", "image_key": image_key}]]}},
    }
    send = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"receive_id": config.LARK_CHAT_ID, "msg_type": "post", "content": msg_content},
        timeout=10)
    try:
        out = send.json()
    except Exception:
        out = {"raw": send.text}
    return {"ok": send.ok, "data": out}


def _tenant_token():
    r = requests.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                      json={"app_id": config.LARK_APP_ID, "app_secret": config.LARK_APP_SECRET}, timeout=10)
    return r.json().get("tenant_access_token")