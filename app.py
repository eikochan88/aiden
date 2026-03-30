from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Aiden 起動成功！"
