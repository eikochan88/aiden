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
KEYWORDS        = ["サービス詳細", "料金", "メニュー", "こんにちは", "はじめまして"]
PAYMENT_KEYWORDS = ["申し込む", "決済", "支払い"]
SAMPLE_KEYWORDS  = ["サンプル", "事例", "実績", "どんな動画"]

SAMPLE_COMPANY_URL = "https://aiden-1e0e.onrender.com/guide/video-company"
SAMPLE_SNS_URL     = "https://aiden-1e0e.onrender.com/guide/video-sns"

# ── サービス選択メッセージ ────────────────────────────────────
SERVICE_SELECT_MSG = """どのサービスにご興味がありますか？

1️⃣ LINEボット制作 ¥200,000
2️⃣ 会社紹介動画 ¥80,000
3️⃣ SNS広告動画 ¥50,000〜
4️⃣ キャッシュレス決済導入 ¥50,000
5️⃣ モニター限定セット ¥150,000
6️⃣ その他・相談したい

番号を送ってください😊"""

# ── サービス番号マッピング ────────────────────────────────────
SERVICE_NUMBER_MAP = {
    "1": "line_bot",
    "2": "company_video",
    "3": "sns_video",
    "4": "payment",
    "5": "monitor_set",
    "6": "other",
}

# ── サービス別決済リンク ──────────────────────────────────────
PAYMENT_LINKS = {
    "line_bot":      ("💬 LINEボット制作 ¥200,000",        "https://buy.stripe.com/dRm3cx0ip8DK4AK6jX9Zm02"),
    "company_video": ("🎬 会社紹介動画 ¥80,000",            "https://buy.stripe.com/8x2cN73uBbPWd7gbEh9Zm00"),
    "sns_video":     ("📱 SNS広告動画（単発）¥50,000",      "https://buy.stripe.com/aFa001aX3g6c9V4aAd9Zm0a"),
    "payment":       ("💳 キャッシュレス決済導入 ¥50,000",  "https://buy.stripe.com/cNi5kF8OVf284AKeQt9Zm0d"),
    "monitor_set":   ("🎁 モニター限定セット ¥150,000",      "https://buy.stripe.com/bJeaEZ6GN9HOc3c0ZD9Zm0e"),
}

SERVICE_NAMES = {
    "line_bot":      "LINEボット制作",
    "company_video": "会社紹介動画",
    "sns_video":     "SNS広告動画",
    "payment":       "キャッシュレス決済導入",
    "monitor_set":   "モニター限定セット",
    "other":         "その他・ご相談",
}

