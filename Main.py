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
# 1. Render Pulsuz Web Service üçün HTTP Server
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
# 2. Telegram Bot və İndikator Analiz Hissəsi
# ----------------------------------------------------
TOKEN = "8955270050:AAFvYBtK01FzfUulEpR6JBmMEkjw0smgUJo"

# İstifadəçilərin seçimləri və anti-spam üçün
user_last_click = {}
user_selections = {}

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

TIMEFRAMES = {
    "15s": {"period": "1d", "interval": "1m"},  # 15s üçün sub-minute proxy interval
    "1m":  {"period": "1d", "interval": "1m"},
    "5m":  {"period": "5d", "interval": "5m"},
    "15m": {"period": "5d", "interval": "15m"},
    "30m": {"period": "5d", "interval": "30m"},
    "1h":  {"period": "1mo", "interval": "60m"},
    "4h":  {"period": "1mo", "interval": "60m"} # 4h üçün proxy
}

# 6 İndikatorun dəqiq hesablanması
def calculate_indicators_and_signal(ticker_symbol, tf_key):
    try:
        tf_info = TIMEFRAMES.get(tf_key, TIMEFRAMES["1m"])
        data = yf.download(tickers=ticker_symbol, period=tf_info["period"], interval=tf_info["interval"], progress=False)
        
        if data.empty or len(data) < 30:
            return None, "Məlumat alınamadı (Bazar bağlı ola bilər)."

        close = data['Close']
        high = data['High']
        low = data['Low']

        # 1. RSI (14)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        last_rsi = float(rsi.iloc[-1])

        # 2. MACD (12, 26, 9)
        exp12 = close.ewm(span=12, adjust=False).mean()
        exp26 = close.ewm(span=26, adjust=False).mean()
        macd = exp12 - exp26
        signal_line = macd.ewm(span=9, adjust=False).mean()
        last_macd = float(macd.iloc[-1])
        last_macd_signal = float(signal_line.iloc[-1])

        # 3. Moving Averages (EMA 20 & SMA 50)
        ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        sma50 = float(close.rolling(window=min(50, len(close))).mean().iloc[-1])
        last_close = float(close.iloc[-1])

        # 4. Stochastic Oscillator (14, 3, 3)
        low14 = low.rolling(window=14).min()
        high14 = high.rolling(window=14).max()
        k = 100 * ((close - low14) / (high14 - low14))
        last_stoch_k = float(k.iloc[-1])

        # 5. Bollinger Bands (20, 2)
        sma20 = close.rolling(window=20).mean()
        std20 = close.rolling(window=20).std()
        upper_band = float((sma20 + (std20 * 2)).iloc[-1])
        lower_band = float((sma20 - (std20 * 2)).iloc[-1])

        # 6. ATR (Average True Range - Volatillik)
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(window=14).mean().iloc[-1])

        # 6 İndikator üzrə Konsensus Siqnal Skorlaması
        buy_score = 0
        sell_score = 0

        # RSI Təhlili
        if last_rsi < 35: buy_score += 2
        elif last_rsi > 65: sell_score += 2

        # MACD Təhlili
        if last_macd > last_macd_signal: buy_score += 1.5
        else: sell_score += 1.5

        # EMA/SMA Təhlili
        if last_close > ema20 and ema20 > sma50: buy_score += 1.5
        elif last_close < ema20 and ema20 < sma50: sell_score += 1.5

        # Stochastic Təhlili
        if last_stoch_k < 20: buy_score += 1
        elif last_stoch_k > 80: sell_score += 1

        # Bollinger Bands Təhlili
        if last_close <= lower_band: buy_score += 2
        elif last_close >= upper_band: sell_score += 2

        # Yekun Siqnalın Müəyyənləşdirilməsi
        if buy_score >= 5.5:
            final_signal = "🟢 GÜCLÜ ALIŞ (CALL ⬆️)"
        elif buy_score >= 3.5:
            final_signal = "🟢 ALIŞ (CALL ⬆️)"
        elif sell_score >= 5.5:
            final_signal = "🔴 GÜCLÜ SATIŞ (PUT ⬇️)"
        elif sell_score >= 3.5:
            final_signal = "🔴 SATIŞ (PUT ⬇️)"
        else:
            final_signal = "⚪ GÖZLƏ / NÖTR ⚖️"

        details = {
            "price": round(last_close, 5),
            "rsi": round(last_rsi, 2),
            "macd": "BULLISH" if last_macd > last_macd_signal else "BEARISH",
            "stoch": round(last_stoch_k, 2),
            "trend": "YUXARI" if last_close > ema20 else "AŞAĞI",
            "bollinger": "AŞAĞI BANT (Sıçrayış ehtimalı)" if last_close <= lower_band else ("YUXARI BANT" if last_close >= upper_band else "ORTA BANT"),
            "atr": round(atr, 5),
            "signal": final_signal
        }
        return details, None

    except Exception as e:
        return None, f"Xəta yarandı: {str(e)}"

