import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import yfinance as yf
from binance.client import Client
import time

# ========================================================================= //
# CONFIGURAÇÃO DA PÁGINA
# ========================================================================= //
st.set_page_config(page_title="Bot Escada Dinâmica", page_icon="🤖", layout="wide")
st.title("🤖 Painel do Bot - Múltiplas Estratégias")

# ========================================================================= //
# MENU LATERAL (CONFIGURAÇÕES)
# ========================================================================= //
st.sidebar.header("⚙️ Configurações")

modo = st.sidebar.selectbox("Modo de Operação", ["Backtest (Passado)", "Live/Demo (Tempo Real)"])

st.sidebar.subheader("💰 Banca e Risco")
banca_inicial = st.sidebar.number_input("Banca Inicial (USDT)", min_value=10.0, max_value=1000000.0, value=1000.0, step=100.0)
usar_alavancagem = st.sidebar.checkbox("Usar Alavancagem?", value=False)
if usar_alavancagem:
    alavancagem = st.sidebar.slider("Alavancagem (x)", min_value=1, max_value=20, value=1, step=1)
else:
    alavancagem = 1

st.sidebar.subheader("Parâmetros da Estratégia")
symbol = st.sidebar.text_input("Par (ex: BTCUSDT)", "BTCUSDT")

timeframe = st.sidebar.selectbox(
    "Timeframe",
    ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "3d", "1s", "1M", "3M", "1A"],
    index=4
)

# --- SELETOR DE ESTRATÉGIA (4 OPÇÕES AGORA) ---
st.sidebar.subheader("🎯 Estratégia")
tipo_estrategia = st.sidebar.radio(
    "Escolha a estratégia:",
    [
        "Normal (Alvo Fixo)",
        "Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)",
        "Recuperação Simples (Apenas Perda Anterior + Taxas)",
        "Rompimento EMA"
    ]
)

# --- PARÂMETROS ESPECÍFICOS DE CADA ESTRATÉGIA ---
if tipo_estrategia == "Rompimento EMA":
    st.sidebar.subheader("📊 Parâmetros EMA")
    ema_periodo = st.sidebar.number_input("Período da EMA", min_value=2, max_value=500, value=30)
    ema_stop_pct = st.sidebar.number_input("Stop Loss (%)", min_value=0.01, max_value=10.0, value=0.15, step=0.01) / 100
    ema_alvo_mult = st.sidebar.number_input("Multiplicador do Alvo (x Stop)", min_value=0.5, max_value=50.0, value=8.0, step=0.5)
