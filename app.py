import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import yfinance as yf

# ========================================================================= //
# CONFIGURAÇÃO
# ========================================================================= //
st.set_page_config(page_title="Bot Multi-Ativos", page_icon="🤖", layout="wide")
st.title("🤖 Painel do Bot - Multi-Ativos e Multi-Estratégias")

# ========================================================================= //
# MENU LATERAL
# ========================================================================= //
st.sidebar.header("⚙️ Configurações")
modo = st.sidebar.selectbox("Modo de Operação", ["Backtest (Passado)", "Live/Demo (Tempo Real)"])

# ========================================================================= //
# 1. ATIVO
# ========================================================================= //
st.sidebar.subheader("📈 Ativo")
categoria = st.sidebar.selectbox("Categoria",
    ["🪙 Criptomoedas", "🥇 Metais Preciosos", "💱 Forex", "📊 Índices", "🛢️ Commodities", "✏️ Personalizado"])

ATIVOS = {
    "🪙 Criptomoedas": {"BTC (Bitcoin)": "BTC-USD", "ETH (Ethereum)": "ETH-USD",
        "BNB (Binance Coin)": "BNB-USD", "SOL (Solana)": "SOL-USD", "XRP (Ripple)": "XRP-USD",
        "ADA (Cardano)": "ADA-USD", "DOGE (Dogecoin)": "DOGE-USD", "AVAX (Avalanche)": "AVAX-USD",
        "DOT (Polkadot)": "DOT-USD", "MATIC (Polygon)": "MATIC-USD", "LINK (Chainlink)": "LINK-USD",
        "LTC (Litecoin)": "LTC-USD", "BCH (Bitcoin Cash)": "BCH-USD", "TRX (Tron)": "TRX-USD",
        "SHIB (Shiba Inu)": "SHIB-USD"},
    "🥇 Metais Preciosos": {"XAU (Ouro Futuros)": "GC=F", "XAG (Prata Futuros)": "SI=F",
        "Platina": "PL=F", "Paládio": "PA=F", "Ouro Spot (XAU/USD)": "XAUUSD=X",
        "Prata Spot (XAG/USD)": "XAGUSD=X"},
    "💱 Forex": {"EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "JPY=X",
        "AUD/USD": "AUDUSD=X", "USD/CAD": "CAD=X", "USD/CHF": "CHF=X", "NZD/USD": "NZDUSD=X",
        "EUR/GBP": "EURGBP=X", "EUR/JPY": "EURJPY=X", "GBP/JPY": "GBPJPY=X", "USD/BRL": "BRL=X",
        "USD/ZAR": "ZAR=X"},
    "📊 Índices": {"S&P 500": "^GSPC", "Nasdaq": "^IXIC", "Dow Jones": "^DJI",
        "DAX (Alemanha)": "^GDAXI", "FTSE 100 (UK)": "^FTSE", "Nikkei 225 (Japão)": "^N225",
        "IBOVESPA (Brasil)": "^BVSP"},
    "🛢️ Commodities": {"Petróleo WTI": "CL=F", "Petróleo Brent": "BZ=F", "Gás Natural": "NG=F",
        "Cobre": "HG=F", "Trigo": "ZW=F", "Milho": "ZC=F", "Café": "KC=F", "Açúcar": "SB=F"},
}

if categoria == "✏️ Personalizado":
    ticker = st.sidebar.text_input("Digite o ticker (Yahoo Finance)", "BTC-USD")
    nome_ativo = ticker
else:
    ativos_cat = ATIVOS[categoria]
    nome_ativo = st.sidebar.selectbox("Escolha o ativo", list(ativos_cat.keys()))
    ticker = ativos_cat[nome_ativo]

st.sidebar.caption(f"📌 Ticker: `{ticker}`")

# ========================================================================= //
# 2. BANCA E RISCO
# ========================================================================= //
st.sidebar.subheader("💰 Banca e Risco")
banca_inicial = st.sidebar.number_input("Banca Inicial (USDT)", min_value=10.0, max_value=1000000.0, value=1000.0, step=100.0)
usar_alavancagem = st.sidebar.checkbox("Usar Alavancagem?", value=False)
alavancagem = st.sidebar.slider("Alavancagem (x)", min_value=1, max_value=20, value=1, step=1) if usar_alavancagem else 1
fee = st.sidebar.number_input("Taxa da Corretora (%)", min_value=0.0, max_value=2.0, value=0.10, step=0.01) / 100

# ========================================================================= //
# 3. TIMEFRAME
# ========================================================================= //
timeframe = st.sidebar.selectbox("Timeframe",
    ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "3d", "1s", "1M", "3M", "1A"], index=4)

