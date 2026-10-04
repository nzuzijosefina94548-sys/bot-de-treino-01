import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import yfinance as yf

# ========================================================================= //
# CONFIGURAÇÃO DA PÁGINA
# ========================================================================= //
st.set_page_config(page_title="Bot Escada Dinâmica", page_icon="🤖", layout="wide")
st.title("🤖 Painel do Bot - Escada Dinâmica")

# ========================================================================= //
# MENU LATERAL (CONFIGURAÇÕES)
# ========================================================================= //
st.sidebar.header("⚙️ Configurações")

modo = st.sidebar.selectbox("Modo de Operação", ["Backtest (Passado)", "Live/Demo (Tempo Real)"])

st.sidebar.subheader("Parâmetros da Estratégia")
symbol = st.sidebar.text_input("Par (ex: BTCUSDT)", "BTCUSDT")
timeframe = st.sidebar.selectbox("Timeframe", ["1m", "5m", "15m", "1h", "4h", "1d"], index=3)
step = st.sidebar.number_input("Passo da Escada (%)", min_value=0.1, max_value=10.0, value=1.0, step=0.1) / 100
fee = st.sidebar.number_input("Taxa da Corretora (%)", min_value=0.01, max_value=1.0, value=0.10, step=0.01) / 100
max_wins = st.sidebar.number_input("Máx. Vitórias Seguidas", min_value=1, max_value=50, value=3)
max_losses = st.sidebar.number_input("Máx. Derrotas Seguidas", min_value=1, max_value=50, value=3)

if modo == "Backtest (Passado)":
    st.sidebar.subheader("Período do Backtest")
    data_inicio = st.sidebar.date_input("Data de Início", datetime.now() - timedelta(days=30))
    data_fim = st.sidebar.date_input("Data de Fim", datetime.now())

if modo == "Live/Demo (Tempo Real)":
    st.sidebar.subheader("Credenciais da Demo (Binance)")
    api_key = st.sidebar.text_input("API Key", type="password")
    secret_key = st.sidebar.text_input("Secret Key", type="password")

