import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import yfinance as yf
from binance.client import Client
from binance.enums import *

# ========================================================================= //
# CONFIGURAÇÃO DA PÁGINA
# ========================================================================= //
st.set_page_config(page_title="Bot Escada Dinâmica", page_icon="🤖", layout="wide")
st.title("🤖 Painel do Bot - Escada Dinâmica")

# ========================================================================= //
# MENU LATERAL (CONFIGURAÇÕES GERAIS)
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

step = st.sidebar.number_input("Lucro Desejado (%)", min_value=0.1, max_value=10.0, value=1.0, step=0.1) / 100
fee = st.sidebar.number_input("Taxa da Corretora (%)", min_value=0.01, max_value=1.0, value=0.10, step=0.01) / 100

st.sidebar.subheader("Estratégia de Alvo")
tipo_estrategia = st.sidebar.radio(
    "Escolha a estratégia:",
    [
        "Normal (Alvo Fixo)",
        "Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)",
        "Recuperação Simples (Apenas Perda Anterior + Taxas)"
    ]
)

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
    
    st.sidebar.subheader("Funcionalidade do Demo")
    func_demo = st.sidebar.radio(
        "Escolha a funcionalidade:",
        [
            "1 - Teste em Tempo Real (Ação Automática)",
            "2 - Backtest com Dados da Binance (Passado)"
        ]
    )
    
    if func_demo == "1 - Teste em Tempo Real (Ação Automática)":
        intervalo_verificacao = st.sidebar.number_input("Intervalo de Verificação (segundos)", min_value=5, max_value=300, value=30)
        num_verificacoes = st.sidebar.number_input("Número de Verificações", min_value=1, max_value=1000, value=10)

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

@st.cache_data(ttl=300)
def baixar_dados_binance_demo(api_key, secret_key, symbol, timeframe, start_str, end_str):
    try:
        client = Client(api_key, secret_key, testnet=True)
        client.API_URL = 'https://testnet.binance.vision/api'
        
        interval_map = {
            "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "12h": "12h",
            "1d": "1d", "3d": "3d", "1s": "1w", "1M": "1M"
        }
        interval = interval_map.get(timeframe, "1h")
        
        start_ts = int(pd.Timestamp(start_str).timestamp() * 1000)
        end_ts = int(pd.Timestamp(end_str).timestamp() * 1000)
        
        klines = client.get_historical_klines(symbol, interval, start_ts, end_ts)
        
        if not klines:
            st.warning("Não foi possível baixar dados da Binance Demo.")
            return pd.DataFrame()
        
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume',
                                            'close_time', 'qav', 'trades', 'tbbav', 'tbqav', 'ignore'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        
        return df
    except Exception as e:
        st.error(f"Erro ao baixar dados da Binance Demo: {e}")
        return pd.DataFrame()

def simular_estrategia(df, step, fee, max_wins, max_losses, tipo_estrategia, banca_inicial, alavancagem):
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
    
    # --- CONTADORES DE BLOQUEIO ---
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
                                "Saída": sl, "Resultado": "Stop", "P&L (%)": pnl_pct, "Capital": capital, "Bloqueado?": "Não"})
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
                                "Saída": tp, "Resultado": "Alvo", "P&L (%)": pnl_pct, "Capital": capital, "Bloqueado?": "Não"})
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
                                "Saída": sl, "Resultado": "Stop", "P&L (%)": pnl_pct, "Capital": capital, "Bloqueado?": "Não"})
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
                                "Saída": tp, "Resultado": "Alvo", "P&L (%)": pnl_pct, "Capital": capital, "Bloqueado?": "Não"})
                wins += 1
                losses = 0
                ref_price = tp
                entry_price = tp
                fator_alvo = step + fee
                tp = entry_price * (1 - fator_alvo)
                sl = entry_price * (1 + step + fee)
                horario_entrada = ts

        # --- VERIFICAÇÃO DE BLOQUEIO ---
        if losses >= max_losses:
            blocked = True
            bloqueios_por_derrota += 1
            trades.append({"Data": ts, "Direção": "-", "Entrada": 0, "Saída": 0, 
                            "Resultado": "BLOQUEIO", "P&L (%)": 0, "Capital": capital, "Bloqueado?": f"Sim (Derrota #{bloqueios_por_derrota})"})
            wins = 0
            losses = 0
            
        if wins >= max_wins:
            blocked = True
            bloqueios_por_vitoria += 1
            trades.append({"Data": ts, "Direção": "-", "Entrada": 0, "Saída": 0, 
                            "Resultado": "BLOQUEIO", "P&L (%)": 0, "Capital": capital, "Bloqueado?": f"Sim (Vitória #{bloqueios_por_vitoria})"})
            wins = 0
            losses = 0

    return trades, capital, bloqueios_por_derrota, bloqueios_por_vitoria

