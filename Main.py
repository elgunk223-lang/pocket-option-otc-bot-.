import os
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

# Pocket Option OTC Bazarları (18 Məşhur Cütlük)
MARKETS = {
    "EUR/USD OTC": "EURUSD=X",
    "GBP/USD OTC": "GBPUSD=X",
    "USD/JPY OTC": "JPY=X",
    "AUD/USD OTC": "AUDUSD=X",
    "USD/CAD OTC": "USDCAD=X",
    "EUR/GBP OTC": "EURGBP=X",
    "USD/CHF OTC": "USDCHF=X",
    "NZD/USD OTC": "NZDUSD=X",
    "EUR/JPY OTC": "EURJPY=X",
    "GBP/JPY OTC": "GBPJPY=X",
    "AUD/JPY OTC": "AUDJPY=X",
    "EUR/CAD OTC": "EURCAD=X",
    "AUD/CAD OTC": "AUDCAD=X",
    "CAD/JPY OTC": "CADJPY=X",
    "GBP/CAD OTC": "GBPCAD=X",
    "CHF/JPY OTC": "CHFJPY=X",
    "EUR/AUD OTC": "EURAUD=X",
    "GBP/AUD OTC": "GBPAUD=X",
}

# Vaxt Taymerləri (15 Saniyə Əlavə Olundu)
TIMEFRAMES = {
    "15 saniyə": "15s",
    "1 dəqiqə": "1m",
    "5 dəqiqə": "5m",
    "15 dəqiqə": "15m",
    "30 dəqiqə": "30m",
    "1 saat": "1h",
    "4 saat": "4h",
}

# Canlı Dataya Əsasən 6 İndikatorun Analizi
def fetch_and_analyze(symbol: str, tf_key: str):
    # 15 saniyəlik analiz üçün 1m datasından istifadə edilib mikro-trend hesablanır
    interval = "1m" if tf_key in ["15s", "1m", "5m", "15m", "30m"] else "1h"
    period = "1d" if interval == "1m" else "7d"
    
    df = yf.download(tickers=symbol, period=period, interval=interval, progress=False)

    if df.empty or len(df) < 50:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    close = df['Close']
    high = df['High']
    low = df['Low']

    # 1. EMA (20)
    ema20 = ta.ema(close, length=20)
    # 2. MACD (12, 26, 9)
    macd_df = ta.macd(close)
    # 3. Supertrend (7, 3)
    st_df = ta.supertrend(high, low, close, length=7, multiplier=3)
    # 4. RSI (14)
    rsi = ta.rsi(close, length=14)
    # 5. CCI (20)
    cci = ta.cci(high, low, close, length=20)
    # 6. Bollinger Bands (20, 2)
    bb_df = ta.bbands(close, length=20, std=2)

    last_close = close.iloc[-1]
    last_ema = ema20.iloc[-1]
    macd_val = macd_df['MACD_12_26_9'].iloc[-1]
    macd_sig = macd_df['MACDs_12_26_9'].iloc[-1]
    st_dir = st_df['SUPERTd_7_3.0'].iloc[-1] if 'SUPERTd_7_3.0' in st_df else 1
    rsi_val = rsi.iloc[-1]
    cci_val = cci.iloc[-1]
    bb_lower = bb_df['BBL_20_2.0'].iloc[-1]
    bb_upper = bb_df['BBU_20_2.0'].iloc[-1]

    results = {}

    # EMA Analizi
    results['EMA (20)'] = "Yuxarı 🟢" if last_close > last_ema else "Aşağı 🔴"

    # MACD Analizi
    if macd_val > macd_sig:
        results['MACD'] = "Yuxarı 🟢"
    elif macd_val < macd_sig:
        results['MACD'] = "Aşağı 🔴"
    else:
        results['MACD'] = "Neytral ⚪"

    # Supertrend Analizi
    results['Supertrend'] = "Yuxarı 🟢" if st_dir == 1 else "Aşağı 🔴"

    # RSI Analizi
    if rsi_val > 55:
        results['RSI (14)'] = "Yuxarı 🟢"
    elif rsi_val < 45:
        results['RSI (14)'] = "Aşağı 🔴"
    else:
        results['RSI (14)'] = "Neytral ⚪"

    # CCI Analizi
    if cci_val > 50:
        results['CCI (20)'] = "Yuxarı 🟢"
    elif cci_val < -50:
        results['CCI (20)'] = "Aşağı 🔴"
    else:
        results['CCI (20)'] = "Neytral ⚪"

    # Bollinger Bands Analizi
    if last_close <= bb_lower:
        results['Bollinger Bands'] = "Yuxarı 🟢"
    elif last_close >= bb_upper:
        results['Bollinger Bands'] = "Aşağı 🔴"
    else:
        results['Bollinger Bands'] = "Neytral ⚪"

    return results

