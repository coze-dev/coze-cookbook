import hashlib
import json
import logging
import os
import secrets
import time
from functools import wraps

from cozepy import Coze, TokenAuth
from dotenv import load_dotenv
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    Response,
    jsonify,
)
from requests_oauthlib import OAuth2Session

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.token_store = {}

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# OAuth 配置
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
CONNECTOR_CLIENT_ID = os.getenv("CONNECTOR_CLIENT_ID")  # 渠道分配给扣子的 client_id
CONNECTOR_CLIENT_SECRET = os.getenv(
    "CONNECTOR_CLIENT_SECRET"
)  # 渠道分配给扣子的 client_secret
CONNECTOR_USER_ID = os.getenv("CONNECTOR_USER_ID")  # 渠道的用户 uid
CONNECTOR_USER_NAME = os.getenv("CONNECTOR_USER_NAME")  # 渠道的用户 name
COZE_CALLBACK_TOKEN = os.getenv("COZE_CALLBACK_TOKEN")  # 扣子回调 token
AUTHORIZE_URL = "https://www.coze.cn/api/oauth/authorize"
TOKEN_URL = "https://www.coze.cn/api/oauth/token"
REDIRECT_URI = "http://localhost:5000/callback"

# 存储 bot 信息的文件
BOTS_FILE = "bots.json"


