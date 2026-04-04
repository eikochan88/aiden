import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory
from models import db, Message, Report, Task
from employees import get_all_employees, get_employee, chat_with_employee, generate_report

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///aiden.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = os.environ.get("SECRET_KEY", "aiden-secret-key-2024")

db.init_app(app)

with app.app_context():
    db.create_all()


# ─── テンプレート用グローバル変数 ──────────────────────────────
@app.context_processor
def inject_globals():
    return {
        "all_employees": get_all_employees(),
        "now": datetime.utcnow(),
    }


# ─── ダッシュボード ────────────────────────────────────────────
@app.route("/")
def dashboard():
    employees = get_all_employees()

    # 各社員の最新メッセージ時刻・メッセージ数を取得
    stats = {}
    for emp in employees:
        count = Message.query.filter_by(employee_id=emp["id"]).count()
        last = (
            Message.query.filter_by(employee_id=emp["id"])
            .order_by(Message.created_at.desc())
            .first()
        )
        report_count = Report.query.filter_by(employee_id=emp["id"]).count()
        stats[emp["id"]] = {
            "msg_count": count,
            "last_active": last.created_at if last else None,
            "report_count": report_count,
        }

    recent_reports = (
        Report.query.order_by(Report.created_at.desc()).limit(5).all()
    )
    pending_tasks = Task.query.filter_by(status="pending").order_by(Task.created_at.desc()).limit(5).all()

    return render_template(
        "dashboard.html",
        employees=employees,
        stats=stats,
        recent_reports=recent_reports,
        pending_tasks=pending_tasks,
    )


# ─── チャット画面 ──────────────────────────────────────────────
@app.route("/chat/<employee_id>")
def chat(employee_id):
    emp = get_employee(employee_id)
    if not emp:
        return redirect(url_for("dashboard"))

    messages = (
        Message.query.filter_by(employee_id=employee_id)
        .order_by(Message.created_at.asc())
        .limit(100)
        .all()
    )
    return render_template("chat.html", emp=emp, messages=messages)


# ─── チャット API ─────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json()
    employee_id = data.get("employee_id", "")
    user_text = data.get("message", "").strip()

    if not user_text:
        return jsonify({"error": "メッセージが空です"}), 400

    emp = get_employee(employee_id)
    if not emp:
        return jsonify({"error": "社員が見つかりません"}), 404

    # 会話履歴を取得（直近40件）
    history = (
        Message.query.filter_by(employee_id=employee_id)
        .order_by(Message.created_at.asc())
        .limit(40)
        .all()
    )
    history_list = [{"sender": m.sender, "content": m.content} for m in history]

    # Claude APIで返答生成
    ai_reply = chat_with_employee(employee_id, history_list, user_text)

    # DBに保存
    db.session.add(Message(employee_id=employee_id, sender="user", content=user_text))
    db.session.add(Message(employee_id=employee_id, sender="ai", content=ai_reply))
    db.session.commit()

    return jsonify({
        "reply": ai_reply,
        "employee_name": emp["name"],
        "timestamp": datetime.utcnow().strftime("%H:%M"),
    })


# ─── チャット履歴クリア ────────────────────────────────────────
@app.route("/api/chat/<employee_id>/clear", methods=["POST"])
def clear_chat(employee_id):
    Message.query.filter_by(employee_id=employee_id).delete()
    db.session.commit()
    return jsonify({"ok": True})


# ─── レポート一覧 ─────────────────────────────────────────────
@app.route("/reports")
def reports():
    employee_id = request.args.get("employee_id", "")
    report_type = request.args.get("type", "")

    query = Report.query
    if employee_id:
        query = query.filter_by(employee_id=employee_id)
    if report_type:
        query = query.filter_by(report_type=report_type)

    all_reports = query.order_by(Report.created_at.desc()).limit(50).all()
    employees = get_all_employees()

    return render_template(
        "reports.html",
        reports=all_reports,
        employees=employees,
        selected_employee=employee_id,
    )


# ─── レポート生成 API ─────────────────────────────────────────
@app.route("/api/report/generate", methods=["POST"])
def api_generate_report():
    data = request.get_json()
    employee_id = data.get("employee_id", "")
    report_key = data.get("report_key", "")

    emp = get_employee(employee_id)
    if not emp:
        return jsonify({"error": "社員が見つかりません"}), 404

    title, content = generate_report(employee_id, report_key)

    report = Report(
        employee_id=employee_id,
        report_type=report_key,
        title=f"{emp['name']}｜{title}",
        content=content,
    )
    db.session.add(report)
    db.session.commit()

    return jsonify({
        "ok": True,
        "report_id": report.id,
        "title": report.title,
        "content": content,
        "created_at": report.created_at.strftime("%Y/%m/%d %H:%M"),
    })


