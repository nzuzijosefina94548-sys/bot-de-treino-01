import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import yfinance as yf

# ========================================================================= //
# CONFIGURAÇÃO DA PÁGINA
# ========================================================================= //
st.set_page_config(page_title="Bot Cripto - 4 Estratégias", page_icon="🤖", layout="wide")
st.title("🤖 Painel do Bot Cripto - 4 Estratégias")

# ========================================================================= //
# MENU LATERAL
# ========================================================================= //
st.sidebar.header("⚙️ Configurações")

modo = st.sidebar.selectbox("Modo de Operação", ["Backtest (Passado)", "Live/Demo (Tempo Real)"])

# ========================================================================= //
# 1. ATIVO E TIMEFRAME
# ========================================================================= //
st.sidebar.subheader("📊 Ativo e Timeframe")

# Lista de criptos disponíveis + campo livre
ativopredefinido = st.sidebar.selectbox(
    "Ativo (escolha ou digite abaixo)",
    ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
     "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT", "LINKUSDT", "Outro"]
)

if ativopredefinido == "Outro":
    symbol = st.sidebar.text_input("Digite o par (ex: LTCUSDT)", "LTCUSDT")
else:
    symbol = ativopredefinido

timeframe = st.sidebar.selectbox(
    "Timeframe",
    ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "3d", "1s", "1M", "3M", "1A"],
    index=4
)

# ========================================================================= //
# 2. BANCA E RISCO
# ========================================================================= //
st.sidebar.subheader("💰 Banca e Risco")
banca_inicial = st.sidebar.number_input("Banca Inicial (USDT)", min_value=10.0, max_value=1000000.0, value=1000.0, step=100.0)
usar_alavancagem = st.sidebar.checkbox("Usar Alavancagem?", value=False)
alavancagem = st.sidebar.slider("Alavancagem (x)", min_value=1, max_value=20, value=1, step=1) if usar_alavancagem else 1

# ========================================================================= //
# 3. ESCOLHA DA ESTRATÉGIA
# ========================================================================= //
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

# ========================================================================= //
# 4. PARÂMETROS DE RISCO (SEMPRE VISÍVEIS)
# ========================================================================= //
st.sidebar.subheader("📉 Stop Loss e Alvo")

stop_loss_pct = st.sidebar.number_input(
    "Stop Loss (%)", min_value=0.1, max_value=50.0, value=1.0, step=0.1,
    help="Percentagem de perda máxima por operação"
) / 100

alvo_pct = st.sidebar.number_input(
    "Alvo / Lucro Desejado (%)", min_value=0.1, max_value=50.0, value=1.0, step=0.1,
    help="Percentagem de lucro por operação"
) / 100

fee = st.sidebar.number_input(
    "Taxa da Corretora (%)", min_value=0.01, max_value=5.0, value=0.10, step=0.01,
    help="Taxa total (abertura + fecho)"
) / 100

# ========================================================================= //
# 5. PARÂMETROS ESPECÍFICOS DA EMA (SEMPRE VISÍVEIS)
# ========================================================================= //
st.sidebar.subheader("📈 Parâmetros EMA (Rompimento EMA)")
ema_periodo = st.sidebar.number_input(
    "Período da EMA", min_value=2, max_value=500, value=21,
    help="Média Móvel Exponencial usada para detetar tendência"
)

# ========================================================================= //
# 6. LIMITES DE SEGURANÇA
# ========================================================================= //
st.sidebar.subheader("🔒 Limites de Segurança")
max_wins = st.sidebar.number_input("Máx. Vitórias Seguidas", min_value=1, max_value=50, value=20)
max_losses = st.sidebar.number_input("Máx. Derrotas Seguidas", min_value=1, max_value=50, value=10)

# ========================================================================= //
# 7. PERÍODO DO BACKTEST
# ========================================================================= //
if modo == "Backtest (Passado)":
    st.sidebar.subheader("📅 Período do Backtest")
    data_inicio = st.sidebar.date_input("Data de Início", datetime.now() - timedelta(days=30))
    data_fim = st.sidebar.date_input("Data de Fim", datetime.now())

