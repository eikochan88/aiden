from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Message(db.Model):
    """各AI社員との会話履歴"""
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), nullable=False, index=True)
    sender = db.Column(db.String(10), nullable=False)   # "user" or "ai"
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Report(db.Model):
    """生成されたレポート・ドキュメント"""
    __tablename__ = "reports"
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), nullable=False, index=True)
    report_type = db.Column(db.String(50), nullable=False)   # daily / weekly / sns / financial 等
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Task(db.Model):
    """タスク・指示管理"""
    __tablename__ = "tasks"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    assigned_to = db.Column(db.String(50))     # employee_id
    status = db.Column(db.String(20), default="pending")   # pending / in_progress / done
    priority = db.Column(db.String(10), default="medium")  # high / medium / low
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
