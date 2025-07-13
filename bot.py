import logging
import sqlite3
import json
from difflib import SequenceMatcher
from flask import Flask, request, jsonify
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, Text
from aiogram.utils.keyboard import ReplyKeyboardBuilder
import threading
import asyncio
from datetime import datetime, timedelta

# --- Настройки ---
TOKEN = "7664463269:AAE6XCD0fQuLuXqbLAi5slSi9kB0Ioo3v0Y"  # Замените на токен бота
ADMIN_ID = 1214347707  # Ваш Telegram ID (для админ-уведомлений)
DB_NAME = "business_bot.db"
WEB_PORT = 5000

# --- Логирование ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Инициализация ---
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
app = Flask(__name__)

# --- База данных ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            telegram_id INTEGER UNIQUE,
            tone TEXT DEFAULT 'friendly',
            subscription_end TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            FOREIGN KEY (business_id) REFERENCES businesses (id)
        )
    ''')
    conn.commit()
    conn.close()

# --- API для Tilda ---
@app.route('/api/register_business', methods=['POST'])
def register_business():
    data = request.form
    name = data.get('name')
    telegram_id = int(data.get('telegram_id', 0))
    if not name or not telegram_id:
        return jsonify({"success": False, "error": "Не указано имя или Telegram ID"}), 400

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO businesses (name, telegram_id, subscription_end) VALUES (?, ?, ?)",
            (name, telegram_id, (datetime.today() + timedelta(days=7)).strftime("%Y-%m-%d"))
        )
        conn.commit()
        return jsonify({"success": True, "business_id": cursor.lastrowid})
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "error": "Бизнес уже зарегистрирован"}), 400
    finally:
        conn.close()

@app.route('/api/add_qa', methods=['POST'])
def add_qa():
    data = request.form
    business_id = int(data.get('business_id', 0))
    question = data.get('question')
    answer = data.get('answer')
    if not question or not answer:
        return jsonify({"success": False, "error": "Не указан вопрос или ответ"}), 400

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO knowledge (business_id, question, answer) VALUES (?, ?, ?)",
        (business_id, question, answer)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/get_templates')
def get_templates():
    with open('templates.json', 'r', encoding='utf-8') as f:
        return jsonify(json.load(f))

@app.route('/api/set_tone', methods=['POST'])
def set_tone():
    data = request.form
    business_id = int(data.get('business_id', 0))
    tone = data.get('tone')
    if tone not in ['friendly', 'formal']:
        return jsonify({"success": False, "error": "Недопустимый тон"}), 400

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE businesses SET tone = ? WHERE id = ?",
        (tone, business_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# --- Логика бота ---
def find_answer(business_id: int, text: str) -> str:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT question, answer FROM knowledge WHERE business_id = ?",
        (business_id,)
    )
    qa_pairs = cursor.fetchall()
    conn.close()

    best_match = None
    highest_ratio = 0
    for question, answer in qa_pairs:
        ratio = SequenceMatcher(None, text.lower(), question.lower()).ratio()
        if ratio > highest_ratio and ratio > 0.6:
            highest_ratio = ratio
            best_match = answer
    return best_match

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    await message.answer(
        "🤖 Добро пожаловать! Этот бот помогает бизнесам автоматизировать ответы.",
        reply_markup=get_main_kb()
    )

@dp.message(Text("🏠 Главное меню"))
async def main_menu(message: types.Message):
    await message.answer("Главное меню:", reply_markup=get_main_kb())

@dp.message()
async def handle_message(message: types.Message):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, tone FROM businesses WHERE telegram_id = ?",
        (message.from_user.id,)
    )
    business = cursor.fetchone()
    conn.close()

    if business:
        business_id, tone = business
        answer = find_answer(business_id, message.text)
        if answer:
            response = answer + (" 😊" if tone == "friendly" else "")
            await message.answer(response)
        else:
            await message.answer("🤖 Я пока не знаю ответа. Добавьте его в панели админа!")
    else:
        await message.answer("🔒 Вы не зарегистрированы. Пожалуйста, зарегистрируйте свой бизнес на нашем сайте.")

# --- Запуск ---
async def run_bot():
    await dp.start_polling(bot)

def run_web():
    app.run(host="0.0.0.0", port=WEB_PORT)

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_web).start()
    asyncio.run(run_bot())