# Telegram Menyusu
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    # Bazarları 2 sütun şəklində səliqəli düzürük
    market_keys = list(MARKETS.keys())
    for i in range(0, len(market_keys), 2):
        row = [InlineKeyboardButton(f"📊 {market_keys[i]}", callback_data=f"market|{market_keys[i]}")]
        if i + 1 < len(market_keys):
            row.append(InlineKeyboardButton(f"📊 {market_keys[i+1]}", callback_data=f"market|{market_keys[i+1]}"))
        keyboard.append(row)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "✨ **Pocket Option OTC Manual Analiz Botu**\n\nAnaliz etmək istədiyiniz bazarı seçin:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("|")
    action = data[0]

    if action == "market":
        market_name = data[1]
        context.user_data["selected_market"] = market_name

        keyboard = []
        tf_keys = list(TIMEFRAMES.keys())
        for i in range(0, len(tf_keys), 2):
            row = [InlineKeyboardButton(f"⏱️ {tf_keys[i]}", callback_data=f"tf|{tf_keys[i]}")]
            if i + 1 < len(tf_keys):
                row.append(InlineKeyboardButton(f"⏱️ {tf_keys[i+1]}", callback_data=f"tf|{tf_keys[i+1]}"))
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("⬅️ Geri", callback_data="back_to_markets")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"📌 Bazar: *{market_name}*\n\nİndi isə analiz üçün vaxt taymerini seçin:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    elif action == "tf":
        tf_name = data[1]
        market_name = context.user_data.get("selected_market", "EUR/USD OTC")
        symbol = MARKETS[market_name]

        await query.edit_message_text("⏳ *Canlı bazar analiz olunur, gözləyin...*", parse_mode="Markdown")

        analysis = fetch_and_analyze(symbol, tf_name)

        if not analysis:
            await query.edit_message_text("❌ Xəta: Məlumat çəkilə bilmədi. Yenidən cəhd edin.")
            return

        up_count = sum(1 for v in analysis.values() if "Yuxarı" in v)
        down_count = sum(1 for v in analysis.values() if "Aşağı" in v)
        neutral_count = sum(1 for v in analysis.values() if "Neytral" in v)

        # Ən az 4 indikator eyni tərəfə baxmalıdır
        if up_count >= 4:
            final_signal = "🟢 CALL (YUXARI) ⬆️"
        elif down_count >= 4:
            final_signal = "🔴 PUT (AŞAĞI) ⬇️"
        else:
            final_signal = "⚠️ NO TRADE (Əlverişsiz Bazar - Əməliyyat Açmayın!)"

        text = f"📊 *POCKET OPTION CANLI ANALİZ REPORU*\n"
        text += f"━━━━━━━━━━━━━━━━━━━━\n"
        text += f"📌 *Bazar:* {market_name}\n"
        text += f"⏱️ *Taymer:* {tf_name}\n"
        text += f"━━━━━━━━━━━━━━━━━━━━\n"
        text += f"🔍 *6 İNDİKATORUN VƏZİYYƏTİ:*\n\n"

        for ind, status in analysis.items():
            text += f"• *{ind}:* {status}\n"

        text += f"\n📊 *Nəticə Sayı:* 🟢 Yuxarı: {up_count} | 🔴 Aşağı: {down_count} | ⚪ Neytral: {neutral_count}\n"
        text += f"━━━━━━━━━━━━━━━━━━━━\n"
        text += f"🎯 *YEKUN MƏSLƏHƏT:* {final_signal}\n"

        keyboard = [[InlineKeyboardButton("🔄 Yenidən Seçim Et", callback_data="back_to_markets")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    elif action == "back_to_markets":
        keyboard = []
        market_keys = list(MARKETS.keys())
        for i in range(0, len(market_keys), 2):
            row = [InlineKeyboardButton(f"📊 {market_keys[i]}", callback_data=f"market|{market_keys[i]}")]
            if i + 1 < len(market_keys):
                row.append(InlineKeyboardButton(f"📊 {market_keys[i+1]}", callback_data=f"market|{market_keys[i+1]}"))
            keyboard.append(row)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            "✨ **Pocket Option OTC Manual Analiz Botu**\n\nAnaliz etmək istədiyiniz bazarı seçin:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

def main():
    TOKEN = "8955270050:AAFvYBtK01FzfUulEpR6JBmMEkjw0smgUJo"

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot uğurla işə düşdü...")
    app.run_polling()

if __name__ == "__main__":
    main()