# ========================================================================= //
# 4. ESTRATÉGIA
# ========================================================================= //
st.sidebar.subheader("🎯 Estratégia")
tipo_estrategia = st.sidebar.radio("Escolha a estratégia:",
    ["Normal (Alvo Fixo)",
     "Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)",
     "Recuperação Simples (Apenas Perda Anterior + Taxas)",
     "Rompimento EMA"])

# ========================================================================= //
# 5. PARÂMETROS DA ESTRATÉGIA (SEMPRE VISÍVEIS!)
# ========================================================================= //
st.sidebar.subheader("📊 Parâmetros da Estratégia")

step = st.sidebar.number_input(
    "Lucro Desejado (%)",
    min_value=0.1, max_value=10.0, value=1.0, step=0.1,
    help="Movimento do preço que ativa a entrada"
) / 100

ema_stop_pct = st.sidebar.number_input(
    "Stop Loss (%)",
    min_value=0.01, max_value=10.0, value=1.0, step=0.1,
    help="Perda máxima por operação"
) / 100

ema_periodo = st.sidebar.number_input(
    "Período da EMA",
    min_value=2, max_value=500, value=21,
    help="Média Móvel Exponencial (usada na estratégia Rompimento EMA)"
)

ema_alvo_mult = st.sidebar.number_input(
    "Multiplicador do Alvo (EMA)",
    min_value=0.5, max_value=50.0, value=0.9, step=0.1,
    help="Alvo da EMA = Stop × Multiplicador"
)

# ========================================================================= //
# 6. LIMITES
# ========================================================================= //
st.sidebar.subheader("🔒 Limites de Segurança")
max_wins = st.sidebar.number_input("Máx. Vitórias Seguidas", min_value=1, max_value=50, value=20)
max_losses = st.sidebar.number_input("Máx. Derrotas Seguidas", min_value=1, max_value=50, value=10)

# ========================================================================= //
# 7. PERÍODO DO BACKTEST
# ========================================================================= //
if modo == "Backtest (Passado)":
    st.sidebar.subheader("Período do Backtest")
    data_inicio = st.sidebar.date_input("Data de Início", datetime.now() - timedelta(days=30))
    data_fim = st.sidebar.date_input("Data de Fim", datetime.now())

if modo == "Live/Demo (Tempo Real)":
    st.sidebar.subheader("Credenciais da Demo (Binance)")
    api_key = st.sidebar.text_input("API Key", type="password")
    secret_key = st.sidebar.text_input("Secret Key", type="password")

# ========================================================================= //
# FUNÇÃO: BAIXAR DADOS
# ========================================================================= //
@st.cache_data(ttl=300)
def baixar_dados_yahoo(ticker, timeframe, start_str, end_str):
    try:
        yf_interval = timeframe
        for k, v in [("2h","1h"),("4h","1h"),("6h","1h"),("12h","1h"),("3d","1d"),
                     ("1A","1mo"),("1s","1wk"),("1M","1mo"),("3M","3mo")]:
            if timeframe == k: yf_interval = v

        df = yf.download(ticker, start=start_str, end=end_str, interval=yf_interval, progress=False)
        if df.empty:
            st.warning(f"Sem dados para {ticker} no timeframe {timeframe}.")
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.reset_index(inplace=True)
        df.rename(columns={'Date':'timestamp','Datetime':'timestamp','Open':'open',
                            'High':'high','Low':'low','Close':'close'}, inplace=True)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        for c in ['open','high','low','close']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df.dropna(subset=['open','high','low','close'], inplace=True)
        return df
    except Exception as e:
        st.error(f"Erro: {e}")
        return pd.DataFrame()