# ========================================================================= //
# FUNÇÃO: BAIXAR DADOS
# ========================================================================= //
@st.cache_data(ttl=300)
def baixar_dados_yahoo(symbol, timeframe, start_str, end_str):
    try:
        ticker = symbol.replace("USDT", "-USD")
        yf_int = {"2h": "1h", "4h": "1h", "6h": "1h", "12h": "1h",
                  "3d": "1d", "1A": "1mo", "1s": "1wk", "1M": "1mo", "3M": "3mo"}.get(timeframe, timeframe)
        df = yf.download(ticker, start=start_str, end=end_str, interval=yf_int, progress=False)
        if df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.reset_index(inplace=True)
        df.rename(columns={'Date': 'timestamp', 'Datetime': 'timestamp', 'Open': 'open',
                            'High': 'high', 'Low': 'low', 'Close': 'close'}, inplace=True)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        for c in ['open', 'high', 'low', 'close']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)
        return df
    except Exception as e:
        st.error(f"Erro ao baixar dados: {e}")
        return pd.DataFrame()

# ========================================================================= //
# ESTRATÉGIAS 1, 2, 3 - ESCADA DINÂMICA (com stop e alvo separados)
# ========================================================================= //
def simular_escada(df, stop_pct, alvo_pct, fee, max_wins, max_losses, tipo_est, banca, alav):
    trades = []
    cap = banca
    ref = df['close'].iloc[0]
    d = 0; ep = None; tp = None; sl = None
    w = 0; l = 0; blk = False; he = None
    pa = 0.0
    bd = 0; bv = 0

    for i, row in df.iterrows():
        h, l, c, ts = row['high'], row['low'], row['close'], row['timestamp']
        if blk:
            continue

        if d == 0:
            # Fator do alvo com base na estratégia
            if tipo_est == "Normal (Alvo Fixo)":
                f = alvo_pct + fee
            elif tipo_est == "Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)":
                f = (pa + fee + fee + alvo_pct) if pa > 0 else (alvo_pct + fee)
            else:
                f = (pa + fee + fee) if pa > 0 else (alvo_pct + fee)

            # Gatilho de entrada
            if h >= ref * (1 + stop_pct):
                d = 1; ep = ref * (1 + stop_pct); tp = ep * (1 + f); sl = ep * (1 - stop_pct - fee); he = ts
            elif l <= ref * (1 - stop_pct):
                d = -1; ep = ref * (1 - stop_pct); tp = ep * (1 - f); sl = ep * (1 + stop_pct + fee); he = ts

        elif d == 1:
            if l <= sl:
                p = ((sl - ep) / ep) * 100
                cap *= (1 + (p * alav) / 100)
                pa = abs(p / 100) + fee
                trades.append({"Data": he, "Direção": "Long", "Entrada": ep, "Saída": sl,
                                "Resultado": "Stop", "P&L (%)": p, "Capital": cap})
                l += 1; w = 0; d = -1; ref = sl; ep = sl
                if tipo_est == "Normal (Alvo Fixo)":
                    f = alvo_pct + fee
                elif tipo_est == "Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)":
                    f = pa + fee + fee + alvo_pct
                else:
                    f = pa + fee + fee
                tp = ep * (1 - f); sl = ep * (1 + stop_pct + fee); he = ts
            elif h >= tp:
                p = ((tp - ep) / ep) * 100
                cap *= (1 + (p * alav) / 100)
                pa = 0.0
                trades.append({"Data": he, "Direção": "Long", "Entrada": ep, "Saída": tp,
                                "Resultado": "Alvo", "P&L (%)": p, "Capital": cap})
                w += 1; l = 0; ref = tp; ep = tp
                f = alvo_pct + fee
                tp = ep * (1 + f); sl = ep * (1 - stop_pct - fee); he = ts

        elif d == -1:
            if h >= sl:
                p = ((ep - sl) / ep) * 100
                cap *= (1 + (p * alav) / 100)
                pa = abs(p / 100) + fee
                trades.append({"Data": he, "Direção": "Short", "Entrada": ep, "Saída": sl,
                                "Resultado": "Stop", "P&L (%)": p, "Capital": cap})
                l += 1; w = 0; d = 1; ref = sl; ep = sl
                if tipo_est == "Normal (Alvo Fixo)":
                    f = alvo_pct + fee
                elif tipo_est == "Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)":
                    f = pa + fee + fee + alvo_pct
                else:
                    f = pa + fee + fee
                tp = ep * (1 + f); sl = ep * (1 - stop_pct - fee); he = ts
            elif l <= tp:
                p = ((ep - tp) / ep) * 100
                cap *= (1 + (p * alav) / 100)
                pa = 0.0
                trades.append({"Data": he, "Direção": "Short", "Entrada": ep, "Saída": tp,
                                "Resultado": "Alvo", "P&L (%)": p, "Capital": cap})
                w += 1; l = 0; ref = tp; ep = tp
                f = alvo_pct + fee
                tp = ep * (1 - f); sl = ep * (1 + stop_pct + fee); he = ts

        if l >= max_losses:
            blk = True; bd += 1
            trades.append({"Data": ts, "Direção": "-", "Entrada": 0, "Saída": 0,
                            "Resultado": "BLOQUEIO", "P&L (%)": 0, "Capital": cap})
            w = 0; l = 0
        if w >= max_wins:
            blk = True; bv += 1
            trades.append({"Data": ts, "Direção": "-", "Entrada": 0, "Saída": 0,
                            "Resultado": "BLOQUEIO", "P&L (%)": 0, "Capital": cap})
            w = 0; l = 0

    return trades, cap, bd, bv

