import os
import json
from flask import Flask, render_template, request, redirect, url_for, session, Response
from requests_oauthlib import OAuth2Session
from dotenv import load_dotenv
from cozepy import Coze, TokenAuth

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

# OAuth 配置
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
AUTHORIZE_URL = "https://www.coze.cn/api/oauth/authorize"
TOKEN_URL = "https://www.coze.cn/api/oauth/token"
REDIRECT_URI = "http://localhost:5000/callback"

# 存储 bot 信息的文件
BOTS_FILE = "bots.json"


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
def index():
    return render_template("index.html")


@app.route("/login")
def login():
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
def bots():
    bots_list = load_bots()
    return render_template("bots.html", bots=bots_list)


@app.route("/chat/<bot_id>")
def chat(bot_id):
    bots_list = load_bots()
    bot = next((b for b in bots_list if b["bot_id"] == bot_id), None)
    if not bot:
        return redirect(url_for("bots"))
    return render_template("chat.html", bot=bot)


@app.route("/chat/<bot_id>/send", methods=["POST"])
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


if __name__ == "__main__":
    app.run(debug=True)