# ========================================================================= //
# ESTRATÉGIA 1, 2, 3 - ESCADA DINÂMICA
# ========================================================================= //
def simular_escada(df, step, stop_pct, fee, max_wins, max_losses, tipo_estrategia, banca_inicial, alavancagem):
    trades = []
    capital = banca_inicial
    ref_price = df['close'].iloc[0]
    direction = 0
    entry_price = None
    tp = None
    sl = None
    wins = 0; losses = 0; blocked = False; horario_entrada = None
    perda_total_anterior = 0.0
    bloqueios_por_derrota = 0; bloqueios_por_vitoria = 0

    for i, row in df.iterrows():
        high, low, close, ts = row['high'], row['low'], row['close'], row['timestamp']
        if blocked: continue

        if direction == 0:
            if tipo_estrategia == "Normal (Alvo Fixo)":
                fator_alvo = step + fee
            elif tipo_estrategia == "Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)":
                fator_alvo = (perda_total_anterior + fee + fee + step) if perda_total_anterior > 0 else (step + fee)
            else:
                fator_alvo = (perda_total_anterior + fee + fee) if perda_total_anterior > 0 else (step + fee)

            if high >= ref_price * (1 + step):
                direction = 1
                entry_price = ref_price * (1 + step)
                tp = entry_price * (1 + fator_alvo)
                sl = entry_price * (1 - stop_pct - fee)
                horario_entrada = ts
            elif low <= ref_price * (1 - step):
                direction = -1
                entry_price = ref_price * (1 - step)
                tp = entry_price * (1 - fator_alvo)
                sl = entry_price * (1 + stop_pct + fee)
                horario_entrada = ts

        elif direction == 1:
            if low <= sl:
                pnl_pct = ((sl - entry_price) / entry_price) * 100
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                perda_total_anterior = abs(pnl_pct / 100)
                trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": entry_price,
                                "Saída": sl, "Resultado": "Stop", "P&L (%)": pnl_pct, "Capital": capital})
                losses += 1; wins = 0; direction = -1; ref_price = sl; entry_price = sl
                if tipo_estrategia == "Normal (Alvo Fixo)": fator_alvo = step + fee
                elif tipo_estrategia == "Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)": fator_alvo = perda_total_anterior + fee + fee + step
                else: fator_alvo = perda_total_anterior + fee + fee
                tp = entry_price * (1 - fator_alvo)
                sl = entry_price * (1 + stop_pct + fee)
                horario_entrada = ts
            elif high >= tp:
                pnl_pct = ((tp - entry_price) / entry_price) * 100
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                perda_total_anterior = 0.0
                trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": entry_price,
                                "Saída": tp, "Resultado": "Alvo", "P&L (%)": pnl_pct, "Capital": capital})
                wins += 1; losses = 0; ref_price = tp; entry_price = tp
                fator_alvo = step + fee
                tp = entry_price * (1 + fator_alvo)
                sl = entry_price * (1 - stop_pct - fee)
                horario_entrada = ts

        elif direction == -1:
            if high >= sl:
                pnl_pct = ((entry_price - sl) / entry_price) * 100
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                perda_total_anterior = abs(pnl_pct / 100)
                trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": entry_price,
                                "Saída": sl, "Resultado": "Stop", "P&L (%)": pnl_pct, "Capital": capital})
                losses += 1; wins = 0; direction = 1; ref_price = sl; entry_price = sl
                if tipo_estrategia == "Normal (Alvo Fixo)": fator_alvo = step + fee
                elif tipo_estrategia == "Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)": fator_alvo = perda_total_anterior + fee + fee + step
                else: fator_alvo = perda_total_anterior + fee + fee
                tp = entry_price * (1 + fator_alvo)
                sl = entry_price * (1 - stop_pct - fee)
                horario_entrada = ts
            elif low <= tp:
                pnl_pct = ((entry_price - tp) / entry_price) * 100
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                perda_total_anterior = 0.0
                trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": entry_price,
                                "Saída": tp, "Resultado": "Alvo", "P&L (%)": pnl_pct, "Capital": capital})
                wins += 1; losses = 0; ref_price = tp; entry_price = tp
                fator_alvo = step + fee
                tp = entry_price * (1 - fator_alvo)
                sl = entry_price * (1 + stop_pct + fee)
                horario_entrada = ts

        if losses >= max_losses:
            blocked = True; bloqueios_por_derrota += 1
            trades.append({"Data": ts, "Direção": "-", "Entrada": 0, "Saída": 0,
                            "Resultado": "BLOQUEIO", "P&L (%)": 0, "Capital": capital})
            wins = 0; losses = 0
        if wins >= max_wins:
            blocked = True; bloqueios_por_vitoria += 1
            trades.append({"Data": ts, "Direção": "-", "Entrada": 0, "Saída": 0,
                            "Resultado": "BLOQUEIO", "P&L (%)": 0, "Capital": capital})
            wins = 0; losses = 0

    return trades, capital, bloqueios_por_derrota, bloqueios_por_vitoria