# ─── レポート詳細 ─────────────────────────────────────────────
@app.route("/reports/<int:report_id>")
def report_detail(report_id):
    report = Report.query.get_or_404(report_id)
    emp = get_employee(report.employee_id)
    return render_template("report_detail.html", report=report, emp=emp)


# ─── レポート削除 ─────────────────────────────────────────────
@app.route("/api/report/<int:report_id>/delete", methods=["POST"])
def delete_report(report_id):
    report = Report.query.get_or_404(report_id)
    db.session.delete(report)
    db.session.commit()
    return jsonify({"ok": True})


# ─── タスク一覧 ───────────────────────────────────────────────
@app.route("/tasks")
def tasks():
    all_tasks = Task.query.order_by(Task.created_at.desc()).all()
    employees = get_all_employees()
    return render_template("tasks.html", tasks=all_tasks, employees=employees)


# ─── タスク作成 API ───────────────────────────────────────────
@app.route("/api/tasks", methods=["POST"])
def create_task():
    data = request.get_json()
    task = Task(
        title=data.get("title", "").strip(),
        description=data.get("description", ""),
        assigned_to=data.get("assigned_to", ""),
        priority=data.get("priority", "medium"),
    )
    db.session.add(task)
    db.session.commit()
    return jsonify({"ok": True, "task_id": task.id})


# ─── タスクステータス更新 ────────────────────────────────────
@app.route("/api/tasks/<int:task_id>/status", methods=["POST"])
def update_task_status(task_id):
    task = Task.query.get_or_404(task_id)
    data = request.get_json()
    task.status = data.get("status", task.status)
    task.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True})


# ─── タスク削除 ───────────────────────────────────────────────
@app.route("/api/tasks/<int:task_id>/delete", methods=["POST"])
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()
    return jsonify({"ok": True})


# ─── 全社員一括メッセージ API ────────────────────────────────
@app.route("/api/broadcast", methods=["POST"])
def api_broadcast():
    data = request.get_json()
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "メッセージを入力してください"}), 400

    employees = get_all_employees()

    def call_emp(emp):
        reply = chat_with_employee(emp["id"], [], message)
        return {
            "id":    emp["id"],
            "name":  emp["name"],
            "title": emp["title"],
            "emoji": emp["emoji"],
            "color": emp["color"],
            "reply": reply,
        }

    results = []
    with ThreadPoolExecutor(max_workers=len(employees)) as ex:
        futures = {ex.submit(call_emp, emp): emp for emp in employees}
        for f in as_completed(futures):
            results.append(f.result())

    order = {emp["id"]: i for i, emp in enumerate(employees)}
    results.sort(key=lambda r: order.get(r["id"], 99))

    return jsonify({"ok": True, "results": results})


# ─── 社員連携会議 API ─────────────────────────────────────────
@app.route("/api/meeting", methods=["POST"])
def api_meeting():
    data = request.get_json()
    theme = data.get("theme", "").strip()
    if not theme:
        return jsonify({"error": "テーマを入力してください"}), 400

    employees = get_all_employees()
    emp_list = "\n".join(
        f"- {e['id']}: {e['name']}（{e['title']} / {e['department']}部）"
        for e in employees
    )

    # ── Step1: 関与社員を自動選出 ──────────────────────────────
    selection_prompt = f"""Aiden株式会社の社員連携会議を開催します。

テーマ：{theme}

社員一覧：
{emp_list}

このテーマに最も関連する社員を3〜6名選び、発言順に並べてください。
社長（oyama）は必ず最初に含めてください。

JSON形式のみで回答（他のテキスト不要）：
{{"employees": ["id1", "id2", ...]}}"""

    from employees import client as openai_client
    try:
        sel = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=150,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": selection_prompt}],
        )
        selected_ids = json.loads(sel.choices[0].message.content).get("employees", [])
        valid = {e["id"] for e in employees}
        selected_ids = [eid for eid in selected_ids if eid in valid]
        if "oyama" not in selected_ids:
            selected_ids = ["oyama"] + selected_ids
    except Exception:
        selected_ids = ["oyama", "kimura", "yamamoto", "nakai", "hayashi", "ueda"]

    # ── Step2: 順番に発言（前の発言をコンテキストとして渡す）──
    results = []
    context = ""

    for emp_id in selected_ids:
        emp = get_employee(emp_id)
        if not emp:
            continue

        if context:
            msg = (
                f"【社員連携会議】テーマ：{theme}\n\n"
                f"【これまでの発言】\n{context}\n"
                f"あなた（{emp['name']} / {emp['title']}）の立場から、"
                "担当業務・具体的なアクションプランを簡潔に述べてください。"
            )
        else:
            msg = (
                f"【社員連携会議】テーマ：{theme}\n\n"
                f"あなた（{emp['name']} / {emp['title']}）の立場から、"
                "方針・承認・全体への指示を述べてください。"
            )

        reply = chat_with_employee(emp_id, [], msg)
        results.append({
            "id":    emp["id"],
            "name":  emp["name"],
            "title": emp["title"],
            "emoji": emp["emoji"],
            "color": emp["color"],
            "reply": reply,
        })
        context += f"■ {emp['name']}（{emp['title']}）：\n{reply}\n\n"

    return jsonify({"ok": True, "theme": theme, "results": results})