def mostrar_resultados(df, trades, capital_final, banca_inicial, bloqueios_derrota, bloqueios_vitoria):
    if trades:
        df_trades = pd.DataFrame(trades)
        
        # --- PAINEL DE AVISO ---
        if bloqueios_derrota > 0 or bloqueios_vitoria > 0:
            st.markdown("---")
            col_aviso1, col_aviso2 = st.columns(2)
            if bloqueios_derrota > 0:
                col_aviso1.error(f"🚨 **BLOQUEIO POR DERROTAS:** O bot foi bloqueado **{bloqueios_derrota}** vez(es) por atingir o limite de {max_losses} derrotas seguidas.")
            else:
                col_aviso1.success("✅ Nenhum bloqueio por derrotas.")
                
            if bloqueios_vitoria > 0:
                col_aviso2.success(f"🎉 **BLOQUEIO POR VITÓRIAS:** O bot foi bloqueado **{bloqueios_vitoria}** vez(es) por atingir a meta de {max_wins} vitórias seguidas.")
            else:
                col_aviso2.info("ℹ️ Nenhum bloqueio por vitórias.")
            st.markdown("---")
        
        total_trades = len(df_trades[df_trades['Resultado'] != 'BLOQUEIO'])
        vitorias = len(df_trades[df_trades['Resultado'] == 'Alvo'])
        derrotas = len(df_trades[df_trades['Resultado'] == 'Stop'])
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
        st.warning("Nenhum trade foi gerado no período.")

# ========================================================================= //
# MODO BACKTEST (YAHOO FINANCE)
# ========================================================================= //
if modo == "Backtest (Passado)":
    st.subheader(f"📊 Backtest {symbol} | Timeframe: {timeframe} | Estratégia: {tipo_estrategia} | Banca: ${banca_inicial} | Alavancagem: {alavancagem}x")

    if st.button("🚀 Rodar Backtest (Yahoo Finance)", type="primary"):
        with st.spinner("Baixando dados do Yahoo Finance e simulando..."):
            df = baixar_dados_yahoo(symbol, timeframe, str(data_inicio), str(data_fim))
            if not df.empty:
                trades, capital_final, bloq_derrota, bloq_vitoria = simular_estrategia(
                    df, step, fee, max_wins, max_losses, tipo_estrategia, banca_inicial, alavancagem
                )
                mostrar_resultados(df, trades, capital_final, banca_inicial, bloq_derrota, bloq_vitoria)

