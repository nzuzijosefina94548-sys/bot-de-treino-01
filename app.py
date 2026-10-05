import os
import time
import threading
from datetime import datetime
from flask import Flask, jsonify
from binance.client import Client

# ========================================================================= //
# SERVIDOR WEB (Para o Render manter o bot acordado)
# ========================================================================= //
app = Flask(__name__)

# ========================================================================= //
# CONFIGURAÇÕES (LIDAS DAS VARIÁVEIS DE AMBIENTE DO RENDER)
# ========================================================================= //
API_KEY = os.environ.get("API_KEY", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "")

config = {
    "symbol": os.environ.get("SYMBOL", "BTCUSDT"),
    "intervalo": int(os.environ.get("INTERVALO", "30")),
    "lucro_desejado": float(os.environ.get("LUCRO_DESEJADO", "1.0")) / 100,
    "taxa": float(os.environ.get("TAXA", "0.1")) / 100,
    "banca_inicial": float(os.environ.get("BANCA_INICIAL", "1000.0")),
    "alavancagem": int(os.environ.get("ALAVANCAGEM", "1")),
    "max_vitorias": int(os.environ.get("MAX_VITORIAS", "3")),
    "max_derrotas": int(os.environ.get("MAX_DERROTAS", "3")),
    "estrategia": int(os.environ.get("ESTRATEGIA", "1"))
}

# ========================================================================= //
# ESTADO GLOBAL DO BOT (Para consulta via web)
# ========================================================================= //
estado = {
    "ativo": False,
    "capital": config["banca_inicial"],
    "preco_atual": 0.0,
    "preco_referencia": 0.0,
    "direcao": "NEUTRO",
    "vitorias": 0,
    "derrotas": 0,
    "perda_anterior": 0.0,
    "bloqueado": False,
    "ultima_atualizacao": "—",
    "logs": []
}