# ========================================================================= //
# ESTRATÉGIA 4 - ROMPIMENTO EMA
# ========================================================================= //
def simular_rompimento_ema(df, ema_periodo, stop_pct, alvo_mult, fee, max_wins, max_losses, banca_inicial, alavancagem):
    trades = []
    capital = banca_inicial
    df = df.copy()
    df['ema'] = df['close'].ewm(span=ema_periodo, adjust=False).mean()
    alerta_compra = False; alerta_venda = False
    maxima_vela_alerta = None; minima_vela_alerta = None
    direcao = 0; entry_price = None; tp = None; sl = None
    wins = 0; losses = 0; blocked = False; horario_entrada = None
    bloqueios_por_derrota = 0; bloqueios_por_vitoria = 0
    alvo_pct = stop_pct * alvo_mult

    for i, row in df.iterrows():
        if i == 0: continue
        high, low, close, ts, ema = row['high'], row['low'], row['close'], row['timestamp'], row['ema']
        prev_close = df['close'].iloc[i-1]; prev_ema = df['ema'].iloc[i-1]
        if blocked: continue

        if prev_close <= prev_ema and close > ema:
            alerta_compra = True; alerta_venda = False; maxima_vela_alerta = high
        elif prev_close >= prev_ema and close < ema:
            alerta_venda = True; alerta_compra = False; minima_vela_alerta = low

        if direcao == 0:
            if alerta_compra and maxima_vela_alerta and high > maxima_vela_alerta:
                direcao = 1; entry_price = maxima_vela_alerta
                sl = entry_price * (1 - stop_pct); tp = entry_price * (1 + alvo_pct)
                horario_entrada = ts; alerta_compra = False
            elif alerta_venda and minima_vela_alerta and low < minima_vela_alerta:
                direcao = -1; entry_price = minima_vela_alerta
                sl = entry_price * (1 + stop_pct); tp = entry_price * (1 - alvo_pct)
                horario_entrada = ts; alerta_venda = False
        elif direcao == 1:
            if low <= sl:
                pnl_pct = ((sl - entry_price) / entry_price) * 100 - (fee * 100)
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": entry_price,
                                "Saída": sl, "Resultado": "Stop", "P&L (%)": pnl_pct, "Capital": capital})
                losses += 1; wins = 0; direcao = 0
            elif high >= tp:
                pnl_pct = ((tp - entry_price) / entry_price) * 100 - (fee * 100)
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": entry_price,
                                "Saída": tp, "Resultado": "Alvo", "P&L (%)": pnl_pct, "Capital": capital})
                wins += 1; losses = 0; direcao = 0
        elif direcao == -1:
            if high >= sl:
                pnl_pct = ((entry_price - sl) / entry_price) * 100 - (fee * 100)
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": entry_price,
                                "Saída": sl, "Resultado": "Stop", "P&L (%)": pnl_pct, "Capital": capital})
                losses += 1; wins = 0; direcao = 0
            elif low <= tp:
                pnl_pct = ((entry_price - tp) / entry_price) * 100 - (fee * 100)
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": entry_price,
                                "Saída": tp, "Resultado": "Alvo", "P&L (%)": pnl_pct, "Capital": capital})
                wins += 1; losses = 0; direcao = 0

        if losses >= max_losses:
            blocked = True; bloqueios_por_derrota += 1
            trades.append({"Data": ts, "Direção": "-", "Entrada": 0, "Saída": 0,
                            "Resultado": "BLOQUEIO", "P&L (%)": 0, "Capital": capital})
            wins = 0; losses = 0
        if wins >= max_wins:
            blocked = True; bloqueios_por_vitoria += 1
            trades.append({"Data": ts, "Direção": "-", "Entrada": 0, "Saída": 0,
                            "Resultado": "BLOQUEIO", "P&L (%)": 0, "Capital": capital})
            wins = 0; losses = 0

    return trades, capital, bloqueios_por_derrota, bloqueios_por_vitoria

