import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import yfinance as yf
import asyncio
import json
import websockets

# ========================================================================= //
# CONFIGURAÇÃO DA PÁGINA
# ========================================================================= //
st.set_page_config(page_title="Bot Multi-Mercados", page_icon="🤖", layout="wide")
st.title("🤖 Painel do Bot - Multi-Mercados")

# ========================================================================= //
# SELETOR DE BOT (TOPO DA SIDEBAR)
# ========================================================================= //
st.sidebar.markdown("## 🤖 Escolha o Bot")
bot_escolhido = st.sidebar.radio(
    "Mercado:",
    ["📈 Cripto (Yahoo Finance / Binance)", "📊 Deriv (Índices Sintéticos)"]
)
st.sidebar.markdown("---")

# ######################################################################### #
# ########################## BOT CRIPTO ################################## #
# ######################################################################### #
if bot_escolhido == "📈 Cripto (Yahoo Finance / Binance)":

    # ===================================================================== //
    # SIDEBAR - CRIPTO
    # ===================================================================== //
    st.sidebar.header("⚙️ Configurações Cripto")

    modo_c = st.sidebar.selectbox("Modo de Operação", ["Backtest (Passado)", "Live/Demo (Tempo Real)"], key="c_modo")

    st.sidebar.subheader("💰 Banca e Risco")
    banca_inicial_c = st.sidebar.number_input("Banca Inicial (USDT)", min_value=10.0, max_value=1000000.0, value=1000.0, step=100.0, key="c_banca")
    usar_alavancagem_c = st.sidebar.checkbox("Usar Alavancagem?", value=False, key="c_alav")
    if usar_alavancagem_c:
        alavancagem_c = st.sidebar.slider("Alavancagem (x)", min_value=1, max_value=20, value=1, step=1, key="c_alav_slider")
    else:
        alavancagem_c = 1

    st.sidebar.subheader("Parâmetros da Estratégia")
    symbol_c = st.sidebar.text_input("Par (ex: BTCUSDT)", "BTCUSDT", key="c_symbol")
    timeframe_c = st.sidebar.selectbox(
        "Timeframe",
        ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "3d", "1s", "1M", "3M", "1A"],
        index=4, key="c_tf"
    )
    step_c = st.sidebar.number_input("Lucro Desejado (%)", min_value=0.1, max_value=10.0, value=1.0, step=0.1, key="c_step") / 100
    fee_c = st.sidebar.number_input("Taxa da Corretora (%)", min_value=0.01, max_value=1.0, value=0.10, step=0.01, key="c_fee") / 100

    st.sidebar.subheader("🎯 Estratégia")
    tipo_estrategia_c = st.sidebar.radio(
        "Escolha a estratégia:",
        [
            "Normal (Alvo Fixo)",
            "Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)",
            "Recuperação Simples (Apenas Perda Anterior + Taxas)",
            "Rompimento EMA"
        ],
        key="c_estrategia"
    )

    if tipo_estrategia_c == "Rompimento EMA":
        ema_periodo_c = st.sidebar.number_input("Período da EMA", min_value=2, max_value=500, value=21, key="c_ema")
        ema_stop_pct_c = st.sidebar.number_input("Stop Loss (%)", min_value=0.01, max_value=10.0, value=1.0, step=0.1, key="c_ema_stop") / 100
        ema_alvo_mult_c = st.sidebar.number_input("Multiplicador do Alvo (x Stop)", min_value=0.5, max_value=50.0, value=2.5, step=0.1, key="c_ema_mult")
    else:
        ema_periodo_c = 21
        ema_stop_pct_c = 0.01
        ema_alvo_mult_c = 2.5

    max_wins_c = st.sidebar.number_input("Máx. Vitórias Seguidas", min_value=1, max_value=50, value=20, key="c_max_w")
    max_losses_c = st.sidebar.number_input("Máx. Derrotas Seguidas", min_value=1, max_value=50, value=10, key="c_max_l")

    if modo_c == "Backtest (Passado)":
        st.sidebar.subheader("📅 Período do Backtest")
        data_inicio_c = st.sidebar.date_input("Data de Início", datetime.now() - timedelta(days=30), key="c_data_i")
        data_fim_c = st.sidebar.date_input("Data de Fim", datetime.now(), key="c_data_f")

    # ===================================================================== //
    # FUNÇÕES - CRIPTO
    # ===================================================================== //
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
                return pd.DataFrame()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.reset_index(inplace=True)
            df.rename(columns={'Date': 'timestamp', 'Datetime': 'timestamp', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close'}, inplace=True)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            for c in ['open', 'high', 'low', 'close']:
                df[c] = pd.to_numeric(df[c], errors='coerce')
            df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)
            return df
        except Exception as e:
            st.error(f"Erro ao baixar dados: {e}")
            return pd.DataFrame()

    def simular_escada_c(df, step, fee, max_wins, max_losses, tipo_estrategia, banca_inicial, alavancagem):
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
                    fator_alvo = (perda_total_anterior + fee + fee + step) if perda_total_anterior > 0 else (step + fee)
                else:
                    fator_alvo = (perda_total_anterior + fee + fee) if perda_total_anterior > 0 else (step + fee)

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
                    losses += 1; wins = 0
                    direction = -1; ref_price = sl; entry_price = sl
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
                    wins += 1; losses = 0
                    ref_price = tp; entry_price = tp
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
                    losses += 1; wins = 0
                    direction = 1; ref_price = sl; entry_price = sl
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
                    wins += 1; losses = 0
                    ref_price = tp; entry_price = tp
                    fator_alvo = step + fee
                    tp = entry_price * (1 - fator_alvo)
                    sl = entry_price * (1 + step + fee)
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

    def simular_rompimento_ema_c(df, ema_periodo, stop_pct, alvo_mult, fee, max_wins, max_losses, banca_inicial, alavancagem):
        trades = []
        capital = banca_inicial
        df = df.copy()
        df['ema'] = df['close'].ewm(span=ema_periodo, adjust=False).mean()
        alerta_compra = False
        alerta_venda = False
        maxima_vela_alerta = None
        minima_vela_alerta = None
        direction = 0
        entry_price = None
        tp = None
        sl = None
        wins = 0; losses = 0
        blocked = False
        horario_entrada = None
        bloqueios_por_derrota = 0
        bloqueios_por_vitoria = 0
        alvo_pct = stop_pct * alvo_mult

        for i, row in df.iterrows():
            if i == 0: continue
            high, low, close, ts, ema = row['high'], row['low'], row['close'], row['timestamp'], row['ema']
            prev_close = df['close'].iloc[i-1]
            prev_ema = df['ema'].iloc[i-1]

            if blocked: continue

            if prev_close <= prev_ema and close > ema:
                alerta_compra = True; alerta_venda = False
                maxima_vela_alerta = high
            elif prev_close >= prev_ema and close < ema:
                alerta_venda = True; alerta_compra = False
                minima_vela_alerta = low

            if direction == 0:
                if alerta_compra and maxima_vela_alerta and high > maxima_vela_alerta:
                    direction = 1
                    entry_price = maxima_vela_alerta
                    sl = entry_price * (1 - stop_pct)
                    tp = entry_price * (1 + alvo_pct)
                    horario_entrada = ts
                    alerta_compra = False
                elif alerta_venda and minima_vela_alerta and low < minima_vela_alerta:
                    direction = -1
                    entry_price = minima_vela_alerta
                    sl = entry_price * (1 + stop_pct)
                    tp = entry_price * (1 - alvo_pct)
                    horario_entrada = ts
                    alerta_venda = False

            elif direction == 1:
                if low <= sl:
                    pnl_pct = ((sl - entry_price) / entry_price) * 100 - (fee * 100)
                    capital *= (1 + (pnl_pct * alavancagem) / 100)
                    trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": entry_price,
                                    "Saída": sl, "Resultado": "Stop", "P&L (%)": pnl_pct, "Capital": capital})
                    losses += 1; wins = 0; direction = 0
                elif high >= tp:
                    pnl_pct = ((tp - entry_price) / entry_price) * 100 - (fee * 100)
                    capital *= (1 + (pnl_pct * alavancagem) / 100)
                    trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": entry_price,
                                    "Saída": tp, "Resultado": "Alvo", "P&L (%)": pnl_pct, "Capital": capital})
                    wins += 1; losses = 0; direction = 0

            elif direction == -1:
                if high >= sl:
                    pnl_pct = ((entry_price - sl) / entry_price) * 100 - (fee * 100)
                    capital *= (1 + (pnl_pct * alavancagem) / 100)
                    trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": entry_price,
                                    "Saída": sl, "Resultado": "Stop", "P&L (%)": pnl_pct, "Capital": capital})
                    losses += 1; wins = 0; direction = 0
                elif low <= tp:
                    pnl_pct = ((entry_price - tp) / entry_price) * 100 - (fee * 100)
                    capital *= (1 + (pnl_pct * alavancagem) / 100)
                    trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": entry_price,
                                    "Saída": tp, "Resultado": "Alvo", "P&L (%)": pnl_pct, "Capital": capital})
                    wins += 1; losses = 0; direction = 0

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

    def mostrar_resultados_c(df, trades, capital_final, banca_inicial, bloq_d, bloq_v, max_l, max_w, tipo_estrategia):
        if trades:
            df_trades = pd.DataFrame(trades)
            if bloq_d > 0 or bloq_v > 0:
                st.markdown("---")
                c1, c2 = st.columns(2)
                c1.error(f"🚨 Bloqueios por derrotas: **{bloq_d}** (limite {max_l})") if bloq_d > 0 else c1.success("✅ Sem bloqueio por derrotas.")
                c2.success(f"🎉 Bloqueios por vitórias: **{bloq_v}** (meta {max_w})") if bloq_v > 0 else c2.info("ℹ️ Sem bloqueio por vitórias.")
                st.markdown("---")

            df_norm = df_trades[df_trades['Resultado'] != 'BLOQUEIO']
            total = len(df_norm)
            vit = len(df_norm[df_norm['Resultado'] == 'Alvo'])
            der = len(df_norm[df_norm['Resultado'] == 'Stop'])
            taxa = (vit / total * 100) if total > 0 else 0
            lucro = ((capital_final - banca_inicial) / banca_inicial) * 100

            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("Total", total); c2.metric("Vencedores", vit); c3.metric("Perdedores", der)
            c4.metric("Taxa Acerto", f"{taxa:.1f}%"); c5.metric("Lucro", f"{lucro:+.2f}%"); c6.metric("Capital", f"${capital_final:.2f}")

            st.subheader("📈 Curva de Capital")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_trades['Data'], y=df_trades['Capital'], mode='lines+markers', line=dict(color='#00ff88', width=2)))
            fig.update_layout(template="plotly_dark", height=400)
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("📉 Preço com Entradas e Saídas")
            fig2 = go.Figure(data=[go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'])])
            if tipo_estrategia == "Rompimento EMA":
                dfp = df.copy()
                dfp['ema'] = dfp['close'].ewm(span=ema_periodo_c, adjust=False).mean()
                fig2.add_trace(go.Scatter(x=dfp['timestamp'], y=dfp['ema'], mode='lines', name='EMA', line=dict(color='yellow', width=2)))
            longs = df_norm[df_norm['Direção'] == 'Long']
            shorts = df_norm[df_norm['Direção'] == 'Short']
            fig2.add_trace(go.Scatter(x=longs['Data'], y=longs['Entrada'], mode='markers', name='Compra', marker=dict(color='#00ff88', size=10, symbol='triangle-up')))
            fig2.add_trace(go.Scatter(x=shorts['Data'], y=shorts['Entrada'], mode='markers', name='Venda', marker=dict(color='#ff4444', size=10, symbol='triangle-down')))
            fig2.update_layout(template="plotly_dark", height=500, xaxis_rangeslider_visible=False)
            st.plotly_chart(fig2, use_container_width=True)

            st.subheader("📋 Histórico de Operações")
            st.dataframe(df_trades, use_container_width=True)
        else:
            st.warning("Nenhum trade foi gerado.")

    # ===================================================================== //
    # MAIN - CRIPTO
    # ===================================================================== //
    st.header("📈 Bot Cripto - Yahoo Finance")

    if modo_c == "Backtest (Passado)":
        st.subheader(f"📊 Backtest {symbol_c} | {timeframe_c} | {tipo_estrategia_c} | Banca: ${banca_inicial_c} | Alav: {alavancagem_c}x")

        if st.button("🚀 Rodar Backtest Cripto", type="primary", key="c_btn"):
            with st.spinner("Baixando dados..."):
                df = baixar_dados_yahoo(symbol_c, timeframe_c, str(data_inicio_c), str(data_fim_c))
                if not df.empty:
                    if tipo_estrategia_c == "Rompimento EMA":
                        trades, cap_final, bloq_d, bloq_v = simular_rompimento_ema_c(
                            df, ema_periodo_c, ema_stop_pct_c, ema_alvo_mult_c, fee_c,
                            max_wins_c, max_losses_c, banca_inicial_c, alavancagem_c
                        )
                    else:
                        trades, cap_final, bloq_d, bloq_v = simular_escada_c(
                            df, step_c, fee_c, max_wins_c, max_losses_c, tipo_estrategia_c,
                            banca_inicial_c, alavancagem_c
                        )
                    mostrar_resultados_c(df, trades, cap_final, banca_inicial_c, bloq_d, bloq_v, max_losses_c, max_wins_c, tipo_estrategia_c)

    if modo_c == "Live/Demo (Tempo Real)":
        st.subheader("🔴 Live/Demo (Binance)")
        st.info("⚠️ O modo Live/Demo está temporariamente indisponível. Use o Backtest.")

# ######################################################################### #
# ########################## BOT DERIV ################################## #
# ######################################################################### #
else:

    st.sidebar.header("⚙️ Configurações Deriv")

    modo_d = st.sidebar.selectbox("Modo de Operação", ["Backtest (Passado)", "Operação Demo (Tempo Real)"], key="d_modo")

    st.sidebar.subheader("🔑 Credenciais da API Deriv")
    deriv_app_id = st.sidebar.text_input("App ID da Deriv", "1089", key="d_appid")
    deriv_token = st.sidebar.text_input("API Token (Demo)", type="password", key="d_token")

    st.sidebar.subheader("📊 Mercado")
    symbol_d = st.sidebar.selectbox(
        "Índice Sintético",
        ["R_10", "R_25", "R_50", "R_75", "R_100"],
        index=3, key="d_symbol"
    )

    granularity_opts = {"1 minuto": 60, "2 minutos": 120, "5 minutos": 300, "15 minutos": 900,
                        "30 minutos": 1800, "1 hora": 3600, "4 horas": 14400, "1 dia": 86400}
    gran_nome_d = st.sidebar.selectbox("Timeframe", list(granularity_opts.keys()), index=2, key="d_tf")
    granularity_d = granularity_opts[gran_nome_d]

    st.sidebar.subheader("🎯 Estratégia")
    tipo_estrategia_d = st.sidebar.radio(
        "Escolha a estratégia:",
        ["Rompimento EMA", "Rompimento Vela com Tendência (Slope)"],
        key="d_estrategia"
    )

    if tipo_estrategia_d == "Rompimento EMA":
        ema_periodo_d = st.sidebar.number_input("Período da EMA", min_value=2, max_value=500, value=21, key="d_ema")
        ema_stop_pct_d = st.sidebar.number_input("Stop Loss (%)", min_value=0.01, max_value=10.0, value=1.0, step=0.1, key="d_ema_stop") / 100
        ema_alvo_mult_d = st.sidebar.number_input("Multiplicador do Alvo (x Stop)", min_value=0.5, max_value=50.0, value=2.5, step=0.1, key="d_ema_mult")
        slope_periodo_d = 0; slope_threshold_d = 0
        stop_pontos_d = 0; alvo_pontos_d = 0
    else:
        slope_periodo_d = st.sidebar.number_input("Período do Slope (candles)", min_value=5, max_value=200, value=30, key="d_slope_p")
        slope_threshold_d = st.sidebar.number_input("Força Mínima da Tendência (%)", min_value=0.01, max_value=5.0, value=0.10, step=0.01, key="d_slope_t")
        stop_pontos_d = st.sidebar.number_input("Stop Loss (pontos)", value=30.0, step=1.0, key="d_stop_pts")
        alvo_pontos_d = st.sidebar.number_input("Take Profit (pontos)", value=500.0, step=10.0, key="d_alvo_pts")
        ema_periodo_d = 0; ema_stop_pct_d = 0; ema_alvo_mult_d = 0

    st.sidebar.subheader("💰 Banca e Risco")
    banca_inicial_d = st.sidebar.number_input("Banca Inicial (USD)", value=1000.0, step=100.0, key="d_banca")
    stake_d = st.sidebar.number_input("Stake por Operação (USD)", value=2.0, step=0.5, key="d_stake")
    multiplicador_d = st.sidebar.number_input("Multiplicador (x)", min_value=1, max_value=2000, value=100, step=10, key="d_mult")

    st.sidebar.subheader("🔒 Limites")
    max_derrotas_d = st.sidebar.number_input("Máx. Derrotas Seguidas", min_value=1, max_value=20, value=5, key="d_max_l")
    max_vitorias_d = st.sidebar.number_input("Máx. Vitórias Seguidas", min_value=1, max_value=50, value=20, key="d_max_w")

    if modo_d == "Backtest (Passado)":
        st.sidebar.subheader("📅 Período do Backtest")
        data_inicio_d = st.sidebar.date_input("Data de Início", datetime.now() - timedelta(days=7), key="d_data_i")
        data_fim_d = st.sidebar.date_input("Data de Fim", datetime.now(), key="d_data_f")

    # ===================================================================== //
    # FUNÇÕES - DERIV
    # ===================================================================== //
    async def obter_velas_historicas(app_id, symbol, granularity, count, end_time):
        uri = f"wss://ws.derivws.com/websockets/v3?app_id={app_id}"
        try:
            async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as ws:
                req = {"ticks_history": symbol, "adjust_start_time": 1, "count": count,
                       "end": end_time, "granularity": granularity, "style": "candles"}
                await ws.send(json.dumps(req))
                res = await ws.recv()
                data = json.loads(res)
                if 'error' in data:
                    return pd.DataFrame(), data['error']['message']
                candles = data.get('candles', [])
                if not candles:
                    return pd.DataFrame(), "Sem dados"
                df = pd.DataFrame(candles)
                df['timestamp'] = pd.to_datetime(df['epoch'], unit='s')
                df = df.rename(columns={'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close'})
                df = df[['timestamp', 'open', 'high', 'low', 'close']]
                df = df.astype({'open': float, 'high': float, 'low': float, 'close': float})
                return df, None
        except Exception as e:
            return pd.DataFrame(), str(e)

    def simular_rompimento_ema_d(df, ema_periodo, stop_pct, alvo_mult, banca_inicial, stake, multiplicador, max_derrotas, max_vitorias):
        if df.empty or len(df) < ema_periodo + 20:
            return None, None, None, None
        df = df.copy()
        df['ema'] = df['close'].ewm(span=ema_periodo, adjust=False).mean()
        capital = banca_inicial
        posicao = None; entry_price = None; stop_price = None; alvo_price = None
        alerta_compra = False; alerta_venda = False
        maxima_vela_alerta = None; minima_vela_alerta = None
        vitorias = 0; derrotas = 0; trades = []; bloqueado = False
        horario_entrada = None
        alvo_pct = stop_pct * alvo_mult

        for i in range(1, len(df)):
            row = df.iloc[i]; prev = df.iloc[i-1]
            high, low, close = row['high'], row['low'], row['close']
            ts = row['timestamp']
            ema_atual = row['ema']; ema_ant = prev['ema']; close_ant = prev['close']
            if bloqueado: continue

            if close_ant <= ema_ant and close > ema_atual:
                alerta_compra = True; alerta_venda = False; maxima_vela_alerta = high
            elif close_ant >= ema_ant and close < ema_atual:
                alerta_venda = True; alerta_compra = False; minima_vela_alerta = low

            if posicao is None:
                if alerta_compra and maxima_vela_alerta and high > maxima_vela_alerta:
                    posicao = "long"; entry_price = maxima_vela_alerta
                    stop_price = entry_price * (1 - stop_pct)
                    alvo_price = entry_price * (1 + alvo_pct)
                    horario_entrada = ts; alerta_compra = False
                elif alerta_venda and minima_vela_alerta and low < minima_vela_alerta:
                    posicao = "short"; entry_price = minima_vela_alerta
                    stop_price = entry_price * (1 + stop_pct)
                    alvo_price = entry_price * (1 - alvo_pct)
                    horario_entrada = ts; alerta_venda = False
            else:
                if posicao == "long":
                    if low <= stop_price:
                        pnl_pct = ((stop_price - entry_price) / entry_price) * 100 * multiplicador
                        capital -= stake; derrotas += 1; vitorias = 0
                        trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": round(entry_price, 2),
                                        "Saída": round(stop_price, 2), "Resultado": "Stop",
                                        "P&L (%)": round(pnl_pct, 3), "Capital": round(capital, 2)})
                        posicao = None
                    elif high >= alvo_price:
                        pnl_pct = ((alvo_price - entry_price) / entry_price) * 100 * multiplicador
                        capital += stake * (pnl_pct / 100); vitorias += 1; derrotas = 0
                        trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": round(entry_price, 2),
                                        "Saída": round(alvo_price, 2), "Resultado": "Alvo",
                                        "P&L (%)": round(pnl_pct, 3), "Capital": round(capital, 2)})
                        posicao = None
                elif posicao == "short":
                    if high >= stop_price:
                        pnl_pct = ((entry_price - stop_price) / entry_price) * 100 * multiplicador
                        capital -= stake; derrotas += 1; vitorias = 0
                        trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": round(entry_price, 2),
                                        "Saída": round(stop_price, 2), "Resultado": "Stop",
                                        "P&L (%)": -round(pnl_pct, 3), "Capital": round(capital, 2)})
                        posicao = None
                    elif low <= alvo_price:
                        pnl_pct = ((entry_price - alvo_price) / entry_price) * 100 * multiplicador
                        capital += stake * (pnl_pct / 100); vitorias += 1; derrotas = 0
                        trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": round(entry_price, 2),
                                        "Saída": round(alvo_price, 2), "Resultado": "Alvo",
                                        "P&L (%)": round(pnl_pct, 3), "Capital": round(capital, 2)})
                        posicao = None

            if derrotas >= max_derrotas: bloqueado = True
            if vitorias >= max_vitorias: bloqueado = True

        return trades, capital, bloqueado, df

    def simular_rompimento_vela_d(df, slope_periodo, slope_threshold, stop_pontos, alvo_pontos,
                                    banca_inicial, stake, multiplicador, max_derrotas, max_vitorias):
        if df.empty or len(df) < slope_periodo + 20:
            return None, None, None, None
        df = df.copy()
        df['slope_pct'] = ((df['close'] - df['close'].shift(slope_periodo)) / df['close'].shift(slope_periodo)) * 100
        capital = banca_inicial
        posicao = None; entry_price = None; stop_price = None; alvo_price = None
        linha_rompimento = None; tipo_linha = None
        vitorias = 0; derrotas = 0; trades = []; bloqueado = False
        tendencia = 0; horario_entrada = None

        for i in range(slope_periodo + 1, len(df)):
            row = df.iloc[i]; prev = df.iloc[i-1]
            high, low, close = row['high'], row['low'], row['close']
            open_ = row['open']
            ts = row['timestamp']; slope = row['slope_pct']
            if pd.isna(slope) or bloqueado: continue

            if slope >= slope_threshold: tendencia = 1
            elif slope <= -slope_threshold: tendencia = -1
            else: tendencia = 0

            if posicao is None:
                if tendencia == 0: continue
                if prev['close'] > prev['open']:
                    linha_rompimento = prev['high']; tipo_linha = "topo"
                else:
                    linha_rompimento = prev['low']; tipo_linha = "fundo"

                if tipo_linha == "topo" and close > linha_rompimento and tendencia == 1:
                    posicao = "long"; entry_price = close
                    stop_price = entry_price - stop_pontos
                    alvo_price = entry_price + alvo_pontos
                    horario_entrada = ts
                elif tipo_linha == "fundo" and close < linha_rompimento and tendencia == -1:
                    posicao = "short"; entry_price = close
                    stop_price = entry_price + stop_pontos
                    alvo_price = entry_price - alvo_pontos
                    horario_entrada = ts
            else:
                if posicao == "long":
                    if low <= stop_price:
                        pnl_pct = ((stop_price - entry_price) / entry_price) * 100 * multiplicador
                        capital -= stake; derrotas += 1; vitorias = 0
                        trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": round(entry_price, 2),
                                        "Saída": round(stop_price, 2), "Resultado": "Stop", "Slope (%)": round(slope, 4),
                                        "P&L (%)": round(pnl_pct, 3), "Capital": round(capital, 2)})
                        posicao = None
                    elif high >= alvo_price:
                        pnl_pct = ((alvo_price - entry_price) / entry_price) * 100 * multiplicador
                        capital += stake * (pnl_pct / 100); vitorias += 1; derrotas = 0
                        trades.append({"Data": horario_entrada, "Direção": "Long", "Entrada": round(entry_price, 2),
                                        "Saída": round(alvo_price, 2), "Resultado": "Alvo", "Slope (%)": round(slope, 4),
                                        "P&L (%)": round(pnl_pct, 3), "Capital": round(capital, 2)})
                        posicao = None
                elif posicao == "short":
                    if high >= stop_price:
                        pnl_pct = ((entry_price - stop_price) / entry_price) * 100 * multiplicador
                        capital -= stake; derrotas += 1; vitorias = 0
                        trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": round(entry_price, 2),
                                        "Saída": round(stop_price, 2), "Resultado": "Stop", "Slope (%)": round(slope, 4),
                                        "P&L (%)": -round(pnl_pct, 3), "Capital": round(capital, 2)})
                        posicao = None
                    elif low <= alvo_price:
                        pnl_pct = ((entry_price - alvo_price) / entry_price) * 100 * multiplicador
                        capital += stake * (pnl_pct / 100); vitorias += 1; derrotas = 0
                        trades.append({"Data": horario_entrada, "Direção": "Short", "Entrada": round(entry_price, 2),
                                        "Saída": round(alvo_price, 2), "Resultado": "Alvo", "Slope (%)": round(slope, 4),
                                        "P&L (%)": round(pnl_pct, 3), "Capital": round(capital, 2)})
                        posicao = None

            if derrotas >= max_derrotas: bloqueado = True
            if vitorias >= max_vitorias: bloqueado = True

        return trades, capital, bloqueado, df

    # ===================================================================== //
    # MAIN - DERIV
    # ===================================================================== //
    st.header("📊 Bot Deriv - Índices Sintéticos")

    if modo_d == "Backtest (Passado)":
        st.subheader(f"📊 Backtest {symbol_d} | {gran_nome_d} | {tipo_estrategia_d}")

        if st.button("🚀 Rodar Backtest Deriv", type="primary", key="d_btn"):
            with st.spinner("Baixando dados da Deriv..."):
                start_epoch = int(pd.Timestamp(data_inicio_d).timestamp())
                end_epoch = int(pd.Timestamp(data_fim_d).timestamp())
                count = min(5000, int((end_epoch - start_epoch) / granularity_d))

                if count <= 0:
                    st.error("Período inválido.")
                else:
                    df, erro = asyncio.run(obter_velas_historicas(deriv_app_id, symbol_d, granularity_d, count, end_epoch))

                    if erro:
                        st.error(f"Erro da API Deriv: {erro}")
                    elif not df.empty:
                        if tipo_estrategia_d == "Rompimento EMA":
                            trades, cap_final, bloqueado, df_plot = simular_rompimento_ema_d(
                                df, ema_periodo_d, ema_stop_pct_d, ema_alvo_mult_d,
                                banca_inicial_d, stake_d, multiplicador_d, max_derrotas_d, max_vitorias_d
                            )
                        else:
                            trades, cap_final, bloqueado, df_plot = simular_rompimento_vela_d(
                                df, slope_periodo_d, slope_threshold_d, stop_pontos_d, alvo_pontos_d,
                                banca_inicial_d, stake_d, multiplicador_d, max_derrotas_d, max_vitorias_d
                            )

                        if trades:
                            df_trades = pd.DataFrame(trades)
                            total = len(df_trades)
                            vit = len(df_trades[df_trades['Resultado'] == 'Alvo'])
                            der = len(df_trades[df_trades['Resultado'] == 'Stop'])
                            taxa = (vit / total * 100) if total > 0 else 0
                            lucro = ((cap_final - banca_inicial_d) / banca_inicial_d) * 100

                            c1, c2, c3, c4, c5, c6 = st.columns(6)
                            c1.metric("Total", total); c2.metric("Vencedores", vit); c3.metric("Perdedores", der)
                            c4.metric("Taxa Acerto", f"{taxa:.1f}%"); c5.metric("Lucro", f"{lucro:+.2f}%"); c6.metric("Capital", f"${cap_final:.2f}")

                            if bloqueado:
                                st.warning("⚠️ O bot foi BLOQUEADO por atingir um limite.")

                            st.subheader("📉 Preço com Entradas e Saídas")
                            fig_p = go.Figure(data=[go.Candlestick(x=df_plot['timestamp'], open=df_plot['open'],
                                                                    high=df_plot['high'], low=df_plot['low'],
                                                                    close=df_plot['close'])])
                            if tipo_estrategia_d == "Rompimento EMA":
                                fig_p.add_trace(go.Scatter(x=df_plot['timestamp'], y=df_plot['ema'],
                                                            mode='lines', name='EMA', line=dict(color='yellow', width=2)))
                            longs = df_trades[df_trades['Direção'] == 'Long']
                            shorts = df_trades[df_trades['Direção'] == 'Short']
                            fig_p.add_trace(go.Scatter(x=longs['Data'], y=longs['Entrada'], mode='markers',
                                                        name='Compra', marker=dict(color='#00ff88', size=10, symbol='triangle-up')))
                            fig_p.add_trace(go.Scatter(x=shorts['Data'], y=shorts['Entrada'], mode='markers',
                                                        name='Venda', marker=dict(color='#ff4444', size=10, symbol='triangle-down')))
                            fig_p.update_layout(template="plotly_dark", height=500, xaxis_rangeslider_visible=False)
                            st.plotly_chart(fig_p, use_container_width=True)

                            if tipo_estrategia_d == "Rompimento Vela com Tendência (Slope)":
                                st.subheader("📊 Slope (Força da Tendência em %)")
                                fig_s = go.Figure()
                                fig_s.add_trace(go.Scatter(x=df_plot['timestamp'], y=df_plot['slope_pct'],
                                                            mode='lines', name='Slope (%)', line=dict(color='#00ccff', width=2)))
                                fig_s.add_hline(y=slope_threshold_d, line_dash="dash", line_color="green")
                                fig_s.add_hline(y=-slope_threshold_d, line_dash="dash", line_color="red")
                                fig_s.update_layout(template="plotly_dark", height=300)
                                st.plotly_chart(fig_s, use_container_width=True)

                            st.subheader("📈 Curva de Capital")
                            fig_e = go.Figure()
                            fig_e.add_trace(go.Scatter(x=df_trades['Data'], y=df_trades['Capital'],
                                                        mode='lines+markers', line=dict(color='#00ff88', width=2)))
                            fig_e.update_layout(template="plotly_dark", height=400)
                            st.plotly_chart(fig_e, use_container_width=True)

                            st.subheader("📋 Histórico de Operações")
                            st.dataframe(df_trades, use_container_width=True)
                        else:
                            st.warning("Nenhum trade gerado.")
                    else:
                        st.error("Não foi possível obter dados da Deriv.")

    else:
        st.subheader("🔴 Operação Demo (Deriv)")
        if not deriv_token:
            st.info("Insira o API Token da Deriv (conta Demo) no menu lateral.")
        else:
            st.warning("⚠️ O modo de operação em tempo real estará disponível na próxima versão.")
            st.info("✅ Use o Backtest para validar a estratégia com dados históricos.")

st.sidebar.markdown("---")
st.sidebar.caption("Bot Multi-Mercados v1.0")
