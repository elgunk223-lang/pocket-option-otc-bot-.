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

user_last_click = {}

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
    "15s": {"period": "1d", "interval": "1m"},
    "1m":  {"period": "1d", "interval": "1m"},
    "5m":  {"period": "5d", "interval": "5m"},
    "15m": {"period": "5d", "interval": "15m"},
    "30m": {"period": "5d", "interval": "30m"},
    "1h":  {"period": "1mo", "interval": "60m"},
    "4h":  {"period": "1mo", "interval": "60m"}
}

def analyze_indicators(ticker_symbol, tf_key):
    try:
        tf_info = TIMEFRAMES.get(tf_key, TIMEFRAMES["1m"])
        data = yf.download(tickers=ticker_symbol, period=tf_info["period"], interval=tf_info["interval"], progress=False)
        
        if data.empty or len(data) < 30:
            return None, "Bazar məlumatı alına bilmədi (Cütlük qapalı ola bilər)."

        # Pandas Series konversiyası (float xətasını tam aradan qaldırır)
        close = data['Close'].squeeze()
        high = data['High'].squeeze()
        low = data['Low'].squeeze()

        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
            high = high.iloc[:, 0]
            low = low.iloc[:, 0]

        last_price = float(close.iloc[-1])

        # 1. RSI (14)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        last_rsi = float(rsi.iloc[-1])

        if last_rsi < 30:
            rsi_signal = "🟢 YUXARI (Aşırı Satış)"
            rsi_val = 1
        elif last_rsi > 70:
            rsi_signal = "🔴 AŞAĞI (Aşırı Alış)"
            rsi_val = -1
        else:
            rsi_signal = "⚪ NEUTRAL"
            rsi_val = 0

        # 2. MACD (12, 26, 9)
        exp12 = close.ewm(span=12, adjust=False).mean()
        exp26 = close.ewm(span=26, adjust=False).mean()
        macd = exp12 - exp26
        signal_line = macd.ewm(span=9, adjust=False).mean()
        last_macd = float(macd.iloc[-1])
        last_sig = float(signal_line.iloc[-1])

        if last_macd > last_sig:
            macd_signal = "🟢 YUXARI (Bullish Cross)"
            macd_val = 1
        else:
            macd_signal = "🔴 AŞAĞI (Bearish Cross)"
            macd_val = -1

        # 3. EMA 20 & SMA 50 Trend
        ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        sma50 = float(close.rolling(window=min(50, len(close))).mean().iloc[-1])

        if last_price > ema20 and ema20 > sma50:
            trend_signal = "🟢 YUXARI (Güclü Yüksəliş Trendi)"
            trend_val = 1
        elif last_price < ema20 and ema20 < sma50:
            trend_signal = "🔴 AŞAĞI (Güclü Eniş Trendi)"
            trend_val = -1
        else:
            trend_signal = "⚪ NEUTRAL (Konsolidasiya)"
            trend_val = 0

        # 4. Stochastic (14, 3, 3)
        low14 = low.rolling(window=14).min()
        high14 = high.rolling(window=14).max()
        stoch_k = 100 * ((close - low14) / (high14 - low14))
        last_stoch = float(stoch_k.iloc[-1])

        if last_stoch < 20:
            stoch_signal = "🟢 YUXARI (Dönüş Siqnalı)"
            stoch_val = 1
        elif last_stoch > 80:
            stoch_signal = "🔴 AŞAĞI (Dönüş Siqnalı)"
            stoch_val = -1
        else:
            stoch_signal = "⚪ NEUTRAL"
            stoch_val = 0

        # 5. Bollinger Bands (20, 2)
        sma20 = close.rolling(window=20).mean()
        std20 = close.rolling(window=20).std()
        upper_band = float((sma20 + (std20 * 2)).iloc[-1])
        lower_band = float((sma20 - (std20 * 2)).iloc[-1])

        if last_price <= lower_band:
            bollinger_signal = "🟢 YUXARI (Alt Bant Sıçrayışı)"
            bollinger_val = 1
        elif last_price >= upper_band:
            bollinger_signal = "🔴 AŞAĞI (Üst Bant Sıçrayışı)"
            bollinger_val = -1
        else:
            bollinger_signal = "⚪ NEUTRAL (Bant Daxili)"
            bollinger_val = 0

        # 6. ATR Volatillik (Aldatıcı / Təhlükəli Bazar Analizi)
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr_mean = float(tr.rolling(window=14).mean().iloc[-1])
        price_volatility_pct = (atr_mean / last_price) * 100

        is_dangerous_market = False
        if price_volatility_pct > 0.35: # Yüksək impuls və ya saxta sınma riski
            atr_signal = "⚠️ TƏHLÜKƏLİ BAZAR (Yüksək Manipulyasiya Riski)"
            is_dangerous_market = True
        else:
            atr_signal = "✅ STABİL BAZAR"

        # Səs Çoxluğu ilə Yekun Siqnalın Hesablanması
        signals_list = [rsi_val, macd_val, trend_val, stoch_val, bollinger_val]
        up_votes = signals_list.count(1)
        down_votes = signals_list.count(-1)
        neutral_votes = signals_list.count(0)

        if is_dangerous_market:
            final_signal = "⛔ TƏHLÜKƏLİ BAZAR - TRADE ETMƏYİN! (NO TRADE)"
        elif up_votes >= 4:
            final_signal = f"🟢 GÜCLÜ YUXARI / CALL ⬆️ ({up_votes}/5 İndikator Təsdiqləyir)"
        elif down_votes >= 4:
            final_signal = f"🔴 GÜCLÜ AŞAĞI / PUT ⬇️ ({down_votes}/5 İndikator Təsdiqləyir)"
        elif up_votes >= 3 and down_votes <= 1:
            final_signal = f"🟢 YUXARI / CALL ⬆️ ({up_votes}/5 İndikator Təsdiqləyir)"
        elif down_votes >= 3 and up_votes <= 1:
            final_signal = f"🔴 AŞAĞI / PUT ⬇️ ({down_votes}/5 İndikator Təsdiqləyir)"
        else:
            final_signal = "⚪ NEUTRAL / GÖZLƏ (Bazar Qərarsızdır - NO TRADE)"

        result = {
            "price": round(last_price, 5),
            "rsi": (round(last_rsi, 2), rsi_signal),
            "macd": macd_signal,
            "trend": trend_signal,
            "stoch": (round(last_stoch, 2), stoch_signal),
            "bollinger": bollinger_signal,
            "atr": atr_signal,
            "final": final_signal,
            "votes": f"🟢 Yuxarı: {up_votes} | 🔴 Aşağı: {down_votes} | ⚪ Neytral: {neutral_votes}"
        }

        return result, None

    except Exception as e:
        return None, f"Analiz xətası: {str(e)}"