# ========================================================================= //
# MOSTRAR RESULTADOS
# ========================================================================= //
def mostrar_resultados(df, trades, capital_final, banca_inicial, bloq_derrota, bloq_vitoria, max_losses, max_wins, tipo_estrategia):
    if not trades:
        st.warning("Nenhum trade gerado no período.")
        return
    df_trades = pd.DataFrame(trades)

    if bloq_derrota > 0 or bloq_vitoria > 0:
        st.markdown("---")
        c1, c2 = st.columns(2)
        if bloq_derrota > 0: c1.error(f"🚨 Bloqueios por DERROTAS: **{bloq_derrota}** (limite {max_losses})")
        else: c1.success("✅ Sem bloqueio por derrotas.")
        if bloq_vitoria > 0: c2.success(f"🎉 Bloqueios por VITÓRIAS: **{bloq_vitoria}** (meta {max_wins})")
        else: c2.info("ℹ️ Sem bloqueio por vitórias.")
        st.markdown("---")

    df_normal = df_trades[df_trades['Resultado'] != 'BLOQUEIO']
    total_trades = len(df_normal)
    vitorias = len(df_normal[df_normal['Resultado'] == 'Alvo'])
    derrotas = len(df_normal[df_normal['Resultado'] == 'Stop'])
    taxa_acerto = (vitorias / total_trades) * 100 if total_trades > 0 else 0
    lucro_total = ((capital_final - banca_inicial) / banca_inicial) * 100

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total de Trades", total_trades)
    c2.metric("Vencedores", vitorias)
    c3.metric("Perdedores", derrotas)
    c4.metric("Taxa de Acerto", f"{taxa_acerto:.1f}%")
    c5.metric("Lucro Total", f"{lucro_total:.2f}%")
    c6.metric("Capital Final", f"${capital_final:.2f}")

    st.subheader("📈 Curva de Capital")
    fig_equity = go.Figure()
    fig_equity.add_trace(go.Scatter(x=df_trades['Data'], y=df_trades['Capital'],
                                     mode='lines+markers', line=dict(color='#00ff88', width=2)))
    fig_equity.update_layout(template="plotly_dark", height=400)
    st.plotly_chart(fig_equity, use_container_width=True)

    st.subheader("📉 Preço com Entradas e Saídas")
    fig_price = go.Figure(data=[go.Candlestick(x=df['timestamp'], open=df['open'],
                                                high=df['high'], low=df['low'], close=df['close'])])
    if tipo_estrategia == "Rompimento EMA":
        dfp = df.copy(); dfp['ema'] = dfp['close'].ewm(span=ema_periodo, adjust=False).mean()
        fig_price.add_trace(go.Scatter(x=dfp['timestamp'], y=dfp['ema'], mode='lines',
                                        name='EMA', line=dict(color='yellow', width=2)))
    L = df_normal[df_normal['Direção'] == 'Long']
    S = df_normal[df_normal['Direção'] == 'Short']
    fig_price.add_trace(go.Scatter(x=L['Data'], y=L['Entrada'], mode='markers', name='Compra',
                                     marker=dict(color='#00ff88', size=10, symbol='triangle-up')))
    fig_price.add_trace(go.Scatter(x=S['Data'], y=S['Entrada'], mode='markers', name='Venda',
                                     marker=dict(color='#ff4444', size=10, symbol='triangle-down')))
    fig_price.update_layout(template="plotly_dark", height=500, xaxis_rangeslider_visible=False)
    st.plotly_chart(fig_price, use_container_width=True)

    st.subheader("📋 Histórico de Operações")
    st.dataframe(df_trades, use_container_width=True)

# ========================================================================= //
# EXECUÇÃO
# ========================================================================= //
if modo == "Backtest (Passado)":
    st.subheader(f"📊 Backtest {nome_ativo} | {timeframe} | {tipo_estrategia}")
    st.caption(f"💰 ${banca_inicial} | ⚡ {alavancagem}x | 💸 {fee*100:.2f}% | 📊 EMA {ema_periodo} | 📉 SL {ema_stop_pct*100:.2f}% | 🎯 Lucro {step*100:.2f}%")

    if st.button("🚀 Rodar Backtest (Yahoo Finance)", type="primary"):
        with st.spinner(f"Baixando dados de {ticker}..."):
            df = baixar_dados_yahoo(ticker, timeframe, str(data_inicio), str(data_fim))
            if not df.empty:
                if tipo_estrategia == "Rompimento EMA":
                    trades, cf, bd, bv = simular_rompimento_ema(df, ema_periodo, ema_stop_pct, ema_alvo_mult,
                                                                  fee, max_wins, max_losses, banca_inicial, alavancagem)
                else:
                    trades, cf, bd, bv = simular_escada(df, step, ema_stop_pct, fee, max_wins, max_losses,
                                                          tipo_estrategia, banca_inicial, alavancagem)
                mostrar_resultados(df, trades, cf, banca_inicial, bd, bv, max_losses, max_wins, tipo_estrategia)

if modo == "Live/Demo (Tempo Real)":
    st.subheader(f"🔴 Live/Demo - {nome_ativo} | Estratégia: {tipo_estrategia}")
    st.info("⚠️ O modo Live/Demo requer configuração adicional.")
    if api_key and secret_key:
        st.success("✅ Chaves da API inseridas.")
    else:
        st.warning("Insira as chaves da API da Demo no menu lateral.")

st.sidebar.markdown("---")
st.sidebar.caption("Bot Multi-Ativos v3.0")