# ── ヒアリングフロー定義 ──────────────────────────────────────
# type: "select" → 番号選択（options リストから選ぶ）
# type: "free"   → 自由記述
HEARING_FLOW = {
    "company_video": [
        {
            "type": "select",
            "label": "動画の雰囲気",
            "text": (
                "動画の雰囲気はどれが近いですか？\n\n"
                "1️⃣ クール・スタイリッシュ\n"
                "2️⃣ 温かい・親しみやすい\n"
                "3️⃣ 元気・明るい\n"
                "4️⃣ 高級感・プロフェッショナル\n\n"
                "番号を送ってください😊"
            ),
            "options": ["クール・スタイリッシュ", "温かい・親しみやすい", "元気・明るい", "高級感・プロフェッショナル"],
        },
        {
            "type": "select",
            "label": "動画の長さ",
            "text": (
                "動画の長さはどれにしますか？\n\n"
                "1️⃣ 30秒\n"
                "2️⃣ 1分\n"
                "3️⃣ 2分\n\n"
                "番号を送ってください😊"
            ),
            "options": ["30秒", "1分", "2分"],
        },
        {
            "type": "free",
            "label": "HP・SNS URL",
            "text": "会社のHPのURLを教えてください🌐\n（なければSNSのURLでもOKです）",
        },
        {
            "type": "free",
            "label": "一言コメント",
            "text": "最後に、伝えたいことがあれば一言どうぞ✨\n（なければ「なし」でOKです）",
        },
    ],
    "sns_video": [
        {
            "type": "select",
            "label": "動画の雰囲気",
            "text": (
                "動画の雰囲気はどれが近いですか？\n\n"
                "1️⃣ クール・スタイリッシュ\n"
                "2️⃣ 温かい・親しみやすい\n"
                "3️⃣ 元気・明るい\n"
                "4️⃣ 高級感・プロフェッショナル\n\n"
                "番号を送ってください😊"
            ),
            "options": ["クール・スタイリッシュ", "温かい・親しみやすい", "元気・明るい", "高級感・プロフェッショナル"],
        },
        {
            "type": "select",
            "label": "動画の長さ",
            "text": (
                "動画の長さはどれにしますか？\n\n"
                "1️⃣ 15秒\n"
                "2️⃣ 30秒\n"
                "3️⃣ 60秒\n\n"
                "番号を送ってください😊"
            ),
            "options": ["15秒", "30秒", "60秒"],
        },
        {
            "type": "select",
            "label": "投稿SNS",
            "text": (
                "投稿するSNSはどれですか？\n\n"
                "1️⃣ Instagram\n"
                "2️⃣ TikTok\n"
                "3️⃣ X（旧Twitter）\n"
                "4️⃣ YouTube\n\n"
                "番号を送ってください😊"
            ),
            "options": ["Instagram", "TikTok", "X（旧Twitter）", "YouTube"],
        },
        {
            "type": "free",
            "label": "HP・SNS URL",
            "text": "会社のHPのURLを教えてください🌐\n（なければSNSのURLでもOKです）",
        },
        {
            "type": "free",
            "label": "一言コメント",
            "text": "最後に、伝えたいことがあれば一言どうぞ✨\n（なければ「なし」でOKです）",
        },
    ],
    "line_bot": [
        {
            "type": "select",
            "label": "ボットの用途",
            "text": (
                "LINEボットの用途を教えてください😊\n\n"
                "1️⃣ 問い合わせ対応\n"
                "2️⃣ 予約受付\n"
                "3️⃣ 商品・サービス販売\n"
                "4️⃣ その他\n\n"
                "番号を送ってください😊"
            ),
            "options": ["問い合わせ対応", "予約受付", "商品・サービス販売", "その他"],
        },
        {
            "type": "select",
            "label": "業種",
            "text": (
                "業種を教えてください😊\n\n"
                "1️⃣ 飲食・カフェ\n"
                "2️⃣ 美容・サロン\n"
                "3️⃣ 士業・コンサル\n"
                "4️⃣ 小売・EC\n"
                "5️⃣ その他\n\n"
                "番号を送ってください😊"
            ),
            "options": ["飲食・カフェ", "美容・サロン", "士業・コンサル", "小売・EC", "その他"],
        },
        {
            "type": "free",
            "label": "HP・SNS URL",
            "text": "会社のHPのURLを教えてください🌐\n（なければSNSのURLでもOKです）",
        },
        {
            "type": "free",
            "label": "一言コメント",
            "text": "最後に、ご要望や伝えたいことがあれば一言どうぞ✨\n（なければ「なし」でOKです）",
        },
    ],
    "payment": [
        {
            "type": "select",
            "label": "販売スタイル",
            "text": (
                "販売スタイルを教えてください😊\n\n"
                "1️⃣ 店舗での対面販売\n"
                "2️⃣ オンライン販売\n"
                "3️⃣ 両方\n\n"
                "番号を送ってください😊"
            ),
            "options": ["店舗での対面販売", "オンライン販売", "両方"],
        },
        {
            "type": "select",
            "label": "プランの種別",
            "text": (
                "ご希望のプランを教えてください😊\n\n"
                "1️⃣ 月額プラン\n"
                "2️⃣ 単発・都度払い\n\n"
                "番号を送ってください😊"
            ),
            "options": ["月額プラン", "単発・都度払い"],
        },
        {
            "type": "free",
            "label": "HP・SNS URL",
            "text": "会社のHPのURLを教えてください🌐\n（なければSNSのURLでもOKです）",
        },
        {
            "type": "free",
            "label": "一言コメント",
            "text": "最後に、ご要望や伝えたいことがあれば一言どうぞ✨\n（なければ「なし」でOKです）",
        },
    ],
    "monitor_set": [
        {
            "type": "select",
            "label": "動画の雰囲気",
            "text": (
                "動画の雰囲気はどれが近いですか？\n\n"
                "1️⃣ クール・スタイリッシュ\n"
                "2️⃣ 温かい・親しみやすい\n"
                "3️⃣ 元気・明るい\n"
                "4️⃣ 高級感・プロフェッショナル\n\n"
                "番号を送ってください😊"
            ),
            "options": ["クール・スタイリッシュ", "温かい・親しみやすい", "元気・明るい", "高級感・プロフェッショナル"],
        },
        {
            "type": "free",
            "label": "HP・SNS URL",
            "text": "会社のHPのURLを教えてください🌐\n（なければSNSのURLでもOKです）",
        },
        {
            "type": "free",
            "label": "一言コメント",
            "text": "最後に、ご要望や伝えたいことがあれば一言どうぞ✨\n（なければ「なし」でOKです）",
        },
    ],
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
    # JSON: {"answers": [{"label": "...", "value": "..."}]}
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
    user_text    = event.message.text.strip()
    line_user_id = event.source.user_id
    reply_token  = event.reply_token
    sess         = get_or_create_session(line_user_id)

    # ── ヒアリング中：回答を受け付ける ────────────────────────
    if sess.state == "hearing":
        _handle_hearing_answer(sess, user_text, reply_token)
        return

    # ── サービス選択中：番号を受け付ける ──────────────────────
    if sess.state == "selecting_service":
        _handle_service_selection(sess, user_text, reply_token)
        return

    # ── 支払い待ち中：リマインド ───────────────────────────────
    if sess.state == "awaiting_payment":
        _, url = PAYMENT_LINKS.get(sess.service_type, ("", ""))
        reply_text(reply_token, (
            "お支払いの確認待ちです。\n"
            "以下のリンクよりお手続きください👇\n\n"
            f"{url}"
        ))
        return

    # ── 通常キーワード処理 ────────────────────────────────────
    if any(kw in user_text for kw in PAYMENT_KEYWORDS) or any(kw in user_text for kw in KEYWORDS):
        sess.state      = "selecting_service"
        sess.updated_at = datetime.utcnow()
        db.session.commit()
        reply_text(reply_token, SERVICE_SELECT_MSG)

    elif any(kw in user_text for kw in SAMPLE_KEYWORDS):
        reply_text(reply_token, (
            "サンプル動画はこちらからご覧いただけます👇\n"
            "（ストリーミング再生のみ対応）\n\n"
            f"🎬 会社紹介動画\n{SAMPLE_COMPANY_URL}\n\n"
            f"📱 SNS広告動画\n{SAMPLE_SNS_URL}"
        ))


def _handle_service_selection(sess: UserSession, user_text: str, reply_token: str):
    """サービス番号選択を処理する"""
    service_key = SERVICE_NUMBER_MAP.get(user_text)

    if not service_key:
        reply_text(reply_token, "1〜6の番号でお答えください😊\n\n" + SERVICE_SELECT_MSG)
        return

    if service_key == "other":
        sess.state      = "idle"
        sess.updated_at = datetime.utcnow()
        db.session.commit()
        reply_text(reply_token, (
            "ご相談内容をそのままLINEにお送りください😊\n"
            "担当者よりご連絡いたします！"
        ))
        return

    label, url = PAYMENT_LINKS[service_key]
    sess.service_type = service_key
    sess.state        = "awaiting_payment"
    sess.updated_at   = datetime.utcnow()
    db.session.commit()
    reply_text(reply_token, (
        f"ありがとうございます！\n\n"
        f"{label} の決済リンクをお送りします👇\n\n"
        f"{url}\n\n"
        "お支払い完了後、自動でご確認メッセージをお送りします✅"
    ))


def _handle_hearing_answer(sess: UserSession, answer: str, reply_token: str):
    """ヒアリングの回答を保存し、次の質問または完了処理を行う"""
    flow = HEARING_FLOW.get(sess.service_type, [])
    step = sess.hearing_step

    if step >= len(flow):
        return

    current_q = flow[step]

    # 番号選択式の場合：バリデーション → 選択肢テキストに変換
    if current_q["type"] == "select":
        options = current_q["options"]
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            resolved = options[int(answer) - 1]
        else:
            # 無効な入力：再質問
            nums = "・".join(str(i) for i in range(1, len(options) + 1))
            reply_text(reply_token,
                f"{nums} の番号で送ってください😊\n\n" + current_q["text"]
            )
            return
    else:
        resolved = answer  # 自由記述はそのまま保存

    # 回答を保存
    data    = json.loads(sess.hearing_data or "{}")
    answers = data.get("answers", [])
    answers.append({"label": current_q["label"], "value": resolved})
    data["answers"]   = answers
    sess.hearing_data = json.dumps(data, ensure_ascii=False)
    sess.hearing_step = step + 1
    sess.updated_at   = datetime.utcnow()

    if sess.hearing_step < len(flow):
        # 次の質問を送る
        db.session.commit()
        reply_text(reply_token, flow[sess.hearing_step]["text"])
    else:
        # ヒアリング完了
        sess.state    = "completed"
        db.session.commit()
        reply_text(reply_token,
            "✅ ヒアリング完了しました！\n制作を開始します🎬\n\n"
            "ご協力ありがとうございました。\n"
            "担当者よりあらためてご連絡いたします😊"
        )
        _forward_hearing_to_admin(sess, answers)


def _forward_hearing_to_admin(sess: UserSession, answers: list):
    """ヒアリング結果をエイデン管理者LINEに転送する"""
    if not EIKO_LINE_USER_ID:
        return

    svc_name = SERVICE_NAMES.get(sess.service_type, sess.service_type)
    lines = [f"📋【ヒアリング結果】{svc_name}", f"LINE ID: {sess.line_user_id}", ""]
    for i, item in enumerate(answers, 1):
        lines.append(f"Q{i}. {item['label']}")
        lines.append(f"→ {item['value']}")
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

            if sess.service_type in HEARING_FLOW:
                # ヒアリング開始
                sess.state        = "hearing"
                sess.hearing_step = 0
                sess.hearing_data = json.dumps({"answers": []})
                sess.updated_at   = datetime.utcnow()
                db.session.commit()

                first_q = HEARING_FLOW[sess.service_type][0]
                push_text(sess.line_user_id, (
                    "たったこれだけでOKです！\nあとはエイデンが全部準備します😊\n\n"
                    + first_q["text"]
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