# Klaviaturag
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

# Bot Əmrləri
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "📊 **Pocket Option OTC Professional Siqnal Botu**\n\n"
        "Bot **6 indikatoru** real vaxtda analiz edir və ziddiyyətli/altsatışlı (fake) bazarlarda `NO TRADE` xəbərdarlığı verir.\n\n"
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
            if elapsed < 8:
                remaining = int(8 - elapsed)
                await query.edit_message_text(
                    f"⏳ Anti-Spam: Lütfən **{remaining} saniyə** gözləyin.",
                    reply_markup=get_timeframe_keyboard(pair_name)
                )
                return

        user_last_click[user_id] = current_time
        ticker = OTC_PAIRS.get(pair_name)

        await query.edit_message_text(f"🔄 **{pair_name}** ({tf_key}) üçün 6 İndikator analizi aparılır...")

        res, err = analyze_indicators(ticker, tf_key)

        if err:
            await query.edit_message_text(
                f"❌ **Xəta:** {err}",
                reply_markup=get_timeframe_keyboard(pair_name)
            )
            return

        msg = (
            f"📈 **VALYUTA:** {pair_name}\n"
            f"⏱ **TAYMER:** {tf_key}\n"
            f"💵 **Cari Qiymət:** {res['price']}\n"
            f"───────────────\n"
            f"📊 **İNDİKATORLARIN ANALİZİ:**\n"
            f"• **1. RSI (14) [{res['rsi'][0]}]:** {res['rsi'][1]}\n"
            f"• **2. MACD:** {res['macd']}\n"
            f"• **3. EMA/SMA Trend:** {res['trend']}\n"
            f"• **4. Stochastic [{res['stoch'][0]}]:** {res['stoch'][1]}\n"
            f"• **5. Bollinger Bands:** {res['bollinger']}\n"
            f"• **6. ATR (Risklilik):** {res['atr']}\n"
            f"───────────────\n"
            f"📊 **SƏS NƏTİCƏSİ:** {res['votes']}\n"
            f"🎯 **YEKUN SİQNAL:**\n**{res['final']}**\n\n"
            f"💡 *Yenidən analiz etmək üçün vaxt seçin:*"
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