else:
    step = st.sidebar.number_input("Lucro Desejado (%)", min_value=0.1, max_value=10.0, value=1.0, step=0.1) / 100
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
# FUNÇÕES DO BOT
# ========================================================================= //
@st.cache_data(ttl=300)
def baixar_dados_yahoo(symbol, timeframe, start_str, end_str):
    try:
        ticker = symbol.replace("USDT", "-USD")
        yf_interval = timeframe
        if timeframe == "2h": yf_interval = "1h"
        elif timeframe == "4h": yf_interval = "1h"
        elif timeframe == "6h": yf_interval = "1h"
        elif timeframe == "12h": yf_interval = "1h"
        elif timeframe == "3d": yf_interval = "1d"
        elif timeframe == "1A": yf_interval = "1mo"
        elif timeframe == "1s": yf_interval = "1wk"
        elif timeframe == "1M": yf_interval = "1mo"
        elif timeframe == "3M": yf_interval = "3mo"
        
        df = yf.download(ticker, start=start_str, end=end_str, interval=yf_interval, progress=False)
        
        if df.empty:
            st.warning(f"Não foi possível baixar os dados para o timeframe {timeframe}.")
            return pd.DataFrame()
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df.reset_index(inplace=True)
        df.rename(columns={'Date': 'timestamp', 'Datetime': 'timestamp', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close'}, inplace=True)
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['open'] = pd.to_numeric(df['open'], errors='coerce')
        df['high'] = pd.to_numeric(df['high'], errors='coerce')
        df['low'] = pd.to_numeric(df['low'], errors='coerce')
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        
        df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)
        
        return df
    except Exception as e:
        st.error(f"Erro ao baixar dados: {e}")
        return pd.DataFrame()

# ========================================================================= //
# ESTRATÉGIA 1, 2, 3 - ESCADA DINÂMICA
# ========================================================================= //
def simular_escada(df, step, fee, max_wins, max_losses, tipo_estrategia, banca_inicial, alavancagem):
    trades = []
    capital = banca_inicial
    ref_price = df['close'].iloc[0]
    direction = 0
    entry_price = None
    tp = None
    sl = None
    wins = 0
    losses = 0
    blocked = False
    horario_entrada = None
    
    perda_total_anterior = 0.0
    bloqueios_por_derrota = 0
    bloqueios_por_vitoria = 0

    for i, row in df.iterrows():
        high, low, close, ts = row['high'], row['low'], row['close'], row['timestamp']

        if blocked:
            continue

        if direction == 0:
            if tipo_estrategia == "Normal (Alvo Fixo)":
                fator_alvo = step + fee
            elif tipo_estrategia == "Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)":
                if perda_total_anterior > 0:
                    fator_alvo = perda_total_anterior + fee + fee + step
                else:
                    fator_alvo = step + fee
            else:
                if perda_total_anterior > 0:
                    fator_alvo = perda_total_anterior + fee + fee
                else:
                    fator_alvo = step + fee

            if high >= ref_price * (1 + step):
                direction = 1
                entry_price = ref_price * (1 + step)
                tp = entry_price * (1 + fator_alvo)
                sl = entry_price * (1 - step - fee)
                horario_entrada = ts
            elif low <= ref_price * (1 - step):
                direction = -1
                entry_price = ref_price * (1 - step)
                tp = entry_price * (1 - fator_alvo)
                sl = entry_price * (1 + step + fee)
                horario_entrada = ts

        elif direction == 1:
            if low <= sl:
                pnl_pct = ((sl - entry_price) / entry_price) * 100
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                perda_total_anterior = abs(pnl_pct / 100) + fee
                trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": entry_price,
                                "Saída": sl, "Resultado": "Stop", "P&L (%)": pnl_pct, "Capital": capital})
                losses += 1
                wins = 0
                direction = -1
                ref_price = sl
                entry_price = sl
                
                if tipo_estrategia == "Normal (Alvo Fixo)":
                    fator_alvo = step + fee
                elif tipo_estrategia == "Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)":
                    fator_alvo = perda_total_anterior + fee + fee + step
                else:
                    fator_alvo = perda_total_anterior + fee + fee
                tp = entry_price * (1 - fator_alvo)
                sl = entry_price * (1 + step + fee)
                horario_entrada = ts
                
            elif high >= tp:
                pnl_pct = ((tp - entry_price) / entry_price) * 100
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                perda_total_anterior = 0.0
                trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": entry_price,
                                "Saída": tp, "Resultado": "Alvo", "P&L (%)": pnl_pct, "Capital": capital})
                wins += 1
                losses = 0
                ref_price = tp
                entry_price = tp
                fator_alvo = step + fee
                tp = entry_price * (1 + fator_alvo)
                sl = entry_price * (1 - step - fee)
                horario_entrada = ts

        elif direction == -1:
            if high >= sl:
                pnl_pct = ((entry_price - sl) / entry_price) * 100
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                perda_total_anterior = abs(pnl_pct / 100) + fee
                trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": entry_price,
                                "Saída": sl, "Resultado": "Stop", "P&L (%)": pnl_pct, "Capital": capital})
                losses += 1
                wins = 0
                direction = 1
                ref_price = sl
                entry_price = sl
                
                if tipo_estrategia == "Normal (Alvo Fixo)":
                    fator_alvo = step + fee
                elif tipo_estrategia == "Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)":
                    fator_alvo = perda_total_anterior + fee + fee + step
                else:
                    fator_alvo = perda_total_anterior + fee + fee
                tp = entry_price * (1 + fator_alvo)
                sl = entry_price * (1 - step - fee)
                horario_entrada = ts
                
            elif low <= tp:
                pnl_pct = ((entry_price - tp) / entry_price) * 100
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                perda_total_anterior = 0.0
                trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": entry_price,
                                "Saída": tp, "Resultado": "Alvo", "P&L (%)": pnl_pct, "Capital": capital})
                wins += 1
                losses = 0
                ref_price = tp
                entry_price = tp
                fator_alvo = step + fee
                tp = entry_price * (1 - fator_alvo)
                sl = entry_price * (1 + step + fee)
                horario_entrada = ts

        if losses >= max_losses:
            blocked = True
            bloqueios_por_derrota += 1
            trades.append({"Data": ts, "Direção": "-", "Entrada": 0, "Saída": 0, 
                            "Resultado": "BLOQUEIO", "P&L (%)": 0, "Capital": capital})
            wins = 0
            losses = 0
            
        if wins >= max_wins:
            blocked = True
            bloqueios_por_vitoria += 1
            trades.append({"Data": ts, "Direção": "-", "Entrada": 0, "Saída": 0, 
                            "Resultado": "BLOQUEIO", "P&L (%)": 0, "Capital": capital})
            wins = 0
            losses = 0

    return trades, capital, bloqueios_por_derrota, bloqueios_por_vitoria

