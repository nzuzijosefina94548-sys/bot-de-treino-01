import os
import json
import asyncio
import threading
import time
from datetime import datetime
import websockets
from flask import Flask, render_template_string, jsonify

# ========================================================================= //
# 🔑 CREDENCIAIS (variáveis de ambiente do Back4app)
# ========================================================================= //
APP_ID = os.environ.get("APP_ID", "1089")
API_TOKEN = os.environ.get("API_TOKEN", "")

# ========================================================================= //
# ⚙️ CONFIGURAÇÕES (todas alteráveis via variáveis de ambiente)
# ========================================================================= //
CONFIG = {
    # Mercado
    "symbol": os.environ.get("SYMBOL", "R_100"),
    
    # Banca e Risco
    "banca_inicial": float(os.environ.get("BANCA_INICIAL", "10000.0")),
    "stake": float(os.environ.get("STAKE", "2.0")),
    "multiplicador": int(os.environ.get("MULTIPLICADOR", "45")),
    
    # Gestão de Risco
    "take_profit_usd": float(os.environ.get("TAKE_PROFIT", "2.50")),
    "stop_loss_usd": float(os.environ.get("STOP_LOSS", "0.10")),
    
    # Duração do contrato
    "duracao_valor": int(os.environ.get("DURACAO_VALOR", "1")),
    "duracao_unidade": os.environ.get("DURACAO_UNIDADE", "d"),
}

DERIV_WS = "wss://ws.binaryws.com/websockets/v3"

# ========================================================================= //
# ESTADO GLOBAL (mostrado no dashboard)
# ========================================================================= //
estado = {
    "conectado": False,
    "email": "",
    "banca": CONFIG["banca_inicial"],
    "banca_inicial": CONFIG["banca_inicial"],
    "direcao": "NEUTRO",
    "total_trades": 0,
    "vitorias": 0,
    "derrotas": 0,
    "pnl_total": 0.0,
    "ultimo_preco": 0.0,
    "contrato_ativo": None,
    "logs": [],
    "iniciado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
}

def add_log(msg):
    hora = datetime.now().strftime("%H:%M:%S")
    linha = f"[{hora}] {msg}"
    print(linha, flush=True)
    estado["logs"].append(linha)
    if len(estado["logs"]) > 100:
        estado["logs"].pop(0)