# ========================================================================= //
# FUNÇÕES DO BOT (AGORA COM YAHOO FINANCE)
# ========================================================================= //
@st.cache_data(ttl=300)
def baixar_dados(symbol, interval, start_str, end_str):
    try:
        # Converte o símbolo da Binance (BTCUSDT) para o símbolo do Yahoo Finance (BTC-USD)
        ticker = symbol.replace("USDT", "-USD")
        
        # Mapeia os intervalos da Binance para os do Yahoo Finance
        yf_interval = interval
        if interval == "1m": yf_interval = "1m"
        elif interval == "5m": yf_interval = "5m"
        elif interval == "15m": yf_interval = "15m"
        elif interval == "1h": yf_interval = "60m" # Yahoo usa 60m para 1 hora
        elif interval == "4h": yf_interval = "1h"  # Yahoo não tem 4h, usamos 1h
        elif interval == "1d": yf_interval = "1d"
        
        # Baixa os dados
        df = yf.download(ticker, start=start_str, end=end_str, interval=yf_interval, progress=False)
        
        # Verifica se o download foi bem-sucedido
        if df.empty:
            st.warning("Não foi possível baixar os dados. Tente mudar o período ou o intervalo.")
            return pd.DataFrame()
            
        # Ajusta o formato para ficar igual ao que o resto do código espera
        df.reset_index(inplace=True)
        df.rename(columns={'Date': 'timestamp', 'Datetime': 'timestamp', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close'}, inplace=True)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        
        return df
    except Exception as e:
        st.error(f"Erro ao baixar dados: {e}")
        return pd.DataFrame()

def simular_estrategia(df, step, fee, max_wins, max_losses):
    trades = []
    capital = 1000.0
    ref_price = df['close'].iloc[0]
    direction = 0
    entry_price = None
    tp = None
    sl = None
    wins = 0
    losses = 0
    blocked = False
    horario_entrada = None

    for i, row in df.iterrows():
        high, low, close, ts = row['high'], row['low'], row['close'], row['timestamp']

        if blocked:
            continue

        if direction == 0:
            if high >= ref_price * (1 + step):
                direction = 1
                entry_price = ref_price * (1 + step)
                tp = entry_price * (1 + step + fee)
                sl = ref_price
                horario_entrada = ts
            elif low <= ref_price * (1 - step):
                direction = -1
                entry_price = ref_price * (1 - step)
                tp = entry_price * (1 - step - fee)
                sl = ref_price
                horario_entrada = ts

        elif direction == 1:
            if low <= sl:
                pnl_pct = ((sl - entry_price) / entry_price - (fee * 2)) * 100
                capital *= (1 + pnl_pct / 100)
                trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": entry_price,
                                "Saída": sl, "Resultado": "Stop", "P&L (%)": pnl_pct, "Capital": capital})
                losses += 1
                wins = 0
                direction = -1
                ref_price = sl
                entry_price = sl
                tp = entry_price * (1 - step - fee)
                sl = entry_price * (1 + step)
                horario_entrada = ts
            elif high >= tp:
                pnl_pct = ((tp - entry_price) / entry_price - (fee * 2)) * 100
                capital *= (1 + pnl_pct / 100)
                trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": entry_price,
                                "Saída": tp, "Resultado": "Alvo", "P&L (%)": pnl_pct, "Capital": capital})
                wins += 1
                losses = 0
                ref_price = tp
                entry_price = tp
                tp = entry_price * (1 + step + fee)
                sl = entry_price * (1 - step)
                horario_entrada = ts

        elif direction == -1:
            if high >= sl:
                pnl_pct = ((entry_price - sl) / entry_price - (fee * 2)) * 100
                capital *= (1 + pnl_pct / 100)
                trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": entry_price,
                                "Saída": sl, "Resultado": "Stop", "P&L (%)": pnl_pct, "Capital": capital})
                losses += 1
                wins = 0
                direction = 1
                ref_price = sl
                entry_price = sl
                tp = entry_price * (1 + step + fee)
                sl = entry_price * (1 - step)
                horario_entrada = ts
            elif low <= tp:
                pnl_pct = ((entry_price - tp) / entry_price - (fee * 2)) * 100
                capital *= (1 + pnl_pct / 100)
                trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": entry_price,
                                "Saída": tp, "Resultado": "Alvo", "P&L (%)": pnl_pct, "Capital": capital})
                wins += 1
                losses = 0
                ref_price = tp
                entry_price = tp
                tp = entry_price * (1 - step - fee)
                sl = entry_price * (1 + step)
                horario_entrada = ts

        if wins >= max_wins or losses >= max_losses:
            blocked = True
            wins = 0
            losses = 0

    return trades, capital

