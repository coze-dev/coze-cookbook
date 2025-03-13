import json
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

# OAuth 配置
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
CONNECTOR_CLIENT_ID = os.getenv("CONNECTOR_CLIENT_ID")  # 渠道分配给扣子的 client_id
CONNECTOR_CLIENT_SECRET = os.getenv(
    "CONNECTOR_CLIENT_SECRET"
)  # 渠道分配给扣子的 client_secret
CONNECTOR_USER_ID = os.getenv("CONNECTOR_USER_ID")  # 渠道的用户 uid
CONNECTOR_USER_NAME = os.getenv("CONNECTOR_USER_NAME")  # 渠道的用户 name
AUTHORIZE_URL = "https://www.coze.cn/api/oauth/authorize"
TOKEN_URL = "https://www.coze.cn/api/oauth/token"
REDIRECT_URI = "http://localhost:5000/callback"

# 存储 bot 信息的文件
BOTS_FILE = "bots.json"

DEFAULT_USERNAME = "coze"
DEFAULT_PASSWORD = "12345678"


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in") and request.endpoint != "callback":
            return redirect(url_for("login_page", next=request.url))
        return f(*args, **kwargs)

    return decorated_function


def load_bots():
    if os.path.exists(BOTS_FILE):
        with open(BOTS_FILE, "r") as f:
            return json.load(f)
    return []


def save_bot(bot_data):
    bots = load_bots()
    bots.append(bot_data)
    with open(BOTS_FILE, "w") as f:
        json.dump(bots, f)


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == DEFAULT_USERNAME and password == DEFAULT_PASSWORD:
            session["logged_in"] = True
            next_url = request.form.get("next") or url_for("index")
            return redirect(next_url)
        return render_template(
            "login.html", error="用户名或密码错误", next=request.form.get("next")
        )
    return render_template("login.html", next=request.args.get("next"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/coze/login")
@login_required
def coze_login():
    coze = OAuth2Session(CLIENT_ID, redirect_uri=REDIRECT_URI)
    authorization_url, state = coze.authorization_url(AUTHORIZE_URL)
    session["oauth_state"] = state
    return redirect(authorization_url)


@app.route("/callback")
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
@login_required
def bots():
    bots_list = load_bots()
    return render_template("bots.html", bots=bots_list)


@app.route("/chat/<bot_id>")
@login_required
def chat(bot_id):
    bots_list = load_bots()
    bot = next((b for b in bots_list if b["bot_id"] == bot_id), None)
    if not bot:
        return redirect(url_for("bots"))
    return render_template("chat.html", bot=bot)


@app.route("/chat/<bot_id>/send", methods=["POST"])
@login_required
def chat_send(bot_id):
    bots_list = load_bots()
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
            yield chunk

    return Response(generate(), mimetype="text/plain")


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if data.get("type") == "bot.created":
        save_bot(data["bot"])
    return "", 200


@app.route("/oauth/authorize", methods=["GET", "POST"])
def oauth_authorize():
    if request.method == "GET":
        # https://vigilant-space-cod-jj9jwx9p7gqfrwv-5000.app.github.dev/oauth/authorize?client_id=client_id_for_coze&response_type=code&redirect_uri=http://127.0.0.1:9090
        # http://127.0.0.1:5000/oauth/authorize?client_id=client_id_for_coze&response_type=code&redirect_uri=http://127.0.0.1:9090
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
def oauth_token():
    data = request.json
    if not data:
        return jsonify({"code": 400, "message": "请求参数错误"}), 400

    # 验证必要参数
    required_fields = ["client_id", "client_secret", "code", "grant_type"]
    for field in required_fields:
        if field not in data:
            return jsonify({"code": 400, "message": f"缺少必要参数: {field}"}), 400

    # 验证 client_id 和 client_secret
    if (
        data["client_id"] != CONNECTOR_CLIENT_ID
        or data["client_secret"] != CONNECTOR_CLIENT_SECRET
    ):
        return jsonify({"code": 401, "message": "client_id 或 client_secret 无效"}), 401

    # 验证 grant_type
    if data["grant_type"] != "authorization_code":
        return jsonify(
            {"code": 400, "message": "grant_type 必须为 authorization_code"}
        ), 400

    # 生成 access_token
    access_token = secrets.token_urlsafe(32)

    # 将 token 存储到内存中
    if not hasattr(app, "token_store"):
        app.token_store = {}
    app.token_store[access_token] = {
        "expired_at": int(time.time()) + 3600,
    }

    return jsonify(
        {"access_token": access_token, "token_type": "bearer", "expires_in": 3600}
    )


@app.route("/oauth/user", methods=["GET"])
def oauth_user():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"code": 401, "message": "未提供有效的访问令牌"}), 401

    # 验证 access_token
    access_token = auth_header.split(" ")[1]
    if (
        access_token not in app.token_store
        or app.token_store[access_token]["expired_at"] < time.time()
    ):
        return jsonify({"code": 401, "message": "访问令牌无效"}), 401

    # 在实际应用中，这里应该验证 access_token 的有效性
    # 并根据 access_token 获取对应的用户信息
    return jsonify({"id": CONNECTOR_USER_ID, "name": CONNECTOR_USER_NAME})


if __name__ == "__main__":
    app.run(debug=True)