# ========================================================================= //
# SERVIDOR WEB (Flask) — para Back4app + UptimeRobot
# ========================================================================= //
app = Flask(__name__)

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Bot Deriv - Stop & Reverse</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="10">
    <style>
        * { box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #0f0f1e; color: #eee; padding: 12px; margin: 0; }
        h1 { color: #00ff88; font-size: 20px; margin: 5px 0 15px 0; text-align: center; }
        h2 { color: #00ccff; font-size: 15px; margin: 0 0 10px 0; }
        .card { background: #16213e; border-radius: 10px; padding: 14px; margin: 10px 0; }
        .metrics { display: flex; flex-wrap: wrap; gap: 10px; }
        .metric { flex: 1 1 45%; min-width: 100px; }
        .label { font-size: 11px; color: #999; text-transform: uppercase; }
        .value { font-size: 20px; font-weight: bold; color: #00ff88; }
        .green { color: #00ff88; }
        .red { color: #ff4444; }
        .yellow { color: #ffcc00; }
        .blue { color: #00ccff; }
        .gray { color: #888; }
        .log { font-family: monospace; font-size: 10px; background: #0a0a15; padding: 10px; border-radius: 5px; max-height: 350px; overflow-y: auto; line-height: 1.5; }
        .badge { display: inline-block; padding: 3px 8px; border-radius: 5px; font-size: 11px; }
        .badge-on { background: #00ff88; color: #000; }
        .badge-off { background: #ff4444; color: #fff; }
    </style>
</head>
<body>
    <h1>🤖 Bot Deriv - Stop & Reverse</h1>
    
    <div class="card">
        <h2>📊 Estado</h2>
        <div class="metrics">
            <div class="metric">
                <div class="label">Conexão</div>
                <div class="value"><span class="badge {{ 'badge-on' if estado.conectado else 'badge-off' }}">{{ 'LIGADO' if estado.conectado else 'DESLIGADO' }}</span></div>
            </div>
            <div class="metric">
                <div class="label">Email</div>
                <div class="value blue" style="font-size: 12px; word-break: break-all;">{{ estado.email or '—' }}</div>
            </div>
            <div class="metric">
                <div class="label">Banca Atual</div>
                <div class="value">${{ '%.2f'|format(estado.banca) }}</div>
            </div>
            <div class="metric">
                <div class="label">Direção</div>
                <div class="value yellow">{{ estado.direcao }}</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h2>💹 Mercado</h2>
        <div class="metrics">
            <div class="metric">
                <div class="label">Símbolo</div>
                <div class="value blue">{{ config.symbol }}</div>
            </div>
            <div class="metric">
                <div class="label">Preço Atual</div>
                <div class="value">{{ '%.2f'|format(estado.ultimo_preco) }}</div>
            </div>
            <div class="metric">
                <div class="label">Contrato Ativo</div>
                <div class="value blue" style="font-size: 12px;">{{ estado.contrato_ativo or '—' }}</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h2>🎯 Desempenho</h2>
        <div class="metrics">
            <div class="metric">
                <div class="label">Total Trades</div>
                <div class="value">{{ estado.total_trades }}</div>
            </div>
            <div class="metric">
                <div class="label">Vitórias</div>
                <div class="value green">{{ estado.vitorias }}</div>
            </div>
            <div class="metric">
                <div class="label">Derrotas</div>
                <div class="value red">{{ estado.derrotas }}</div>
            </div>
            <div class="metric">
                <div class="label">P&L Total</div>
                <div class="value {{ 'green' if estado.pnl_total >= 0 else 'red' }}">${{ '%.2f'|format(estado.pnl_total) }}</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h2>⚙️ Configuração</h2>
        <div class="metrics">
            <div class="metric">
                <div class="label">Stake</div>
                <div class="value">${{ config.stake }}</div>
            </div>
            <div class="metric">
                <div class="label">Multiplicador</div>
                <div class="value">{{ config.multiplicador }}x</div>
            </div>
            <div class="metric">
                <div class="label">Take Profit</div>
                <div class="value green">${{ config.take_profit_usd }}</div>
            </div>
            <div class="metric">
                <div class="label">Stop Loss</div>
                <div class="value red">${{ config.stop_loss_usd }}</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h2>📜 Logs (últimos 30)</h2>
        <div class="log">{% for l in estado.logs[-30:] %}{{ l }}<br>{% endfor %}</div>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(DASHBOARD_HTML, estado=estado, config=CONFIG)

@app.route('/health')
def health():
    return "OK", 200

@app.route('/status')
def status():
    return jsonify(estado)

# ========================================================================= //
# FUNÇÕES DA API DERIV
# ========================================================================= //
async def abrir_contrato(ws, tipo):
    """Abre um contrato Multiplier com TP/SL definidos."""
    stake = CONFIG["stake"]
    mult = CONFIG["multiplicador"]
    tp = CONFIG["take_profit_usd"]
    sl = CONFIG["stop_loss_usd"]

    # 1. Pedir proposta
    proposta = {
        "proposal": 1,
        "amount": stake,
        "basis": "stake",
        "contract_type": tipo,
        "currency": "USD",
        "duration": CONFIG["duracao_valor"],
        "duration_unit": CONFIG["duracao_unidade"],
        "symbol": CONFIG["symbol"],
        "multiplier": mult,
        "limit_order": {
            "take_profit": tp,
            "stop_loss": sl
        }
    }

    await ws.send(json.dumps(proposta))
    resp = json.loads(await ws.recv())

    if 'error' in resp:
        add_log(f"❌ Erro na proposta: {resp['error']['message']}")
        return None

    proposal_id = resp['proposal']['id']
    add_log(f"📋 Proposta recebida: {proposal_id[:20]}...")

    # 2. Comprar contrato
    compra = {"buy": proposal_id, "price": stake}
    await ws.send(json.dumps(compra))
    resp_buy = json.loads(await ws.recv())

    if 'error' in resp_buy:
        add_log(f"❌ Erro na compra: {resp_buy['error']['message']}")
        return None

    contract_id = resp_buy['buy']['contract_id']
    add_log(f"📄 Contrato aberto: #{contract_id}")

    # 3. Subscrever ao contrato para monitorizar
    await ws.send(json.dumps({
        "proposal_open_contract": 1,
        "contract_id": contract_id,
        "subscribe": 1
    }))

    estado["contrato_ativo"] = contract_id
    return contract_id

# ========================================================================= //
# LOOP PRINCIPAL DO BOT
# ========================================================================= //
async def bot_loop():
    if not API_TOKEN:
        add_log("❌ ERRO: API_TOKEN não configurado!")
        return

    while True:
        try:
            add_log("🔌 A conectar à Deriv...")
            uri = f"{DERIV_WS}?app_id={APP_ID}"

            async with websockets.connect(uri, ping_interval=30, ping_timeout=20) as ws:
                # Autenticação
                await ws.send(json.dumps({"authorize": API_TOKEN}))
                auth = json.loads(await ws.recv())

                if 'error' in auth:
                    add_log(f"❌ Erro de auth: {auth['error']['message']}")
                    await asyncio.sleep(30)
                    continue

                estado["conectado"] = True
                estado["email"] = auth['authorize']['email']
                estado["banca"] = float(auth['authorize']['balance'])
                add_log(f"✅ Conectado: {estado['email']}")
                add_log(f"💰 Saldo: ${estado['banca']:.2f}")

                # Subscrever aos ticks
                await ws.send(json.dumps({"ticks": CONFIG["symbol"], "subscribe": 1}))
                add_log(f"📈 A monitorizar {CONFIG['symbol']}...")

                direcao = 1  # 1=compra, -1=venda
                contrato_ativo = None
                primeiro_tick = True

                while True:
                    msg = json.loads(await ws.recv())

                    # --- TICK (preço em tempo real) ---
                    if 'tick' in msg:
                        preco = float(msg['tick']['quote'])
                        estado["ultimo_preco"] = preco

                        # Primeira entrada
                        if primeiro_tick:
                            add_log(f"🎬 Iniciando primeira operação...")
                            tipo = "MULTUP" if direcao == 1 else "MULTDN"
                            contrato_ativo = await abrir_contrato(ws, tipo)
                            estado["direcao"] = "COMPRA" if direcao == 1 else "VENDA"
                            primeiro_tick = False

                    # --- CONTRATO FECHADO ---
                    elif 'proposal_open_contract' in msg:
                        contrato = msg['proposal_open_contract']

                        if contrato.get('is_sold'):
                            profit = float(contrato.get('profit', 0))
                            estado["pnl_total"] += profit
                            estado["total_trades"] += 1

                            if profit > 0:
                                estado["vitorias"] += 1
                                add_log(f"✅ ALVO! Lucro: +${profit:.2f}")
                                # Continua na MESMA direção
                            else:
                                estado["derrotas"] += 1
                                add_log(f"❌ STOP! Perda: ${profit:.2f}")
                                # INVERTE a direção
                                direcao = -direcao
                                add_log(f"🔄 Revertendo para {'COMPRA' if direcao == 1 else 'VENDA'}")

                            # Pedir saldo atualizado
                            await ws.send(json.dumps({"balance": 1}))

                            # Abrir próxima operação
                            contrato_ativo = None
                            tipo = "MULTUP" if direcao == 1 else "MULTDN"
                            add_log(f"🚀 Abrindo próxima operação ({'COMPRA' if direcao == 1 else 'VENDA'})...")
                            contrato_ativo = await abrir_contrato(ws, tipo)
                            estado["direcao"] = "COMPRA" if direcao == 1 else "VENDA"

                    # --- BALANÇO ---
                    elif 'balance' in msg:
                        estado["banca"] = float(msg['balance']['balance'])

        except websockets.exceptions.ConnectionClosed:
            estado["conectado"] = False
            add_log("⚠️ Conexão fechada. A reconectar em 10s...")
            await asyncio.sleep(10)
        except Exception as e:
            estado["conectado"] = False
            add_log(f"⚠️ Erro: {e}")
            await asyncio.sleep(10)

# ========================================================================= //
# INICIAR BOT EM THREAD SEPARADA
# ========================================================================= //
def iniciar_bot():
    asyncio.run(bot_loop())

# ========================================================================= //
# INÍCIO
# ========================================================================= //
if __name__ == "__main__":
    add_log("=" * 50)
    add_log("🤖 BOT DERIV - STOP & REVERSE")
    add_log(f"   Símbolo: {CONFIG['symbol']}")
    add_log(f"   Stake: ${CONFIG['stake']} | Multiplicador: {CONFIG['multiplicador']}x")
    add_log(f"   Take Profit: ${CONFIG['take_profit_usd']} | Stop Loss: ${CONFIG['stop_loss_usd']}")
    add_log(f"   Banca Inicial: ${CONFIG['banca_inicial']}")
    add_log("=" * 50)

    # Iniciar bot numa thread
    thread = threading.Thread(target=iniciar_bot, daemon=True)
    thread.start()

    # Iniciar servidor web
    porta = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=porta)