# ========================================================================= //
# MODO BACKTEST
# ========================================================================= //
if modo == "Backtest (Passado)":
    st.subheader(f"📊 Backtest {symbol} | Timeframe: {timeframe}")

    if st.button("🚀 Rodar Backtest", type="primary"):
        with st.spinner("Baixando dados do Yahoo Finance e simulando..."):
            df = baixar_dados(symbol, timeframe, str(data_inicio), str(data_fim))
            if not df.empty:
                trades, capital_final = simular_estrategia(df, step, fee, max_wins, max_losses)
                
                if trades:
                    df_trades = pd.DataFrame(trades)
                    total_trades = len(df_trades)
                    vitorias = len(df_trades[df_trades['Resultado'] == 'Alvo'])
                    derrotas = len(df_trades[df_trades['Resultado'] == 'Stop'])
                    taxa_acerto = (vitorias / total_trades) * 100 if total_trades > 0 else 0
                    lucro_total = ((capital_final - 1000) / 1000) * 100

                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Total de Trades", total_trades)
                    col2.metric("Taxa de Acerto", f"{taxa_acerto:.1f}%")
                    col3.metric("Lucro Total", f"{lucro_total:.2f}%")
                    col4.metric("Capital Final", f"${capital_final:.2f}")

                    st.subheader("📈 Curva de Capital")
                    fig_equity = go.Figure()
                    fig_equity.add_trace(go.Scatter(x=df_trades['Data'], y=df_trades['Capital'],
                                                     mode='lines+markers', name='Capital',
                                                     line=dict(color='#00ff88', width=2)))
                    fig_equity.update_layout(template="plotly_dark", height=400)
                    st.plotly_chart(fig_equity, use_container_width=True)

                    st.subheader("📉 Preço com Entradas e Saídas")
                    fig_price = go.Figure(data=[go.Candlestick(x=df['timestamp'], open=df['open'],
                                                                high=df['high'], low=df['low'],
                                                                close=df['close'], name='Preço')])
                    longs = df_trades[df_trades['Direção'] == 'Long']
                    shorts = df_trades[df_trades['Direção'] == 'Short']
                    fig_price.add_trace(go.Scatter(x=longs['Data'], y=longs['Entrada'], mode='markers',
                                                    name='Compra', marker=dict(color='#00ff88', size=10, symbol='triangle-up')))
                    fig_price.add_trace(go.Scatter(x=shorts['Data'], y=shorts['Entrada'], mode='markers',
                                                    name='Venda', marker=dict(color='#ff4444', size=10, symbol='triangle-down')))
                    fig_price.update_layout(template="plotly_dark", height=500, xaxis_rangeslider_visible=False)
                    st.plotly_chart(fig_price, use_container_width=True)

                    st.subheader("📋 Histórico de Operações")
                    st.dataframe(df_trades, use_container_width=True)
                else:
                    st.warning("Nenhum trade foi gerado no período. Tente aumentar o período ou diminuir o passo.")

# ========================================================================= //
# MODO LIVE/DEMO
# ========================================================================= //
if modo == "Live/Demo (Tempo Real)":
    st.subheader(f"🔴 Live/Demo - {symbol}")

    if not api_key or not secret_key:
        st.info("Insira as credenciais da conta Demo no menu lateral para começar.")
    else:
        if "log" not in st.session_state:
            st.session_state.log = []
        if "ref_price" not in st.session_state:
            st.session_state.ref_price = None
        if "direction" not in st.session_state:
            st.session_state.direction = 0
        if "wins" not in st.session_state:
            st.session_state.wins = 0
        if "losses" not in st.session_state:
            st.session_state.losses = 0

        try:
            from binance.client import Client
            client = Client(api_key, secret_key, testnet=True)
            
            if st.button("🔄 Verificar Preço Agora"):
                ticker = client.get_symbol_ticker(symbol=symbol)
                preco = float(ticker['price'])

                if st.session_state.ref_price is None:
                    st.session_state.ref_price = preco
                    st.session_state.log.append(f"Preço de referência definido: {preco}")
                else:
                    ref = st.session_state.ref_price
                    if preco >= ref * (1 + step):
                        st.session_state.log.append(f"🟢 Gatilho de ALTA! Preço: {preco} | Ref: {ref}")
                        st.session_state.direction = 1
                        st.session_state.ref_price = preco * (1 + step)
                        st.session_state.wins += 1
                    elif preco <= ref * (1 - step):
                        st.session_state.log.append(f"🔴 Gatilho de BAIXA! Preço: {preco} | Ref: {ref}")
                        st.session_state.direction = -1
                        st.session_state.ref_price = preco * (1 - step)
                        st.session_state.losses += 1

                st.metric("Preço Atual", f"${preco:,.2f}")
                st.metric("Preço de Referência", f"${st.session_state.ref_price:,.2f}")
                st.metric("Direção", "Long" if st.session_state.direction == 1 else ("Short" if st.session_state.direction == -1 else "Neutro"))
                st.metric("Vitórias / Derrotas", f"{st.session_state.wins} / {st.session_state.losses}")

                st.subheader("📜 Log de Atividades")
                for linha in reversed(st.session_state.log[-20:]):
                    st.text(linha)
                    
        except Exception as e:
            st.error(f"Erro na conexão: {e}")

st.sidebar.markdown("---")
st.sidebar.caption("Bot Escada Dinâmica v1.0")