# Klaviatura Seçimləri
def get_pair_keyboard():
    keyboard = []
    keys = list(OTC_PAIRS.keys())
    for i in range(0, len(keys), 2):
        row = [InlineKeyboardButton(keys[i], callback_data=f"pair_{keys[i]}")]
        if i + 1 < len(keys):
            row.append(InlineKeyboardButton(keys[i+1], callback_data=f"pair_{keys[i+1]}"))
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

def get_timeframe_keyboard(pair_name):
    keyboard = [
        [InlineKeyboardButton("⏱ 15 san", callback_data=f"tf_{pair_name}_15s"), InlineKeyboardButton("⏱ 1 dək", callback_data=f"tf_{pair_name}_1m")],
        [InlineKeyboardButton("⏱ 5 dək", callback_data=f"tf_{pair_name}_5m"), InlineKeyboardButton("⏱ 15 dək", callback_data=f"tf_{pair_name}_15m")],
        [InlineKeyboardButton("⏱ 30 dək", callback_data=f"tf_{pair_name}_30m"), InlineKeyboardButton("⏱ 1 saat", callback_data=f"tf_{pair_name}_1h")],
        [InlineKeyboardButton("⏱ 4 saat", callback_data=f"tf_{pair_name}_4h")],
        [InlineKeyboardButton("◀️ Valyuta Seçiminə Qayıt", callback_data="back_to_pairs")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Bot İşleyişi
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "📊 **Pocket Option OTC Professional Siqnal Botu**\n\n"
        "Bot **6 əsas texniki indikatoru** (RSI, MACD, Moving Averages, Stochastic, Bollinger Bands, ATR) real vaxt rejimində analiz edərək dəqiq siqnallar verir.\n\n"
        "👇 **Lütfən analiz etmək istədiyiniz valyuta cütünü seçin:**"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=get_pair_keyboard())

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data

    if data == "back_to_pairs":
        await query.edit_message_text(
            "👇 **Lütfən analiz etmək istədiyiniz valyuta cütünü seçin:**",
            reply_markup=get_pair_keyboard()
        )
        return

    if data.startswith("pair_"):
        pair_name = data.replace("pair_", "")
        await query.edit_message_text(
            f"📈 Seçildi: **{pair_name}**\n\n⏱ **İndi analizin vaxt intervalını (Taymer) seçin:**",
            parse_mode="Markdown",
            reply_markup=get_timeframe_keyboard(pair_name)
        )
        return

    if data.startswith("tf_"):
        parts = data.split("_")
        pair_name = parts[1]
        tf_key = parts[2]
        
        current_time = time.time()
        if user_id in user_last_click:
            elapsed = current_time - user_last_click[user_id]
            if elapsed < 10:
                remaining = int(10 - elapsed)
                await query.edit_message_text(
                    f"⏳ Anti-Spam: Lütfən **{remaining} saniyə** gözləyin.",
                    reply_markup=get_timeframe_keyboard(pair_name)
                )
                return

        user_last_click[user_id] = current_time
        ticker = OTC_PAIRS.get(pair_name)

        await query.edit_message_text(f"🔄 **{pair_name}** ({tf_key}) üçün 6 İndikator analizi aparılır, gözləyin...")

        res, err = calculate_indicators_and_signal(ticker, tf_key)

        if err:
            await query.edit_message_text(
                f"❌ **Xəta:** {err}",
                reply_markup=get_timeframe_keyboard(pair_name)
            )
            return

        msg = (
            f"📈 **VALYUTA:** {pair_name}\n"
            f"⏱ **VAYT İNTERVALI:** {tf_key}\n"
            f"💵 **Cari Qiymət:** {res['price']}\n"
            f"───────────────\n"
            f"📊 **6 İNDİKATOR ANALİZİ:**\n"
            f"• **RSI (14):** {res['rsi']}\n"
            f"• **MACD Trend:** {res['macd']}\n"
            f"• **Stochastic (%K):** {res['stoch']}\n"
            f"• **EMA / SMA Trend:** {res['trend']}\n"
            f"• **Bollinger:** {res['bollinger']}\n"
            f"• **ATR (Volatillik):** {res['atr']}\n"
            f"───────────────\n"
            f"🎯 **YEKUN SİQNAL:** {res['signal']}\n\n"
            f"💡 *Yenidən analiz etmək üçün interval seçin:*"
        )

        await query.edit_message_text(
            msg,
            parse_mode="Markdown",
            reply_markup=get_timeframe_keyboard(pair_name)
        )

def main():
    threading.Thread(target=run_health_check_server, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    print("Bot və HTTP Server uğurla işə düşdü...")
    app.run_polling()

if __name__ == "__main__":
    main()