# ========================================================================= //
# ESTRATÉGIA 4 - ROMPIMENTO EMA
# ========================================================================= //
def simular_rompimento_ema(df, ema_periodo, stop_pct, alvo_mult, max_wins, max_losses, banca_inicial, alavancagem):
    trades = []
    capital = banca_inicial
    
    # Calcular a EMA
    df = df.copy()
    df['ema'] = df['close'].ewm(span=ema_periodo, adjust=False).mean()
    
    # Estado do alerta
    alerta_compra = False
    alerta_venda = False
    maxima_vela_alerta = None
    minima_vela_alerta = None
    
    direcao = 0
    entry_price = None
    tp = None
    sl = None
    wins = 0
    losses = 0
    blocked = False
    horario_entrada = None
    bloqueios_por_derrota = 0
    bloqueios_por_vitoria = 0
    
    alvo_pct = stop_pct * alvo_mult

    for i, row in df.iterrows():
        if i == 0:
            continue
        
        high, low, close, ts, ema = row['high'], row['low'], row['close'], row['timestamp'], row['ema']
        prev_close = df['close'].iloc[i-1]
        prev_ema = df['ema'].iloc[i-1]

        if blocked:
            continue

        # --- DETECÇÃO DE CRUZAMENTO ---
        if prev_close <= prev_ema and close > ema:  # Cruzamento para cima
            alerta_compra = True
            alerta_venda = False
            maxima_vela_alerta = high
        elif prev_close >= prev_ema and close < ema:  # Cruzamento para baixo
            alerta_venda = True
            alerta_compra = False
            minima_vela_alerta = low

        # --- ENTRADAS (SE NÃO TIVER POSIÇÃO) ---
        if direcao == 0:
            if alerta_compra and high > maxima_vela_alerta:
                direcao = 1
                entry_price = maxima_vela_alerta
                sl = entry_price * (1 - stop_pct)
                tp = entry_price * (1 + alvo_pct)
                horario_entrada = ts
                alerta_compra = False
            elif alerta_venda and low < minima_vela_alerta:
                direcao = -1
                entry_price = minima_vela_alerta
                sl = entry_price * (1 + stop_pct)
                tp = entry_price * (1 - alvo_pct)
                horario_entrada = ts
                alerta_venda = False

        # --- GESTÃO DE POSIÇÃO LONG ---
        elif direcao == 1:
            if low <= sl:
                pnl_pct = ((sl - entry_price) / entry_price) * 100
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": entry_price,
                                "Saída": sl, "Resultado": "Stop", "P&L (%)": pnl_pct, "Capital": capital})
                losses += 1
                wins = 0
                direcao = 0
            elif high >= tp:
                pnl_pct = ((tp - entry_price) / entry_price) * 100
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": entry_price,
                                "Saída": tp, "Resultado": "Alvo", "P&L (%)": pnl_pct, "Capital": capital})
                wins += 1
                losses = 0
                direcao = 0

        # --- GESTÃO DE POSIÇÃO SHORT ---
        elif direcao == -1:
            if high >= sl:
                pnl_pct = ((entry_price - sl) / entry_price) * 100
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": entry_price,
                                "Saída": sl, "Resultado": "Stop", "P&L (%)": pnl_pct, "Capital": capital})
                losses += 1
                wins = 0
                direcao = 0
            elif low <= tp:
                pnl_pct = ((entry_price - tp) / entry_price) * 100
                capital *= (1 + (pnl_pct * alavancagem) / 100)
                trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": entry_price,
                                "Saída": tp, "Resultado": "Alvo", "P&L (%)": pnl_pct, "Capital": capital})
                wins += 1
                losses = 0
                direcao = 0

        # --- BLOQUEIOS ---
        if losses >= max_losses:
            blocked = True
            bloqueios_por_derrota += 1
            trades.append({"Data": ts, "Direção": "-", "Entrada": 0, "Saída": 0, 
                            "Resultado": "BLOQUEIO", "P&L (%)": 0, "Capital": capital})
            wins = 0
            losses = 0
        if wins >= max_wins:
            blocked = True
            bloqueios_por_vitoria += 1
            trades.append({"Data": ts, "Direção": "-", "Entrada": 0, "Saída": 0, 
                            "Resultado": "BLOQUEIO", "P&L (%)": 0, "Capital": capital})
            wins = 0
            losses = 0

    return trades, capital, bloqueios_por_derrota, bloqueios_por_vitoria

