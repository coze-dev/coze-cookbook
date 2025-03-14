import hashlib
import json
import logging
import os
import time
from functools import wraps

import httpx
from cozepy import (
    Coze,
    JWTAuth,
    JWTOAuthApp,
    load_oauth_app_from_config,
    COZE_CN_BASE_URL,
    PKCEOAuthApp,
)
from dotenv import load_dotenv
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    Response,
    jsonify,
)

# 加载 .env 文件, 用户可以自行修改 .env
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.token_store = {}

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 渠道 id
CONNECTOR_ID = os.getenv("CONNECTOR_ID")  # 渠道 id
CONNECTOR_PKCE_CLIENT_ID = os.getenv("CONNECTOR_PKCE_CLIENT_ID")  # 渠道 pkce client id
# OAuth 配置
CONNECTOR_CLIENT_ID = os.getenv(
    "CONNECTOR_CLIENT_ID"
)  # 渠道分配给扣子的 oauth client_id
CONNECTOR_CLIENT_SECRET = os.getenv(
    "CONNECTOR_CLIENT_SECRET"
)  # 渠道分配给扣子的 oauth client_secret
CONNECTOR_USER_ID = os.getenv("CONNECTOR_USER_ID")  # oauth 后渠道的用户 uid
CONNECTOR_USER_NAME = os.getenv("CONNECTOR_USER_NAME")  # oauth 后渠道的用户 name
# 扣子的配置
COZE_CALLBACK_TOKEN = os.getenv("COZE_CALLBACK_TOKEN")  # 扣子回调 token
# 服务静态配置
BOTS_FILE = "bots.json"  # 存储 bot 信息的文件
COZE_OAUTH_CONFIG_PATH = "coze_oauth_config.json"  # jwt oauth 配置文件


# 基于配置文件加载 coze oauth jwt app
def load_coze_oauth_app(config_path) -> JWTOAuthApp:
    try:
        with open(config_path, "r") as file:
            config = json.loads(file.read())
        return load_oauth_app_from_config(config)  # type: ignore
    except FileNotFoundError:
        raise Exception("配置不存在")
    except Exception as e:
        raise Exception(f"加载 OAuth 失败: {str(e)}")