# ─── 会話分析 API ────────────────────────────────────────────
@app.route("/api/chat/<employee_id>/analyze", methods=["POST"])
def api_analyze_chat(employee_id):
    emp = get_employee(employee_id)
    if not emp:
        return jsonify({"error": "社員が見つかりません"}), 404

    messages = (
        Message.query.filter_by(employee_id=employee_id)
        .order_by(Message.created_at.asc())
        .limit(40)
        .all()
    )

    if not messages:
        return jsonify({"error": "会話履歴がありません。先にAI社員と会話してください。"}), 400

    conv_lines = []
    for msg in messages:
        sender = "栄子会長" if msg.sender == "user" else emp["name"]
        conv_lines.append(f"{sender}：{msg.content}")
    conv_text = "\n\n".join(conv_lines)

    prompt = f"""以下はAI社員システム「Aiden」での会話記録です。

━━━━━━━━━━━━━━━━━━━━
■ 会話相手：{emp["name"]}（{emp["title"]} ／ {emp["department"]}部）
━━━━━━━━━━━━━━━━━━━━

{conv_text}

━━━━━━━━━━━━━━━━━━━━

上記の会話を分析し、以下の4点を日本語で回答してください。

## 1. 会話の評価
この会話で上手くいった点・良かった点を具体的に挙げてください。

## 2. 改善できる点
より効果的なやり取りにするための改善案を具体的に挙げてください。

## 3. より効果的な質問・指示の例
同じ目的をより効率よく達成できる質問・指示の例を2〜3つ提示してください。

## 4. 次のアクション提案
この会話を踏まえて、今すぐ取り組むべき具体的なアクションを提案してください。"""

    from employees import client as openai_client
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = response.choices[0].message.content
    except Exception as e:
        return jsonify({"error": f"分析に失敗しました: {str(e)}"}), 500

    return jsonify({"ok": True, "analysis": analysis, "employee_name": emp["name"]})


# ─── 動画分析 API（山本彩）────────────────────────────────────
@app.route("/api/video/analyze", methods=["POST"])
def api_video_analyze():
    data = request.get_json()
    video_url = data.get("video_url", "").strip()

    if not video_url:
        return jsonify({"error": "URLが入力されていません"}), 400

    emp = get_employee("yamamoto")
    prompt = f"""以下の動画URLを確認し、SNSマーケターとして分析してください。

動画URL: {video_url}

以下の4項目を日本語で回答してください：

━━━━━━━━━━━━━━━━━━
■ 1. SNS投稿としての評価
━━━━━━━━━━━━━━━━━━
この動画のSNS素材としての強み・弱みを評価してください。

━━━━━━━━━━━━━━━━━━
■ 2. 投稿すべきSNSの推薦
━━━━━━━━━━━━━━━━━━
X（旧Twitter）/ Instagram / TikTok / YouTube / LinkedIn のうち
どのSNSに投稿すべきか、理由とともに順位をつけてください。

━━━━━━━━━━━━━━━━━━
■ 3. 投稿文・ハッシュタグ
━━━━━━━━━━━━━━━━━━
推薦SNS別に最適な投稿文（100〜150文字）とハッシュタグ（5個）を作成してください。

━━━━━━━━━━━━━━━━━━
■ 4. 改善点・アドバイス
━━━━━━━━━━━━━━━━━━
より多くのエンゲージメントを獲得するための具体的な改善提案をしてください。"""

    from employees import client as openai_client
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=1500,
            messages=[
                {"role": "system", "content": emp["system_prompt"]},
                {"role": "user", "content": prompt},
            ],
        )
        analysis = response.choices[0].message.content
    except Exception as e:
        return jsonify({"error": f"分析に失敗しました: {e}"}), 500

    # レポートとして保存
    report = Report(
        employee_id="yamamoto",
        report_type="video_analysis",
        title=f"山本 彩｜動画分析レポート",
        content=f"【分析対象URL】\n{video_url}\n\n{analysis}",
    )
    db.session.add(report)
    db.session.commit()

    return jsonify({
        "ok": True,
        "analysis": analysis,
        "report_id": report.id,
        "video_url": video_url,
    })


# ─── ガイドページ ─────────────────────────────────────────────
_GUIDE_PAGES = {
    "line-bot", "video-company", "video-sns",
    "ai-automation", "stripe", "line-maintenance", "line-setup",
}

@app.route("/guide")
def guide_index():
    return send_from_directory("static/guide", "index.html")

@app.route("/guide/<page>")
def guide(page):
    if page not in _GUIDE_PAGES:
        return redirect(url_for("dashboard"))
    return send_from_directory("static/guide", f"{page}.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