# ========================================================================= //
# MODO LIVE/DEMO (BINANCE)
# ========================================================================= //
if modo == "Live/Demo (Tempo Real)":
    st.subheader(f"🔴 Live/Demo - {symbol} | Estratégia: {tipo_estrategia} | Banca: ${banca_inicial} | Alavancagem: {alavancagem}x")

    if not api_key or not secret_key:
        st.info("Insira as credenciais da conta Demo no menu lateral para começar.")
    else:
        # --- FUNCIONALIDADE 1: TESTE EM TEMPO REAL ---
        if func_demo == "1 - Teste em Tempo Real (Ação Automática)":
            st.subheader("🔴 Teste em Tempo Real - Ação Automática")
            
            if "bot_ativo" not in st.session_state:
                st.session_state.bot_ativo = True
            if "capital_atual" not in st.session_state:
                st.session_state.capital_atual = banca_inicial
            if "pnl_total" not in st.session_state:
                st.session_state.pnl_total = 0.0
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
            if "bloqueado" not in st.session_state:
                st.session_state.bloqueado = False

            # --- PAINEL DE AVISO NO TOPO ---
            if st.session_state.bloqueado:
                st.error("🚨 **BOT BLOQUEADO!** O limite de derrotas ou vitórias seguidas foi atingido. O bot está pausado. Clique em 'RESETAR BOT' para continuar.")
            else:
                st.success("🟢 **BOT ATIVO!** A operar normalmente.")
            
            # --- PAINEL DE CONTROLE VISUAL ---
            col_painel1, col_painel2, col_painel3, col_painel4 = st.columns(4)
            col_painel1.metric("Capital Atual", f"${st.session_state.capital_atual:.2f}")
            col_painel2.metric("P&L Total", f"${st.session_state.pnl_total:.2f}")
            col_painel3.metric("Vitórias", st.session_state.wins)
            col_painel4.metric("Derrotas", st.session_state.losses)

            col_btn1, col_btn2, col_btn3 = st.columns(3)
            with col_btn1:
                if st.button("⏸️ PAUSAR BOT" if st.session_state.bot_ativo else "▶️ RETOMAR BOT"):
                    st.session_state.bot_ativo = not st.session_state.bot_ativo
                    st.rerun()
            with col_btn2:
                if st.button("🔄 RESETAR BOT"):
                    st.session_state.capital_atual = banca_inicial
                    st.session_state.pnl_total = 0.0
                    st.session_state.log = []
                    st.session_state.ref_price = None
                    st.session_state.direction = 0
                    st.session_state.wins = 0
                    st.session_state.losses = 0
                    st.session_state.bloqueado = False
                    st.rerun()
            with col_btn3:
                st.metric("Estado", "🟢 ATIVO" if st.session_state.bot_ativo else "🔴 PAUSADO")

            st.markdown("---")

            if st.session_state.bot_ativo and not st.session_state.bloqueado:
                if st.button("🚀 Iniciar Verificação Automática"):
                    try:
                        client = Client(api_key, secret_key, testnet=True)
                        client.API_URL = 'https://testnet.binance.vision/api'
                        
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        for i in range(num_verificacoes):
                            if not st.session_state.bot_ativo or st.session_state.bloqueado:
                                st.warning("Bot pausado ou bloqueado.")
                                break
                                
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
                                    lucro = banca_inicial * step * alavancagem
                                    st.session_state.capital_atual += lucro
                                    st.session_state.pnl_total += lucro
                                elif preco <= ref * (1 - step):
                                    st.session_state.log.append(f"🔴 Gatilho de BAIXA! Preço: {preco} | Ref: {ref}")
                                    st.session_state.direction = -1
                                    st.session_state.ref_price = preco * (1 - step)
                                    st.session_state.losses += 1
                                    perda = banca_inicial * step * alavancagem
                                    st.session_state.capital_atual -= perda
                                    st.session_state.pnl_total -= perda
                                
                                # Verifica bloqueio
                                if st.session_state.losses >= max_losses or st.session_state.wins >= max_wins:
                                    st.session_state.bloqueado = True
                                    st.session_state.log.append(f"🚨 BLOQUEIO ATIVADO! (Derrotas: {st.session_state.losses} | Vitórias: {st.session_state.wins})")

                            status_text.text(f"Verificação {i+1}/{num_verificacoes} | Preço: ${preco:,.2f}")
                            progress_bar.progress((i + 1) / num_verificacoes)
                            time.sleep(intervalo_verificacao)

                        st.success("Verificação Concluída!")
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Erro na conexão: {e}")
            else:
                st.warning("🔴 O bot está PAUSADO ou BLOQUEADO. Clique em 'RESETAR BOT' ou 'RETOMAR BOT'.")

            st.subheader("📜 Log de Atividades")
            for linha in reversed(st.session_state.log[-20:]):
                st.text(linha)
        
        # --- FUNCIONALIDADE 2: BACKTEST COM DADOS DA BINANCE ---
        else:
            st.subheader("📊 Backtest com Dados da Binance (Passado)")
            st.info(f"Usando a estratégia: **{tipo_estrategia}** | Banca: ${banca_inicial} | Alavancagem: {alavancagem}x")
            
            col_a, col_b = st.columns(2)
            with col_a:
                data_inicio_demo = st.date_input("Data de Início (Binance)", datetime.now() - timedelta(days=30), key="demo_inicio")
            with col_b:
                data_fim_demo = st.date_input("Data de Fim (Binance)", datetime.now(), key="demo_fim")
            
            if st.button("🚀 Rodar Backtest com Dados da Binance", type="primary"):
                with st.spinner("Baixando dados da Binance Demo e simulando..."):
                    df = baixar_dados_binance_demo(api_key, secret_key, symbol, timeframe, str(data_inicio_demo), str(data_fim_demo))
                    if not df.empty:
                        trades, capital_final, bloq_derrota, bloq_vitoria = simular_estrategia(
                            df, step, fee, max_wins, max_losses, tipo_estrategia, banca_inicial, alavancagem
                        )
                        mostrar_resultados(df, trades, capital_final, banca_inicial, bloq_derrota, bloq_vitoria)

st.sidebar.markdown("---")
st.sidebar.caption("Bot Escada Dinâmica v1.0")
