import os
import json
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
EIKO_LINE_USER_ID = os.environ.get("EIKO_LINE_USER_ID", "")

GUIDE_URL = "https://aiden-1e0e.onrender.com/guide"

# ── キーワード ──────────────────────────────────────────────────
KEYWORDS = ["サービス詳細", "料金", "メニュー"]
PAYMENT_KEYWORDS = ["申し込む", "決済", "支払い"]
SAMPLE_KEYWORDS = ["サンプル", "事例", "実績", "どんな動画"]

SAMPLE_COMPANY_URL = "https://aiden-1e0e.onrender.com/guide/video-company"
SAMPLE_SNS_URL     = "https://aiden-1e0e.onrender.com/guide/video-sns"

# ── サービス案内（ガイドURL含まず）──────────────────────────────
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

SERVICE_SELECT_MSG = """【サービスを選択してください】

ご希望のサービスを番号でお答えください👇

1️⃣ LINEボット制作 ¥200,000
2️⃣ 会社紹介動画 ¥80,000
3️⃣ SNS広告動画（単発）¥50,000
4️⃣ LINE月額保守 ¥50,000/月
5️⃣ モニターセット ¥150,000"""

# ── サービス番号マッピング ────────────────────────────────────
SERVICE_NUMBER_MAP = {
    "1": "line_bot",
    "2": "company_video",
    "3": "sns_video",
    "4": "maintenance",
    "5": "monitor_set",
}

# ── サービス別決済リンク ──────────────────────────────────────
PAYMENT_LINKS = {
    "line_bot":      ("💬 LINEボット制作 ¥200,000",    "https://buy.stripe.com/dRm3cx0ip8DK4AK6jX9Zm02"),
    "company_video": ("🎬 会社紹介動画 ¥80,000",        "https://buy.stripe.com/8x2cN73uBbPWd7gbEh9Zm00"),
    "sns_video":     ("📱 SNS広告動画（単発）¥50,000",  "https://buy.stripe.com/aFa001aX3g6c9V4aAd9Zm0a"),
    "maintenance":   ("🔧 LINE月額保守 ¥50,000/月",     "https://buy.stripe.com/cNi5kF8OVf284AKeQt9Zm0d"),
    "monitor_set":   ("🎁 モニターセット ¥150,000",      "https://buy.stripe.com/bJeaEZ6GN9HOc3c0ZD9Zm0e"),
}

# ── ヒアリング質問（シンプル2問のみ）────────────────────────
HEARING_QUESTIONS = {
    "company_video": [
        "【素材①/2】\n会社のHPのURLを教えてください😊\n（HPがなければSNSのURLでもOKです！）",
        "【素材②/2】\n会社ロゴをこのLINEに送ってください📎\n（HPに載っていれば不要です！）",
    ],
    "sns_video": [
        "【素材①/2】\n会社のHPのURLを教えてください😊\n（HPがなければSNSのURLでもOKです！）",
        "【素材②/2】\n会社ロゴをこのLINEに送ってください📎\n（HPに載っていれば不要です！）",
    ],
}

HEARING_LABELS = {
    "company_video": [
        "HP・SNS URL",
        "会社ロゴ",
    ],
    "sns_video": [
        "HP・SNS URL",
        "会社ロゴ",
    ],
}

SERVICE_NAMES = {
    "line_bot":      "LINEボット制作",
    "company_video": "会社紹介動画",
    "sns_video":     "SNS広告動画",
    "maintenance":   "LINE月額保守",
    "monitor_set":   "モニターセット",
}

# ── DB モデル ─────────────────────────────────────────────────

class UserSession(db.Model):
    """ユーザーの会話セッション管理"""
    __tablename__ = "user_sessions"
    line_user_id  = db.Column(db.String(64), primary_key=True)
    # idle / selecting_service / awaiting_payment / hearing / completed
    state         = db.Column(db.String(32), default="idle", nullable=False)
    service_type  = db.Column(db.String(32), nullable=True)
    hearing_step  = db.Column(db.Integer, default=0)
    # JSON: {"answers": ["回答1", "回答2", ...]}
    hearing_data  = db.Column(db.Text, default="{}")
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow)


with app.app_context():
    db.create_all()


# ── ヘルパー ──────────────────────────────────────────────────

def get_or_create_session(line_user_id: str) -> UserSession:
    session = db.session.get(UserSession, line_user_id)
    if not session:
        session = UserSession(line_user_id=line_user_id)
        db.session.add(session)
        db.session.commit()
    return session


def push_text(line_user_id: str, text: str):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).push_message(
            PushMessageRequest(
                to=line_user_id,
                messages=[TextMessage(text=text)],
            )
        )


def reply_text(reply_token: str, text: str):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )


# ── LINE Webhook ──────────────────────────────────────────────

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
    user_text     = event.message.text.strip()
    line_user_id  = event.source.user_id
    reply_token   = event.reply_token
    sess          = get_or_create_session(line_user_id)

    # ── ヒアリング中：回答を受け付ける ────────────────────────
    if sess.state == "hearing":
        _handle_hearing_answer(sess, user_text, reply_token)
        return

    # ── サービス選択中：番号を受け付ける ──────────────────────
    if sess.state == "selecting_service":
        service_key = SERVICE_NUMBER_MAP.get(user_text)
        if service_key:
            label, url = PAYMENT_LINKS[service_key]
            sess.service_type = service_key
            sess.state        = "awaiting_payment"
            sess.updated_at   = datetime.utcnow()
            db.session.commit()
            reply_text(reply_token, (
                f"ありがとうございます！\n{label} の決済リンクをお送りします👇\n\n"
                f"{url}\n\n"
                "お支払い完了後、自動でご確認メッセージをお送りします。"
            ))
        else:
            reply_text(reply_token, "1〜5の番号でお答えください。\n\n" + SERVICE_SELECT_MSG)
        return

    # ── 支払い待ち中：リマインド ───────────────────────────────
    if sess.state == "awaiting_payment":
        label, url = PAYMENT_LINKS.get(sess.service_type, ("", ""))
        reply_text(reply_token, (
            "お支払いの確認待ちです。\n"
            "以下のリンクよりお手続きください👇\n\n"
            f"{url}"
        ))
        return

    # ── 通常キーワード処理 ────────────────────────────────────
    if any(kw in user_text for kw in PAYMENT_KEYWORDS):
        sess.state      = "selecting_service"
        sess.updated_at = datetime.utcnow()
        db.session.commit()
        reply_text(reply_token, SERVICE_SELECT_MSG)

    elif any(kw in user_text for kw in SAMPLE_KEYWORDS):
        reply_text(reply_token, (
            "サンプル動画はこちらからご覧いただけます👇\n"
            "動画はストリーミング再生のみ対応しています。\n\n"
            "🎬 会社紹介動画のサンプル\n"
            f"{SAMPLE_COMPANY_URL}\n\n"
            "📱 SNS広告動画のサンプル\n"
            f"{SAMPLE_SNS_URL}"
        ))

    elif any(kw in user_text for kw in KEYWORDS):
        reply_text(reply_token, SERVICE_INFO)


def _handle_hearing_answer(sess: UserSession, answer: str, reply_token: str):
    """ヒアリングの回答を保存し、次の質問または完了処理を行う"""
    data    = json.loads(sess.hearing_data or "{}")
    answers = data.get("answers", [])
    answers.append(answer)
    data["answers"]    = answers
    sess.hearing_data  = json.dumps(data, ensure_ascii=False)
    sess.hearing_step  = len(answers)
    sess.updated_at    = datetime.utcnow()

    questions = HEARING_QUESTIONS.get(sess.service_type, [])

    if len(answers) < len(questions):
        # 次の質問を送る
        db.session.commit()
        reply_text(reply_token, questions[len(answers)])
    else:
        # ヒアリング完了
        sess.state     = "completed"
        db.session.commit()
        reply_text(reply_token,
            "✅ ヒアリング完了しました！\n制作を開始します。\n\n"
            "ご回答ありがとうございました。\n"
            "担当者よりあらためてご連絡いたします。"
        )
        _forward_hearing_to_admin(sess, answers)


def _forward_hearing_to_admin(sess: UserSession, answers: list):
    """ヒアリング結果をエイデン管理者LINEに転送する"""
    if not EIKO_LINE_USER_ID:
        return

    labels   = HEARING_LABELS.get(sess.service_type, [])
    svc_name = SERVICE_NAMES.get(sess.service_type, sess.service_type)

    lines = [f"📋【ヒアリング結果】{svc_name}", f"LINE ID: {sess.line_user_id}", ""]
    for i, (label, ans) in enumerate(zip(labels, answers), 1):
        lines.append(f"Q{i}. {label}")
        lines.append(f"→ {ans}")
        lines.append("")

    push_text(EIKO_LINE_USER_ID, "\n".join(lines).strip())


# ── Stripe Webhook ────────────────────────────────────────────

@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    payload    = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        abort(400)
    except stripe.error.SignatureVerificationError:
        abort(400)

    if event["type"] == "checkout.session.completed":
        _on_payment_completed()

    return "OK"


def _on_payment_completed():
    """入金確認後の処理：ガイドURL送付 + ヒアリング開始（対象サービスのみ）"""
    pending = UserSession.query.filter_by(state="awaiting_payment").all()
    for sess in pending:
        try:
            svc_name = SERVICE_NAMES.get(sess.service_type, "サービス")
            push_text(sess.line_user_id, (
                f"✅ 入金確認しました！\n"
                f"【{svc_name}】の制作を開始します。\n\n"
                f"詳細はガイドページをご確認ください👇\n{GUIDE_URL}"
            ))

            if sess.service_type in HEARING_QUESTIONS:
                # ヒアリングが必要なサービス：最初の質問を送る
                sess.state        = "hearing"
                sess.hearing_step = 0
                sess.hearing_data = json.dumps({"answers": []})
                sess.updated_at   = datetime.utcnow()
                db.session.commit()

                first_q = HEARING_QUESTIONS[sess.service_type][0]
                push_text(sess.line_user_id, (
                    "たったこれだけでOKです！\nあとはエイデンが全部準備します😊\n\n"
                    + first_q
                ))
            else:
                sess.state      = "completed"
                sess.updated_at = datetime.utcnow()
                db.session.commit()

        except Exception:
            pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