# ========================================================================= //
# MOSTRAR RESULTADOS
# ========================================================================= //
def mostrar_resultados(df, trades, capital_final, banca_inicial, bloq_derrota, bloq_vitoria, max_losses, max_wins, tipo_estrategia):
    if trades:
        df_trades = pd.DataFrame(trades)
        
        if bloq_derrota > 0 or bloq_vitoria > 0:
            st.markdown("---")
            col_aviso1, col_aviso2 = st.columns(2)
            if bloq_derrota > 0:
                col_aviso1.error(f"🚨 **BLOQUEIO POR DERROTAS:** O bot foi bloqueado **{bloq_derrota}** vez(es) por atingir o limite de {max_losses} derrotas seguidas.")
            else:
                col_aviso1.success("✅ Nenhum bloqueio por derrotas.")
                
            if bloq_vitoria > 0:
                col_aviso2.success(f"🎉 **BLOQUEIO POR VITÓRIAS:** O bot foi bloqueado **{bloq_vitoria}** vez(es) por atingir a meta de {max_wins} vitórias seguidas.")
            else:
                col_aviso2.info("ℹ️ Nenhum bloqueio por vitórias.")
            st.markdown("---")
        
        df_normal = df_trades[df_trades['Resultado'] != 'BLOQUEIO']
        total_trades = len(df_normal)
        vitorias = len(df_normal[df_normal['Resultado'] == 'Alvo'])
        derrotas = len(df_normal[df_normal['Resultado'] == 'Stop'])
        taxa_acerto = (vitorias / total_trades) * 100 if total_trades > 0 else 0
        lucro_total = ((capital_final - banca_inicial) / banca_inicial) * 100

        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("Total de Trades", total_trades)
        col2.metric("Vencedores", vitorias)
        col3.metric("Perdedores", derrotas)
        col4.metric("Taxa de Acerto", f"{taxa_acerto:.1f}%")
        col5.metric("Lucro Total", f"{lucro_total:.2f}%")
        col6.metric("Capital Final", f"${capital_final:.2f}")

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
        
        # Adiciona a EMA ao gráfico se for a estratégia de Rompimento
        if tipo_estrategia == "Rompimento EMA":
            df_plot = df.copy()
            df_plot['ema'] = df_plot['close'].ewm(span=ema_periodo, adjust=False).mean()
            fig_price.add_trace(go.Scatter(x=df_plot['timestamp'], y=df_plot['ema'],
                                            mode='lines', name='EMA', line=dict(color='yellow', width=2)))
        
        longs = df_normal[df_normal['Direção'] == 'Long']
        shorts = df_normal[df_normal['Direção'] == 'Short']
        fig_price.add_trace(go.Scatter(x=longs['Data'], y=longs['Entrada'], mode='markers',
                                        name='Compra', marker=dict(color='#00ff88', size=10, symbol='triangle-up')))
        fig_price.add_trace(go.Scatter(x=shorts['Data'], y=shorts['Entrada'], mode='markers',
                                        name='Venda', marker=dict(color='#ff4444', size=10, symbol='triangle-down')))
        fig_price.update_layout(template="plotly_dark", height=500, xaxis_rangeslider_visible=False)
        st.plotly_chart(fig_price, use_container_width=True)

        st.subheader("📋 Histórico de Operações")
        st.dataframe(df_trades, use_container_width=True)
    else:
        st.warning("Nenhum trade foi gerado no período.")

# ========================================================================= //
# MODO BACKTEST
# ========================================================================= //
if modo == "Backtest (Passado)":
    st.subheader(f"📊 Backtest {symbol} | Timeframe: {timeframe} | Estratégia: {tipo_estrategia} | Banca: ${banca_inicial} | Alavancagem: {alavancagem}x")

    if st.button("🚀 Rodar Backtest (Yahoo Finance)", type="primary"):
        with st.spinner("Baixando dados do Yahoo Finance e simulando..."):
            df = baixar_dados_yahoo(symbol, timeframe, str(data_inicio), str(data_fim))
            if not df.empty:
                if tipo_estrategia == "Rompimento EMA":
                    trades, capital_final, bloq_derrota, bloq_vitoria = simular_rompimento_ema(
                        df, ema_periodo, ema_stop_pct, ema_alvo_mult, max_wins, max_losses, banca_inicial, alavancagem
                    )
                else:
                    trades, capital_final, bloq_derrota, bloq_vitoria = simular_escada(
                        df, step, fee, max_wins, max_losses, tipo_estrategia, banca_inicial, alavancagem
                    )
                mostrar_resultados(df, trades, capital_final, banca_inicial, bloq_derrota, bloq_vitoria, max_losses, max_wins, tipo_estrategia)

# ========================================================================= //
# MODO LIVE/DEMO (BINANCE) - Apenas informativo
# ========================================================================= //
if modo == "Live/Demo (Tempo Real)":
    st.subheader(f"🔴 Live/Demo - {symbol} | Estratégia: {tipo_estrategia}")
    st.info("⚠️ O modo Live/Demo requer configuração adicional. Por enquanto, use o Backtest para validar as estratégias.")
    
    if api_key and secret_key:
        st.success("✅ Chaves da API inseridas. O modo Live/Demo estará disponível em breve.")
    else:
        st.warning("Insira as chaves da API da Demo no menu lateral.")

st.sidebar.markdown("---")
st.sidebar.caption("Bot Multi-Estratégias v1.0")