def log_request_response(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 记录请求信息
        req_data = {
            "method": request.method,
            "url": request.url,
            "headers": dict(request.headers),
            "args": dict(request.args),
            "form": dict(request.form),
            "json": request.get_json(silent=True),
        }
        logger.debug(f"Request: {json.dumps(req_data, ensure_ascii=False)}")

        # 执行原始函数
        response = f(*args, **kwargs)

        # 记录响应信息
        if isinstance(response, (Response, str)):
            code = response.status_code if isinstance(response, Response) else 200
            data = response.get_json() if isinstance(response, Response) else response
            logger.debug(f"Response: {code}, {json.dumps(data, ensure_ascii=False)}")
        elif (
            isinstance(response, tuple)
            and len(response) == 2
            and isinstance(response[0], Response)
            and isinstance(response[1], int)
        ):
            # 如果 response 是 (Response, int) 的 tuple 类型
            code = response[1]
            data = response[0].get_json()
            logger.debug(f"Response: {code}, {json.dumps(data, ensure_ascii=False)}")

        return response

    return decorated_function


def load_bots():
    if os.path.exists(BOTS_FILE):
        with open(BOTS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_bot(bot_id, bot_name):
    retry_count = 10
    while retry_count > 0:
        try:
            bots = load_bots()
            bots[bot_id] = bot_name
            with open(BOTS_FILE, "w") as f:
                json.dump(bots, f)
            return
        except Exception as e:
            logger.warning(f"保存 bot 数据失败，正在重试... : {e}")


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


@app.route("/")
@log_request_response
def index():
    return render_template("index.html")


@app.route("/logout")
@log_request_response
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/callback")
@log_request_response
def callback():
    coze = OAuth2Session(
        CLIENT_ID, redirect_uri=REDIRECT_URI, state=session.get("oauth_state")
    )
    token = coze.fetch_token(
        TOKEN_URL, client_secret=CLIENT_SECRET, authorization_response=request.url
    )
    session["oauth_token"] = token
    return redirect(url_for("bots"))


@app.route("/bots")
@log_request_response
def bots():
    bots = load_bots()
    # bots map to list
    bots_list = [
        {"bot_id": bot_id, "bot_name": bot_name} for bot_id, bot_name in bots.items()
    ]
    return render_template("bots.html", bots=bots_list)


@app.route("/chat/<bot_id>")
@log_request_response
def chat(bot_id):
    bots = load_bots()
    bots_list = [
        {"bot_id": bot_id, "bot_name": bot_name} for bot_id, bot_name in bots.items()
    ]
    bot = next((b for b in bots_list if b["bot_id"] == bot_id), None)
    if not bot:
        return redirect(url_for("bots"))
    return render_template("chat.html", bot=bot)


@app.route("/chat/<bot_id>/send", methods=["POST"])
@log_request_response
def chat_send(bot_id):
    bots = load_bots()
    bots_list = [
        {"bot_id": bot_id, "bot_name": bot_name} for bot_id, bot_name in bots.items()
    ]
    bot = next((b for b in bots_list if b["bot_id"] == bot_id), None)
    if not bot:
        return "Bot not found", 404

    message = request.json.get("message")
    if not message:
        return "No message provided", 400

    token = session.get("oauth_token")
    if not token:
        return "Not authenticated", 401

    coze = Coze(auth=TokenAuth(token["access_token"]))

    def generate():
        for chunk in coze.chat.stream(bot_id=bot_id, message=message):
            yield f"data: {json.dumps(chunk)}\n\n"

    return Response(generate(), mimetype="text/event-stream")


@app.route("/oauth/authorize", methods=["GET", "POST"])
@log_request_response
def oauth_authorize():
    if request.method == "GET":
        # 验证必要参数
        client_id = request.args.get("client_id")
        redirect_uri = request.args.get("redirect_uri")
        response_type = request.args.get("response_type")
        state = request.args.get("state") or ""

        if not all([client_id, redirect_uri, response_type]):
            return jsonify({"code": 400, "message": "缺少必要参数"}), 400

        if client_id != CONNECTOR_CLIENT_ID:
            return jsonify({"code": 401, "message": "client_id 无效"}), 401

        if response_type != "code":
            return jsonify({"code": 400, "message": "response_type 必须为 code"}), 400

        return render_template(
            "authorize.html",
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            state=state,
        )
    else:
        # 处理授权确认
        client_id = request.form.get("client_id")
        redirect_uri = request.form.get("redirect_uri")
        state = request.form.get("state")
        action = request.form.get("action")

        if action == "deny":
            return render_template("error.html")

        # 生成授权码
        code = secrets.token_urlsafe(16)

        # 在实际应用中，这里应该将授权码与用户信息关联并存储

        return redirect(f"{redirect_uri}?code={code}&state={state}")


@app.route("/oauth/token", methods=["POST"])
@log_request_response
def oauth_token():
    data = request.json
    if not data:
        logger.warning("OAuth token 请求缺少请求体")
        return jsonify({"code": 400, "message": "请求参数错误"}), 400

    # 验证必要参数
    required_fields = ["client_id", "client_secret", "code", "grant_type"]
    for field in required_fields:
        if field not in data:
            logger.warning(f"OAuth token 请求缺少必要参数: {field}")
            return jsonify({"code": 400, "message": f"缺少必要参数: {field}"}), 400

    # 验证 client_id 和 client_secret
    if (
        data["client_id"] != CONNECTOR_CLIENT_ID
        or data["client_secret"] != CONNECTOR_CLIENT_SECRET
    ):
        logger.error(f"无效的 client_id 或 client_secret: {data['client_id']}")
        return jsonify({"code": 401, "message": "client_id 或 client_secret 无效"}), 401

    # 验证 grant_type
    if data["grant_type"] != "authorization_code":
        logger.warning(f"无效的 grant_type: {data['grant_type']}")
        return jsonify(
            {"code": 400, "message": "grant_type 必须为 authorization_code"}
        ), 400

    # 生成 access_token
    access_token = secrets.token_urlsafe(32)
    logger.debug(f"为 client_id {data['client_id']} 生成新的 access_token")

    # 将 token 存储到内存中
    app.token_store[access_token] = int(time.time()) + 3600
    logger.info("成功生成并存储 access_token，过期时间为 3600 秒")

    return jsonify(
        {"access_token": access_token, "token_type": "bearer", "expires_in": 3600}
    )


@app.route("/oauth/user", methods=["GET"])
@log_request_response
def oauth_user():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"code": 401, "message": "未提供有效的访问令牌"}), 401

    # 验证 access_token
    access_token = auth_header.split(" ")[1]
    if (
        access_token not in app.token_store
        or app.token_store[access_token] < time.time()
    ):
        return jsonify({"code": 401, "message": "访问令牌无效"}), 401

    # 在实际应用中，这里应该验证 access_token 的有效性
    # 并根据 access_token 获取对应的用户信息
    return jsonify({"id": CONNECTOR_USER_ID, "name": CONNECTOR_USER_NAME})


@app.route("/coze/callback", methods=["POST"])
@log_request_response
def coze_callback():
    # 获取签名和时间戳
    signature = request.headers.get("X-Coze-Signature")
    timestamp = request.headers.get("X-Coze-Timestamp")
    nonce = request.headers.get("X-Coze-Nonce")

    if not signature or not timestamp:
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


if __name__ == "__main__":
    app.run(debug=True)