def log(msg):
    """Adiciona mensagem ao log e imprime no console."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{timestamp}] {msg}"
    print(linha)
    estado["logs"].append(linha)
    if len(estado["logs"]) > 50:
        estado["logs"].pop(0)

# ========================================================================= //
# FUNÇÕES DA ESTRATÉGIA
# ========================================================================= //
def calcular_fator_alvo(perda_anterior):
    if config["estrategia"] == 1:  # Normal
        return config["lucro_desejado"] + config["taxa"]
    elif config["estrategia"] == 2:  # Recuperação Cirúrgica
        if perda_anterior > 0:
            return perda_anterior + config["taxa"] * 2 + config["lucro_desejado"]
        else:
            return config["lucro_desejado"] + config["taxa"]
    else:  # Recuperação Simples
        if perda_anterior > 0:
            return perda_anterior + config["taxa"] * 2
        else:
            return config["lucro_desejado"] + config["taxa"]

# ========================================================================= //
# LOOP PRINCIPAL DO BOT
# ========================================================================= //
def bot_loop():
    log("🤖 BOT INICIADO!")
    log(f"   Par: {config['symbol']} | Estratégia: {config['estrategia']}")
    log(f"   Banca: ${config['banca_inicial']:.2f} | Alavancagem: {config['alavancagem']}x")
    log(f"   Lucro: {config['lucro_desejado']*100}% | Taxa: {config['taxa']*100}%")

    if not API_KEY or not SECRET_KEY:
        log("❌ ERRO: API_KEY ou SECRET_KEY não configuradas!")
        return

    try:
        client = Client(API_KEY, SECRET_KEY, testnet=True)
        client.API_URL = 'https://testnet.binance.vision/api'
    except Exception as e:
        log(f"❌ Erro ao conectar à Binance: {e}")
        return

    capital = config["banca_inicial"]
    preco_referencia = None
    direcao = 0
    preco_entrada = None
    alvo = None
    stop = None
    vitorias = 0
    derrotas = 0
    perda_anterior = 0.0
    bloqueado = False

    estado["ativo"] = True

    while estado["ativo"]:
        try:
            ticker = client.get_symbol_ticker(symbol=config["symbol"])
            preco = float(ticker['price'])
            estado["preco_atual"] = preco
            estado["ultima_atualizacao"] = datetime.now().strftime("%H:%M:%S")

            if preco_referencia is None:
                preco_referencia = preco
                estado["preco_referencia"] = preco
                log(f"📌 Preço de referência: ${preco_referencia:,.2f}")
                time.sleep(config["intervalo"])
                continue

            if bloqueado:
                log(f"🔒 BLOQUEADO | V:{vitorias} D:{derrotas}")
                time.sleep(config["intervalo"])
                continue

            if direcao == 0:
                fator = calcular_fator_alvo(perda_anterior)
                if preco >= preco_referencia * (1 + config["lucro_desejado"]):
                    direcao = 1
                    preco_entrada = preco_referencia * (1 + config["lucro_desejado"])
                    alvo = preco_entrada * (1 + fator)
                    stop = preco_entrada * (1 - config["lucro_desejado"] - config["taxa"])
                    log(f"🟢 GATILHO ALTA | Entrada: ${preco_entrada:,.2f} | Alvo: ${alvo:,.2f} | Stop: ${stop:,.2f}")
                elif preco <= preco_referencia * (1 - config["lucro_desejado"]):
                    direcao = -1
                    preco_entrada = preco_referencia * (1 - config["lucro_desejado"])
                    alvo = preco_entrada * (1 - fator)
                    stop = preco_entrada * (1 + config["lucro_desejado"] + config["taxa"])
                    log(f"🔴 GATILHO BAIXA | Entrada: ${preco_entrada:,.2f} | Alvo: ${alvo:,.2f} | Stop: ${stop:,.2f}")

            elif direcao == 1:
                if preco >= alvo:
                    lucro_pct = ((alvo - preco_entrada) / preco_entrada) * 100
                    capital *= (1 + (lucro_pct * config["alavancagem"]) / 100)
                    vitorias += 1
                    derrotas = 0
                    perda_anterior = 0.0
                    log(f"✅ ALVO | Lucro: {lucro_pct:.2f}% | Capital: ${capital:.2f}")
                    preco_referencia = alvo
                    direcao = 0
                elif preco <= stop:
                    perda_pct = ((preco_entrada - stop) / preco_entrada) * 100
                    capital *= (1 - (perda_pct * config["alavancagem"]) / 100)
                    derrotas += 1
                    vitorias = 0
                    perda_anterior = abs(perda_pct / 100) + config["taxa"]
                    log(f"❌ STOP | Perda: {perda_pct:.2f}% | Capital: ${capital:.2f}")
                    preco_referencia = stop
                    direcao = -1
                    preco_entrada = stop
                    fator = calcular_fator_alvo(perda_anterior)
                    alvo = preco_entrada * (1 - fator)
                    stop = preco_entrada * (1 + config["lucro_desejado"] + config["taxa"])

            elif direcao == -1:
                if preco <= alvo:
                    lucro_pct = ((preco_entrada - alvo) / preco_entrada) * 100
                    capital *= (1 + (lucro_pct * config["alavancagem"]) / 100)
                    vitorias += 1
                    derrotas = 0
                    perda_anterior = 0.0
                    log(f"✅ ALVO | Lucro: {lucro_pct:.2f}% | Capital: ${capital:.2f}")
                    preco_referencia = alvo
                    direcao = 0
                elif preco >= stop:
                    perda_pct = ((stop - preco_entrada) / preco_entrada) * 100
                    capital *= (1 - (perda_pct * config["alavancagem"]) / 100)
                    derrotas += 1
                    vitorias = 0
                    perda_anterior = abs(perda_pct / 100) + config["taxa"]
                    log(f"❌ STOP | Perda: {perda_pct:.2f}% | Capital: ${capital:.2f}")
                    preco_referencia = stop
                    direcao = 1
                    preco_entrada = stop
                    fator = calcular_fator_alvo(perda_anterior)
                    alvo = preco_entrada * (1 + fator)
                    stop = preco_entrada * (1 - config["lucro_desejado"] - config["taxa"])

            if vitorias >= config["max_vitorias"] or derrotas >= config["max_derrotas"]:
                bloqueado = True
                log(f"🚨 BLOQUEIO! V:{vitorias} D:{derrotas}")

            # Atualizar estado global
            estado["capital"] = capital
            estado["vitorias"] = vitorias
            estado["derrotas"] = derrotas
            estado["perda_anterior"] = perda_anterior
            estado["bloqueado"] = bloqueado
            estado["direcao"] = "NEUTRO" if direcao == 0 else ("LONG" if direcao == 1 else "SHORT")

            time.sleep(config["intervalo"])

        except Exception as e:
            log(f"⚠️ Erro: {e}")
            time.sleep(config["intervalo"])

    log("⏹️ BOT PARADO.")
    estado["ativo"] = False

# ========================================================================= //
# ROTAS DO SERVIDOR WEB
# ========================================================================= //
@app.route('/')
def home():
    """Página principal com o estado do bot em HTML."""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Bot Escada Dinâmica</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta http-equiv="refresh" content="10">
        <style>
            body {{ font-family: Arial; background: #1a1a2e; color: #eee; padding: 15px; }}
            .card {{ background: #16213e; border-radius: 10px; padding: 15px; margin: 10px 0; }}
            h1 {{ color: #00ff88; font-size: 22px; }}
            .metric {{ display: inline-block; margin: 8px 15px 8px 0; }}
            .value {{ font-size: 24px; color: #00ff88; }}
            .label {{ font-size: 12px; color: #999; }}
            .log {{ font-family: monospace; font-size: 11px; background: #0f0f1e; padding: 10px; border-radius: 5px; max-height: 400px; overflow-y: auto; }}
            .green {{ color: #00ff88; }}
            .red {{ color: #ff4444; }}
            .yellow {{ color: #ffcc00; }}
        </style>
    </head>
    <body>
        <h1>🤖 Bot Escada Dinâmica</h1>
        
        <div class="card">
            <h2>📊 Estado</h2>
            <div class="metric"><span class="label">Estado</span><br><span class="value {'green' if estado['ativo'] else 'red'}">{'ATIVO' if estado['ativo'] else 'PARADO'}</span></div>
            <div class="metric"><span class="label">Capital</span><br><span class="value">${estado['capital']:.2f}</span></div>
            <div class="metric"><span class="label">Direção</span><br><span class="value yellow">{estado['direcao']}</span></div>
            <div class="metric"><span class="label">Bloqueado</span><br><span class="value {'red' if estado['bloqueado'] else 'green'}">{'SIM' if estado['bloqueado'] else 'NÃO'}</span></div>
        </div>

        <div class="card">
            <h2>💹 Mercado</h2>
            <div class="metric"><span class="label">Preço Atual</span><br><span class="value">${estado['preco_atual']:,.2f}</span></div>
            <div class="metric"><span class="label">Preço Referência</span><br><span class="value">${estado['preco_referencia']:,.2f}</span></div>
            <div class="metric"><span class="label">Última Atualização</span><br><span class="value">{estado['ultima_atualizacao']}</span></div>
        </div>

        <div class="card">
            <h2>🎯 Desempenho</h2>
            <div class="metric"><span class="label">Vitórias</span><br><span class="value green">{estado['vitorias']}</span></div>
            <div class="metric"><span class="label">Derrotas</span><br><span class="value red">{estado['derrotas']}</span></div>
            <div class="metric"><span class="label">Perda Anterior</span><br><span class="value">${estado['perda_anterior']:.4f}</span></div>
        </div>

        <div class="card">
            <h2>📜 Logs (últimos 20)</h2>
            <div class="log">
                {'<br>'.join(estado['logs'][-20:])}
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/status')
def status():
    """Endpoint JSON com o estado atual."""
    return jsonify(estado)

@app.route('/health')
def health():
    """Endpoint para o Render verificar se está vivo."""
    return "OK", 200

# ========================================================================= //
# INICIALIZAÇÃO
# ========================================================================= //
def iniciar_bot():
    """Inicia o bot numa thread separada."""
    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()

if __name__ == "__main__":
    iniciar_bot()
    porta = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=porta)