# ========================================================================= //
# ESTRATÉGIA 4 - ROMPIMENTO EMA
# ========================================================================= //
def simular_rompimento_ema(df, emp, stop_pct, alvo_pct, fee, mw, ml, banca, alav):
    trades = []
    cap = banca
    df = df.copy()
    df['ema'] = df['close'].ewm(span=emp, adjust=False).mean()
    ac = False; av = False; mx = None; mn = None
    d = 0; ep = None; tp = None; sl = None
    w = 0; l = 0; blk = False; he = None
    bd = 0; bv = 0

    for i, row in df.iterrows():
        if i == 0:
            continue
        h, l, c, ts, e = row['high'], row['low'], row['close'], row['timestamp'], row['ema']
        pc = df['close'].iloc[i-1]; pe = df['ema'].iloc[i-1]

        if blk:
            continue

        if pc <= pe and c > e:
            ac = True; av = False; mx = h
        elif pc >= pe and c < e:
            av = True; ac = False; mn = l

        if d == 0:
            if ac and mx and h > mx:
                d = 1; ep = mx; sl = ep * (1 - stop_pct); tp = ep * (1 + alvo_pct); he = ts; ac = False
            elif av and mn and l < mn:
                d = -1; ep = mn; sl = ep * (1 + stop_pct); tp = ep * (1 - alvo_pct); he = ts; av = False
        elif d == 1:
            if l <= sl:
                p = ((sl - ep) / ep) * 100 - (fee * 100)
                cap *= (1 + (p * alav) / 100)
                trades.append({"Data": he, "Direção": "Long", "Entrada": ep, "Saída": sl,
                                "Resultado": "Stop", "P&L (%)": p, "Capital": cap})
                l += 1; w = 0; d = 0
            elif h >= tp:
                p = ((tp - ep) / ep) * 100 - (fee * 100)
                cap *= (1 + (p * alav) / 100)
                trades.append({"Data": he, "Direção": "Long", "Entrada": ep, "Saída": tp,
                                "Resultado": "Alvo", "P&L (%)": p, "Capital": cap})
                w += 1; l = 0; d = 0
        elif d == -1:
            if h >= sl:
                p = ((ep - sl) / ep) * 100 - (fee * 100)
                cap *= (1 + (p * alav) / 100)
                trades.append({"Data": he, "Direção": "Short", "Entrada": ep, "Saída": sl,
                                "Resultado": "Stop", "P&L (%)": p, "Capital": cap})
                l += 1; w = 0; d = 0
            elif l <= tp:
                p = ((ep - tp) / ep) * 100 - (fee * 100)
                cap *= (1 + (p * alav) / 100)
                trades.append({"Data": he, "Direção": "Short", "Entrada": ep, "Saída": tp,
                                "Resultado": "Alvo", "P&L (%)": p, "Capital": cap})
                w += 1; l = 0; d = 0

        if l >= ml:
            blk = True; bd += 1
            trades.append({"Data": ts, "Direção": "-", "Entrada": 0, "Saída": 0,
                            "Resultado": "BLOQUEIO", "P&L (%)": 0, "Capital": cap})
            w = 0; l = 0
        if w >= mw:
            blk = True; bv += 1
            trades.append({"Data": ts, "Direção": "-", "Entrada": 0, "Saída": 0,
                            "Resultado": "BLOQUEIO", "P&L (%)": 0, "Capital": cap})
            w = 0; l = 0

    return trades, cap, bd, bv