# 日志装饰器
def log_request_response(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 记录请求信息
        req_data = {
            "method": request.method,
            "url": request.url,
            "args": dict(request.args),
            "form": dict(request.form),
            "json": request.get_json(silent=True),
        }
        logger.info(f"Request: {json.dumps(req_data, ensure_ascii=False)}")

        # 执行原始函数
        response = f(*args, **kwargs)

        # 记录响应信息
        if (
            isinstance(response, tuple)
            and len(response) == 2
            and isinstance(response[0], Response)
            and isinstance(response[1], int)
        ):
            # 如果 response 是 (Response, int) 的 tuple 类型
            code = response[1]
            data = response[0].get_json()
            logger.info(f"Response: {code}, {json.dumps(data, ensure_ascii=False)}")

        return response

    return decorated_function


# 渠道的扣子客户端和 oauth 客户端
connector_oauth_app = load_coze_oauth_app(COZE_OAUTH_CONFIG_PATH)
connector_pkce_oauth_app = PKCEOAuthApp(
    client_id=CONNECTOR_PKCE_CLIENT_ID, base_url=COZE_CN_BASE_URL
)
connector_coze = Coze(
    auth=JWTAuth(oauth_app=connector_oauth_app, ttl=86399),
    base_url=COZE_CN_BASE_URL,
)


# 从 bots.json 加载已经发布的 bot 数据
def load_bots():
    if os.path.exists(BOTS_FILE):
        with open(BOTS_FILE, "r") as f:
            data = json.load(f)
            return [
                {"bot_id": bot_id, "bot_name": info.get("bot_name", "")}
                for bot_id, info in data.items()
            ]

    return []


# 从 bots.json 加载已经发布的 bot 数据, 并且拉取头像等数据
def load_bot_and_info():
    bots = load_bots()
    res = []
    for bot in bots:
        bot_info = connector_coze.bots.retrieve(bot_id=bot["bot_id"])

        res.append(
            {
                "bot_id": bot["bot_id"],
                "bot_name": bot["bot_name"],
                "bot_description": bot_info.description,
                "bot_icon_url": bot_info.icon_url,
            }
        )
    return res


# 将 bot 数据保存到本地文件
def save_bot(bot_id, bot_name):
    retry_count = 10
    while retry_count > 0:
        try:
            bots = load_bots()
            bots = {bot["bot_id"]: bot for bot in bots}
            bots[bot_id] = {
                "bot_name": bot_name,
            }
            with open(BOTS_FILE, "w") as f:
                json.dump(bots, f)
            return
        except Exception as e:
            logger.warning(f"保存 bot 数据失败，正在重试... : {e}")


def update_coze_device(connector_id: str, token: str, device_id: str, device_name: str):
    url = f"https://api.coze.cn/v1/connectors/{connector_id}/user_configs"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = {
        "configs": [
            {"key": "device_id", "enums": [{"value": device_id, "label": device_name}]}
        ]
    }

    client = httpx.Client()
    response = client.post(url, json=data, headers=headers)
    if response.status_code >= 400:
        logid = response.headers.get("x-tt-logid")
        raise Exception(f"同步设备失败: {logid}, resp: {response.text}")


def get_coze_user_info(pkce_token: str):
    url = "https://api.coze.cn/v1/users/me"
    headers = {
        "Authorization": f"Bearer {pkce_token}",
    }
    client = httpx.Client()
    response = client.get(url, headers=headers)
    response.raise_for_status()
    # user_id, user_name, nick_name, avatar_url
    return response.json()["data"]


# 计算扣子 bot 发布回调签名
def gen_coze_callback_signature(
    nonce: str, timestamp: str, body: str, token: str
) -> str:
    """
    docs: https://www.coze.cn/open/docs/guides/configure_callback_message#bba62e6c
    """
    # 按照指定顺序拼接字符串
    raw_str = timestamp + nonce + token + body

    # 使用 SHA1 计算哈希值
    hash_obj = hashlib.sha1()
    hash_obj.update(raw_str.encode("utf-8"))

    # 返回十六进制格式的签名
    return hash_obj.hexdigest()


# 首页路由, 302 到 bots 列表页
@app.route("/")
@log_request_response
def index():
    return redirect(url_for("bots"))


# bots 列表页, 展示所有已经发布的 bots 列表, 支持和 bot 聊天
@app.route("/bots")
@log_request_response
def bots():
    bots = load_bot_and_info()
    token = connector_oauth_app.get_access_token(ttl=86399).access_token
    return render_template("bots.html", bots=bots, token=token)


# 在扣子发布智能体到渠道的时候, 扣子会给本接口推送一条 json 数据, 包含 bot 相关信息
@app.route("/coze/callback", methods=["POST"])
@log_request_response
def coze_callback():
    # 获取签名和时间戳
    signature = request.headers.get("X-Coze-Signature")
    timestamp = request.headers.get("X-Coze-Timestamp")
    nonce = request.headers.get("X-Coze-Nonce")

    if not signature or not timestamp or not nonce:
        return jsonify({"code": 400, "message": "缺少签名或时间戳"}), 400

    # 获取请求体
    body = request.get_data().decode("utf-8")
    if not body:
        return jsonify({"code": 400, "message": "请求体为空"}), 400

    expected_signature = gen_coze_callback_signature(
        nonce, timestamp, body, COZE_CALLBACK_TOKEN
    )
    if signature != expected_signature:
        return jsonify({"code": 401, "message": "签名验证失败"}), 401

    event = json.loads(body)
    event_type = event.get("header", {}).get("event_type", "")
    # user_id = event.get("event", {}).get("user_id", "")
    # connector_user_id = event.get("event", {}).get("connector_user_id", "")
    bot_id = str(event.get("event", {}).get("bot_id", ""))
    bot_name = event.get("event", {}).get("bot_name", "")

    if event_type != "bot.published":
        return jsonify({"code": 400, "message": f"不支持处理事件 {event_type}"}), 400

    # audit_status: 1: 审核中；2: 通过；3: 拒绝
    if "非法" in bot_name or "违禁" in bot_name or "敏感" in bot_name:
        return jsonify({"audit": {"audit_status": 3, "reason": "bot 名称非法"}}), 200
    if "审核中" in bot_name:
        return jsonify({"audit": {"audit_status": 1, "reason": ""}}), 200

    save_bot(bot_id, bot_name)
    return jsonify({"audit": {"audit_status": 2, "reason": ""}}), 200


# 使用 pkce 授权获取到用户的 AccessToken
@app.route("/pkce_callback")
@log_request_response
def pkce_callback():
    redirect_uri = request.base_url
    code = request.args.get("code")
    code_verifier = request.args.get("state")
    if not code or not code_verifier:
        return jsonify({"message": "缺少授权码或 state"}), 400

    try:
        # 获取 token
        token = connector_pkce_oauth_app.get_access_token(
            redirect_uri=redirect_uri, code=code, code_verifier=code_verifier
        )
        # 创建响应对象并设置 cookie
        resp = redirect(url_for("devices") + "?auth_success=true")
        resp.set_cookie(
            "coze_pkce_access_token",
            token.access_token,
            max_age=token.expires_in - int(time.time()),
            httponly=True,
            secure=True,
        )
        return resp
    except Exception as e:
        return jsonify({"message": f"PKCE 授权失败: {str(e)}"}), 500


# 用 cookie 中的 coze_pkce_access_token 获取用户信息
@app.route("/users_me")
@log_request_response
def users_me():
    # 从 cookie 中获取 token
    token = request.cookies.get("coze_pkce_access_token")
    if not token:
        return jsonify({"message": "未登录"}), 401

    try:
        # 调用扣子 API 获取用户信息
        user_info = get_coze_user_info(token)
        return jsonify(user_info), 200
    except Exception as e:
        return jsonify({"message": f"获取用户信息失败: {str(e)}"}), 500


@app.route("/devices")
@log_request_response
def devices():
    return render_template("devices.html", client_id=CONNECTOR_PKCE_CLIENT_ID)


# 通过调用扣子接口, 将设备 id 同步到扣子, 用户可以在发布页面点击配置选择对应的设备 id
@app.route("/sync_device", methods=["POST"])
@log_request_response
def sync_device():
    data = request.get_json()
    if not data or "device_id" not in data or "device_name" not in data:
        return jsonify({"message": "缺少必要参数"}), 400

    device_id = data["device_id"]
    device_name = data["device_name"]

    # 从 cookie 中获取 token
    token = request.cookies.get("coze_pkce_access_token")
    if not token:
        return jsonify({"message": "未登录"}), 401

    try:
        # 调用扣子 API 同步设备信息
        update_coze_device(CONNECTOR_ID, token, device_id, device_name)
        return jsonify({"message": "设备同步成功"}), 200
    except Exception as e:
        return jsonify({"message": f"同步设备失败: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True)
