import os
import stripe
from flask import Flask, request, abort
from flask_sqlalchemy import SQLAlchemy
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from datetime import datetime

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///linebot.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

configuration = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

GUIDE_URL = "https://aiden-1e0e.onrender.com/guide"

KEYWORDS = ["サービス詳細", "料金", "メニュー"]
PAYMENT_KEYWORDS = ["申し込む", "決済", "支払い"]

# ガイドURLはここには含めない（入金確認後に送る）
SERVICE_INFO = """【Aidenのサービス一覧】

💬 LINEボット制作 ¥200,000
　AIチャットボット・自動応答・予約システムなど

🎬 会社紹介動画 ¥80,000
　プロ撮影・編集・BGM付きの企業PR動画

📱 SNS広告動画（単発）¥50,000
　TikTok/Instagram対応の縦型ショート動画

🔧 LINE月額保守 ¥50,000/月
　運用・更新・サポート込みの安心パック

🎁 モニターセット ¥150,000
　LINEボット＋動画のお得なセット

ご興味がございましたら「申し込む」とご返信ください。
決済リンクをお送りします！"""

PAYMENT_MENU = """【お申し込みメニュー】

ご希望のサービスをお選びいただき、リンクよりお手続きください。

💬 LINEボット制作 ¥200,000
https://buy.stripe.com/dRm3cx0ip8DK4AK6jX9Zm02

🎬 会社紹介動画 ¥80,000
https://buy.stripe.com/8x2cN73uBbPWd7gbEh9Zm00

📱 SNS広告動画（単発）¥50,000
https://buy.stripe.com/aFa001aX3g6c9V4aAd9Zm0a

🔧 LINE月額保守 ¥50,000/月
https://buy.stripe.com/cNi5kF8OVf284AKeQt9Zm0d

🎁 モニターセット ¥150,000
https://buy.stripe.com/bJeaEZ6GN9HOc3c0ZD9Zm0e

お支払い完了後、自動で確認メッセージをお送りします。"""


class PendingPayment(db.Model):
    __tablename__ = "pending_payments"
    id = db.Column(db.Integer, primary_key=True)
    line_user_id = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notified = db.Column(db.Boolean, default=False)


with app.app_context():
    db.create_all()


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
    line_user_id = event.source.user_id

    if any(kw in user_text for kw in PAYMENT_KEYWORDS):
        # 決済リンク送付時にLINEユーザーIDを「支払い待ち」として保存
        existing = PendingPayment.query.filter_by(
            line_user_id=line_user_id, notified=False
        ).first()
        if not existing:
            db.session.add(PendingPayment(line_user_id=line_user_id))
            db.session.commit()
        reply_text = PAYMENT_MENU

    elif any(kw in user_text for kw in KEYWORDS):
        # ガイドURLは送らず、サービス内容と料金のみ案内
        reply_text = SERVICE_INFO

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


@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        abort(400)
    except stripe.error.SignatureVerificationError:
        abort(400)

    if event["type"] == "checkout.session.completed":
        _notify_paid_users()

    return "OK"


def _notify_paid_users():
    """入金確認済みの支払い待ちユーザー全員にLINEで通知する"""
    pending = PendingPayment.query.filter_by(notified=False).all()
    if not pending:
        return

    with ApiClient(configuration) as api_client:
        messaging_api = MessagingApi(api_client)
        for record in pending:
            try:
                messaging_api.push_message(
                    PushMessageRequest(
                        to=record.line_user_id,
                        messages=[
                            TextMessage(text=(
                                "✅ 入金確認しました！\n"
                                "制作を開始します。\n\n"
                                "詳細はガイドページをご確認ください👇\n"
                                f"{GUIDE_URL}"
                            )),
                        ],
                    )
                )
                record.notified = True
            except Exception:
                pass
    db.session.commit()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
