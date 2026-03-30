#!/bin/bash
# Aiden ダッシュボード自動起動スクリプト

APP_DIR="/home/eiko/aiden"
LOG_FILE="$APP_DIR/app.log"
PORT=5000

# ポート5000が既に使用中かチェック
if ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
    echo "✅ Aiden dashboard はすでに起動中です → http://localhost:$PORT"
else
    echo "🚀 Aiden dashboard を起動しています..."
    cd "$APP_DIR"
    # .env を読み込んでバックグラウンドで起動
    export $(grep -v '^#' .env | xargs)
    nohup python3 app.py > "$LOG_FILE" 2>&1 &
    # 起動を待つ
    for i in $(seq 1 10); do
        sleep 1
        if ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
            echo "✅ 起動完了 → http://localhost:$PORT"
            break
        fi
    done
fi

# ブラウザを開く（WSL2: Windows側のブラウザを使用）
sleep 1
cmd.exe /c start http://localhost:$PORT 2>/dev/null || \
    powershell.exe -Command "Start-Process 'http://localhost:$PORT'" 2>/dev/null || \
    xdg-open "http://localhost:$PORT" 2>/dev/null || true
