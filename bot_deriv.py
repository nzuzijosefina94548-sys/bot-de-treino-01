import asyncio
import json
import websockets
import pandas as pd
import numpy as np
from datetime import datetime
import os
import threading
from flask import Flask
import time

# ========================================================================= //
# 🌐 SERVIDOR WEB (para o Koyeb manter o bot acordado)
# ========================================================================= //
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Deriv a correr!", 200

@app.route('/health')
def health():
    return "OK", 200

# ========================================================================= //
# 🔑 CREDENCIAIS (lidas das variáveis de ambiente do Koyeb)
# ========================================================================= //
APP_ID = os.environ.get("APP_ID", "1089")
API_TOKEN = os.environ.get("API_TOKEN", "")

# ========================================================================= //
# ⚙️ CONFIGURAÇÕES (lidas das variáveis de ambiente do Koyeb)
# ========================================================================= //
config = {
    "symbol": os.environ.get("SYMBOL", "R_75"),
    "granularity": int(os.environ.get("GRANULARITY", "300")),
    "estrategia": os.environ.get("ESTRATEGIA", "Rompimento EMA"),
    "ema_periodo": int(os.environ.get("EMA_PERIODO", "21")),
    "ema_stop_pct": float(os.environ.get("EMA_STOP_PCT", "1.0")) / 100,
    "ema_alvo_mult": float(os.environ.get("EMA_ALVO_MULT", "2.5")),
    "slope_periodo": int(os.environ.get("SLOPE_PERIODO", "30")),
    "slope_threshold": float(os.environ.get("SLOPE_THRESHOLD", "0.10")),
    "stop_pontos": float(os.environ.get("STOP_PONTOS", "30.0")),
    "alvo_pontos": float(os.environ.get("ALVO_PONTOS", "500.0")),
    "stake": float(os.environ.get("STAKE", "2.0")),
    "multiplicador": int(os.environ.get("MULTIPLICADOR", "100")),
    "max_derrotas": int(os.environ.get("MAX_DERROTAS", "5")),
    "max_vitorias": int(os.environ.get("MAX_VITORIAS", "20")),
}

DERIV_WS = "wss://ws.binaryws.com/websockets/v3"

# ========================================================================= //
# LOOP PRINCIPAL DO BOT (em tempo real)
# ========================================================================= //
async def bot_loop():
    print(f"🔴 BOT INICIADO - {config['symbol']} | {config['estrategia']}")
    print(f"   App ID: {APP_ID}")
    print(f"   Stake: ${config['stake']} | Mult: {config['multiplicador']}x")

    uri = f"{DERIV_WS}?app_id={APP_ID}"

    try:
        async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as ws:
            # Autenticação
            await ws.send(json.dumps({"authorize": API_TOKEN}))
            auth = json.loads(await ws.recv())
            if 'error' in auth:
                print(f"❌ Erro auth: {auth['error']['message']}")
                return
            print(f"✅ Autenticado: {auth['authorize']['email']}")
            print(f"   Saldo: ${auth['authorize']['balance']:.2f}")

            # Subscrever aos ticks
            await ws.send(json.dumps({"ticks": config['symbol'], "subscribe": 1}))

            pos = None; ep = None; sp = None; tp = None
            ac = False; av = False; mx = None; mn = None
            w = 0; l = 0; blk = False
            ultimos_prices = []
            alvo_pct = config['ema_stop_pct'] * config['ema_alvo_mult']

            while True:
                data = json.loads(await ws.recv())
                if 'tick' not in data:
                    continue

                preco = float(data['tick']['quote'])
                ultimos_prices.append(preco)
                if len(ultimos_prices) > 200:
                    ultimos_prices.pop(0)

                if blk:
                    continue

                # Lógica Rompimento EMA
                if config['estrategia'] == "Rompimento EMA" and len(ultimos_prices) >= config['ema_periodo'] + 2:
                    ema_s = pd.Series(ultimos_prices).ewm(span=config['ema_periodo'], adjust=False).mean()
                    ema = ema_s.iloc[-1]
                    prev_ema = ema_s.iloc[-2]
                    prev_preco = ultimos_prices[-2]

                    if prev_preco <= prev_ema and preco > ema:
                        ac = True; av = False; mx = preco
                    elif prev_preco >= prev_ema and preco < ema:
                        av = True; ac = False; mn = preco

                    if pos is None:
                        if ac and mx and preco > mx:
                            pos = "long"; ep = preco
                            sp = ep * (1 - config['ema_stop_pct'])
                            tp = ep * (1 + alvo_pct)
                            print(f"🟢 COMPRA @ {ep:.2f} | Stop: {sp:.2f} | Alvo: {tp:.2f}")
                            ac = False
                        elif av and mn and preco < mn:
                            pos = "short"; ep = preco
                            sp = ep * (1 + config['ema_stop_pct'])
                            tp = ep * (1 - alvo_pct)
                            print(f"🔴 VENDA @ {ep:.2f} | Stop: {sp:.2f} | Alvo: {tp:.2f}")
                            av = False

                    if pos == "long":
                        if preco <= sp:
                            print(f"❌ STOP Long @ {preco:.2f}")
                            l += 1; w = 0; pos = None
                        elif preco >= tp:
                            print(f"✅ ALVO Long @ {preco:.2f}")
                            w += 1; l = 0; pos = None
                    elif pos == "short":
                        if preco >= sp:
                            print(f"❌ STOP Short @ {preco:.2f}")
                            l += 1; w = 0; pos = None
                        elif preco <= tp:
                            print(f"✅ ALVO Short @ {preco:.2f}")
                            w += 1; l = 0; pos = None

                    if l >= config['max_derrotas']:
                        blk = True
                        print(f"🚨 BLOQUEIO: {l} derrotas seguidas.")
                    if w >= config['max_vitorias']:
                        blk = True
                        print(f"🎉 BLOQUEIO: {w} vitórias seguidas.")

    except Exception as e:
        print(f"❌ Erro: {e}")

# ========================================================================= //
# INICIAR BOT EM THREAD SEPARADA
# ========================================================================= //
def iniciar_bot():
    asyncio.run(bot_loop())

# ========================================================================= //
# INÍCIO
# ========================================================================= //
if __name__ == "__main__":
    # Inicia o bot numa thread para o Flask poder correr em paralelo
    bot_thread = threading.Thread(target=iniciar_bot, daemon=True)
    bot_thread.start()
    # Inicia o servidor web do Koyeb
    porta = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=porta)
