import os
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

configuration = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])

GUIDE_URL = "https://aiden-1e0e.onrender.com/guide"

KEYWORDS = ["サービス詳細", "料金", "メニュー"]

PAYMENT_KEYWORDS = ["申し込む", "決済", "支払い"]

PAYMENT_MENU = """【お申し込みメニュー】

💬 LINEボット制作 ¥200,000
https://buy.stripe.com/dRm3cx0ip8DK4AK6jX9Zm02

🎬 会社紹介動画 ¥80,000
https://buy.stripe.com/8x2cN73uBbPWd7gbEh9Zm00

📱 SNS広告動画（単発）¥50,000
https://buy.stripe.com/aFa001aX3g6c9V4aAd9Zm0a

🔧 LINE月額保守 ¥50,000/月
https://buy.stripe.com/cNi5kF8OVf284AKeQt9Zm0d

🎁 モニターセット ¥150,000
https://buy.stripe.com/bJeaEZ6GN9HOc3c0ZD9Zm0e"""


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()

    if any(kw in user_text for kw in PAYMENT_KEYWORDS):
        reply_text = PAYMENT_MENU
    elif any(kw in user_text for kw in KEYWORDS):
        reply_text = f"サービスの詳細・料金・メニューはこちらからご確認いただけます👇\n{GUIDE_URL}"
    else:
        return

    with ApiClient(configuration) as api_client:
        messaging_api = MessagingApi(api_client)
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
