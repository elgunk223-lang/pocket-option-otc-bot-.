import os
import time
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import pandas as pd
import yfinance as yf
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# Logging tənzimləmələri
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ----------------------------------------------------
# 1. Render Pulsuz Web Service üçün Dummy HTTP Server
# ----------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# ----------------------------------------------------
# 2. Telegram Bot və Analiz Hissəsi
# ----------------------------------------------------
TOKEN = "8955270050:AAFvYBtK01FzfUulEpR6JBmMEkjw0smgUJo"

# Son analizin vaxtını saxlayacaq lüğət (15 saniyəlik limit üçün)
user_last_click = {}

# Pocket Option OTC Valyuta cütləri
OTC_PAIRS = {
    "EUR/USD OTC": "EURUSD=X",
    "GBP/USD OTC": "GBPUSD=X",
    "USD/JPY OTC": "USDJPY=X",
    "AUD/USD OTC": "AUDUSD=X",
    "USD/CAD OTC": "USDCAD=X",
    "USD/CHF OTC": "USDCHF=X",
    "NZD/USD OTC": "NZDUSD=X",
    "EUR/GBP OTC": "EURGBP=X",
    "EUR/JPY OTC": "EURJPY=X",
    "GBP/JPY OTC": "GBPJPY=X",
    "AUD/JPY OTC": "AUDJPY=X",
    "CAD/JPY OTC": "CADJPY=X",
    "EUR/AUD OTC": "EURAUD=X",
    "EUR/CAD OTC": "EURCAD=X",
    "GBP/CAD OTC": "GBPCAD=X",
    "GBP/AUD OTC": "GBPAUD=X",
    "AUD/CAD OTC": "AUDCAD=X",
    "AUD/NZD OTC": "AUDNZD=X"
}

def analyze_market(ticker_symbol):
    try:
        data = yf.download(tickers=ticker_symbol, period="1d", interval="1m", progress=False)
        if data.empty or len(data) < 14:
            return "Məlumat alınamadı", "N/A", "N/A"
        
        close = data['Close']
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        last_rsi = float(rsi.iloc[-1])
        
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        
        last_macd = float(macd.iloc[-1])
        last_signal = float(signal.iloc[-1])
        
        if last_rsi < 30 and last_macd > last_signal:
            signal_res = "🟢 GÜCLÜ ALIŞ (CALL)"
        elif last_rsi > 70 and last_macd < last_signal:
            signal_res = "🔴 GÜCLÜ SATIŞ (PUT)"
        elif last_rsi < 45:
            signal_res = "🟢 ALIŞ (CALL)"
        elif last_rsi > 55:
            signal_res = "🔴 SATIŞ (PUT)"
        else:
            signal_res = "⚪ GÖZLƏ (NÖTR)"
            
        return signal_res, round(last_rsi, 2), round(float(close.iloc[-1]), 5)
    except Exception as e:
        return "Xəta yarandı", "N/A", "N/A"

def get_main_keyboard():
    keyboard = []
    keys = list(OTC_PAIRS.keys())
    for i in range(0, len(keys), 2):
        row = [InlineKeyboardButton(keys[i], callback_data=f"pair_{keys[i]}")]
        if i + 1 < len(keys):
            row.append(InlineKeyboardButton(keys[i+1], callback_data=f"pair_{keys[i+1]}"))
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "📊 **Pocket Option OTC Siqnal Botuna Xoş Gəldiniz!**\n\n"
        "Analiz etmək istədiyiniz valyuta cütünü aşağıdakı düymələrdən seçin:\n"
        "⏱ *Hər analiz arasında 15 saniyə gözləmə vaxtı var.*"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    current_time = time.time()
    
    # 15 saniyəlik anti-spam taymeri
    if user_id in user_last_click:
        elapsed = current_time - user_last_click[user_id]
        if elapsed < 15:
            remaining = int(15 - elapsed)
            await query.edit_message_text(
                f"⏳ Lütfən **{remaining} saniyə** gözləyin və yenidən cəhd edin.",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            return

    user_last_click[user_id] = current_time
    pair_name = query.data.replace("pair_", "")
    ticker = OTC_PAIRS.get(pair_name)
    
    await query.edit_message_text(f"🔄 **{pair_name}** analizi aparılır, gözləyin...")
    
    signal, rsi, price = analyze_market(ticker)
    
    response_text = (
        f"📈 **Valyuta:** {pair_name}\n"
        f"💵 **Cari Qiymət:** {price}\n"
        f"📊 **RSI (14):** {rsi}\n\n"
        f"🎯 **SİQNAL:** {signal}\n\n"
        f"⏱ *Növbəti analiz üçün 15 saniyə gözləyin.*"
    )
    
    await query.edit_message_text(
        response_text,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

def main():
    # Render üçün arxa fonda HTTP server açırıq
    threading.Thread(target=run_health_check_server, daemon=True).start()
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    print("Bot və HTTP Server uğurla işə düşdü...")
    app.run_polling()

if __name__ == "__main__":
    main()