# ========================================================================= //
# MOSTRAR RESULTADOS
# ========================================================================= //
def mostrar_resultados(df, trades, cap_f, banca, bd, bv, ml, mw, tipo_est):
    if not trades:
        st.warning("Nenhum trade gerado.")
        return

    dft = pd.DataFrame(trades)

    if bd > 0 or bv > 0:
        st.markdown("---")
        c1, c2 = st.columns(2)
        if bd > 0:
            c1.error(f"🚨 Bloqueios por DERROTAS: **{bd}** (limite {ml})")
        else:
            c1.success("✅ Sem bloqueio por derrotas.")
        if bv > 0:
            c2.success(f"🎉 Bloqueios por VITÓRIAS: **{bv}** (meta {mw})")
        else:
            c2.info("ℹ️ Sem bloqueio por vitórias.")
        st.markdown("---")

    dn = dft[dft['Resultado'] != 'BLOQUEIO']
    t = len(dn)
    v = len(dn[dn['Resultado'] == 'Alvo'])
    r = len(dn[dn['Resultado'] == 'Stop'])
    tx = (v / t * 100) if t > 0 else 0
    lc = ((cap_f - banca) / banca) * 100

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total", t)
    c2.metric("Vencedores", v)
    c3.metric("Perdedores", r)
    c4.metric("Taxa Acerto", f"{tx:.1f}%")
    c5.metric("Lucro", f"{lc:+.2f}%")
    c6.metric("Capital", f"${cap_f:.2f}")

    st.subheader("📈 Curva de Capital")
    f1 = go.Figure()
    f1.add_trace(go.Scatter(x=dft['Data'], y=dft['Capital'], mode='lines+markers',
                             line=dict(color='#00ff88', width=2)))
    f1.update_layout(template="plotly_dark", height=400)
    st.plotly_chart(f1, use_container_width=True)

    st.subheader("📉 Preço com Entradas e Saídas")
    f2 = go.Figure(data=[go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'],
                                          low=df['low'], close=df['close'])])
    if tipo_est == "Rompimento EMA":
        dp = df.copy()
        dp['ema'] = dp['close'].ewm(span=ema_periodo, adjust=False).mean()
        f2.add_trace(go.Scatter(x=dp['timestamp'], y=dp['ema'], mode='lines', name='EMA',
                                 line=dict(color='yellow', width=2)))
    L = dn[dn['Direção'] == 'Long']
    S = dn[dn['Direção'] == 'Short']
    f2.add_trace(go.Scatter(x=L['Data'], y=L['Entrada'], mode='markers', name='Compra',
                             marker=dict(color='#00ff88', size=10, symbol='triangle-up')))
    f2.add_trace(go.Scatter(x=S['Data'], y=S['Entrada'], mode='markers', name='Venda',
                             marker=dict(color='#ff4444', size=10, symbol='triangle-down')))
    f2.update_layout(template="plotly_dark", height=500, xaxis_rangeslider_visible=False)
    st.plotly_chart(f2, use_container_width=True)

    st.subheader("📋 Histórico de Operações")
    st.dataframe(dft, use_container_width=True)

# ========================================================================= //
# EXECUÇÃO
# ========================================================================= //
st.header("📈 Bot Cripto - Yahoo Finance")

if modo == "Backtest (Passado)":
    st.subheader(f"📊 Backtest {symbol} | {timeframe} | {tipo_estrategia}")
    st.info(f"📉 Stop: {stop_loss_pct*100:.2f}% | 📈 Alvo: {alvo_pct*100:.2f}% | 💸 Taxa: {fee*100:.2f}% | 📊 EMA: {ema_periodo} | 💰 Banca: ${banca_inicial} | ⚡ Alav: {alavancagem}x")

    if st.button("🚀 Rodar Backtest", type="primary"):
        with st.spinner("Baixando dados do Yahoo Finance..."):
            df = baixar_dados_yahoo(symbol, timeframe, str(data_inicio), str(data_fim))
            if not df.empty:
                if tipo_estrategia == "Rompimento EMA":
                    trades, cap_f, bd, bv = simular_rompimento_ema(
                        df, ema_periodo, stop_loss_pct, alvo_pct, fee,
                        max_wins, max_losses, banca_inicial, alavancagem
                    )
                else:
                    trades, cap_f, bd, bv = simular_escada(
                        df, stop_loss_pct, alvo_pct, fee, max_wins, max_losses,
                        tipo_estrategia, banca_inicial, alavancagem
                    )
                mostrar_resultados(df, trades, cap_f, banca_inicial, bd, bv,
                                    max_losses, max_wins, tipo_estrategia)

if modo == "Live/Demo (Tempo Real)":
    st.info("⚠️ O modo Live/Demo está temporariamente indisponível. Use o Backtest.")

st.sidebar.markdown("---")
st.sidebar.caption("Bot Cripto - 4 Estratégias v2.0")
