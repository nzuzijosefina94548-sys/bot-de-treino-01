import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import yfinance as yf
import asyncio
import json
import websockets

st.set_page_config(page_title="Bot Multi-Mercados", page_icon="🤖", layout="wide")
st.title("🤖 Painel do Bot - Multi-Mercados")

st.sidebar.markdown("## 🤖 Escolha o Bot")
bot_escolhido = st.sidebar.radio("Mercado:", ["📈 Cripto (Yahoo Finance / Binance)", "📊 Deriv (Índices Sintéticos)"])
st.sidebar.markdown("---")

# ========================================================================== #
# ============================== BOT CRIPTO ================================ #
# ========================================================================== #
if bot_escolhido == "📈 Cripto (Yahoo Finance / Binance)":

    st.sidebar.header("⚙️ Configurações Cripto")
    modo_c = st.sidebar.selectbox("Modo de Operação", ["Backtest (Passado)", "Live/Demo (Tempo Real)"], key="c_modo")

    st.sidebar.subheader("💰 Banca e Risco")
    banca_inicial_c = st.sidebar.number_input("Banca Inicial (USDT)", min_value=10.0, max_value=1000000.0, value=1000.0, step=100.0, key="c_banca")
    usar_alavancagem_c = st.sidebar.checkbox("Usar Alavancagem?", value=False, key="c_alav")
    alavancagem_c = st.sidebar.slider("Alavancagem (x)", min_value=1, max_value=20, value=1, step=1, key="c_alav_slider") if usar_alavancagem_c else 1

    st.sidebar.subheader("Parâmetros da Estratégia")
    symbol_c = st.sidebar.text_input("Par (ex: BTCUSDT)", "BTCUSDT", key="c_symbol")
    timeframe_c = st.sidebar.selectbox("Timeframe",
        ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "3d", "1s", "1M", "3M", "1A"],
        index=4, key="c_tf")
    step_c = st.sidebar.number_input("Lucro Desejado (%)", min_value=0.1, max_value=10.0, value=1.0, step=0.1, key="c_step") / 100
    fee_c = st.sidebar.number_input("Taxa da Corretora (%)", min_value=0.01, max_value=1.0, value=0.10, step=0.01, key="c_fee") / 100

    st.sidebar.subheader("🎯 Estratégia")
    tipo_estrategia_c = st.sidebar.radio("Escolha a estratégia:",
        ["Normal (Alvo Fixo)", "Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)",
         "Recuperação Simples (Apenas Perda Anterior + Taxas)", "Rompimento EMA"], key="c_estrategia")

    if tipo_estrategia_c == "Rompimento EMA":
        ema_periodo_c = st.sidebar.number_input("Período da EMA", min_value=2, max_value=500, value=21, key="c_ema")
        ema_stop_pct_c = st.sidebar.number_input("Stop Loss (%)", min_value=0.01, max_value=10.0, value=1.0, step=0.1, key="c_ema_stop") / 100
        ema_alvo_mult_c = st.sidebar.number_input("Multiplicador do Alvo (x Stop)", min_value=0.5, max_value=50.0, value=2.5, step=0.1, key="c_ema_mult")
    else:
        ema_periodo_c = 21; ema_stop_pct_c = 0.01; ema_alvo_mult_c = 2.5

    max_wins_c = st.sidebar.number_input("Máx. Vitórias Seguidas", min_value=1, max_value=50, value=20, key="c_max_w")
    max_losses_c = st.sidebar.number_input("Máx. Derrotas Seguidas", min_value=1, max_value=50, value=10, key="c_max_l")

    if modo_c == "Backtest (Passado)":
        st.sidebar.subheader("📅 Período do Backtest")
        data_inicio_c = st.sidebar.date_input("Data de Início", datetime.now() - timedelta(days=30), key="c_data_i")
        data_fim_c = st.sidebar.date_input("Data de Fim", datetime.now(), key="c_data_f")

    @st.cache_data(ttl=300)
    def baixar_dados_yahoo(symbol, timeframe, start_str, end_str):
        try:
            ticker = symbol.replace("USDT", "-USD")
            yf_int = {"2h":"1h","4h":"1h","6h":"1h","12h":"1h","3d":"1d","1A":"1mo","1s":"1wk","1M":"1mo","3M":"3mo"}.get(timeframe, timeframe)
            df = yf.download(ticker, start=start_str, end=end_str, interval=yf_int, progress=False)
            if df.empty: return pd.DataFrame()
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df.reset_index(inplace=True)
            df.rename(columns={'Date':'timestamp','Datetime':'timestamp','Open':'open','High':'high','Low':'low','Close':'close'}, inplace=True)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            for c in ['open','high','low','close']: df[c] = pd.to_numeric(df[c], errors='coerce')
            df.dropna(subset=['open','high','low','close'], inplace=True)
            return df
        except Exception as e:
            st.error(f"Erro: {e}"); return pd.DataFrame()

    def simular_escada_c(df, step, fee, max_wins, max_losses, tipo_est, banca, alav):
        trades=[]; cap=banca; ref=df['close'].iloc[0]; d=0; ep=None; tp=None; sl=None
        w=0; l=0; blk=False; he=None; pa=0.0; bd=0; bv=0
        for i,row in df.iterrows():
            h,l,c,ts = row['high'],row['low'],row['close'],row['timestamp']
            if blk: continue
            if d==0:
                if tipo_est=="Normal (Alvo Fixo)": f=step+fee
                elif tipo_est=="Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)": f=(pa+fee+fee+step) if pa>0 else (step+fee)
                else: f=(pa+fee+fee) if pa>0 else (step+fee)
                if h>=ref*(1+step): d=1; ep=ref*(1+step); tp=ep*(1+f); sl=ep*(1-step-fee); he=ts
                elif l<=ref*(1-step): d=-1; ep=ref*(1-step); tp=ep*(1-f); sl=ep*(1+step+fee); he=ts
            elif d==1:
                if l<=sl:
                    p=((sl-ep)/ep)*100; cap*=(1+(p*alav)/100); pa=abs(p/100)+fee
                    trades.append({"Data":he,"Direção":"Long","Entrada":ep,"Saída":sl,"Resultado":"Stop","P&L (%)":p,"Capital":cap})
                    l+=1; w=0; d=-1; ref=sl; ep=sl
                    if tipo_est=="Normal (Alvo Fixo)": f=step+fee
                    elif tipo_est=="Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)": f=pa+fee+fee+step
                    else: f=pa+fee+fee
                    tp=ep*(1-f); sl=ep*(1+step+fee); he=ts
                elif h>=tp:
                    p=((tp-ep)/ep)*100; cap*=(1+(p*alav)/100); pa=0.0
                    trades.append({"Data":he,"Direção":"Long","Entrada":ep,"Saída":tp,"Resultado":"Alvo","P&L (%)":p,"Capital":cap})
                    w+=1; l=0; ref=tp; ep=tp; f=step+fee; tp=ep*(1+f); sl=ep*(1-step-fee); he=ts
            elif d==-1:
                if h>=sl:
                    p=((ep-sl)/ep)*100; cap*=(1+(p*alav)/100); pa=abs(p/100)+fee
                    trades.append({"Data":he,"Direção":"Short","Entrada":ep,"Saída":sl,"Resultado":"Stop","P&L (%)":p,"Capital":cap})
                    l+=1; w=0; d=1; ref=sl; ep=sl
                    if tipo_est=="Normal (Alvo Fixo)": f=step+fee
                    elif tipo_est=="Recuperação Cirúrgica (Perda Anterior + Taxas + Lucro)": f=pa+fee+fee+step
                    else: f=pa+fee+fee
                    tp=ep*(1+f); sl=ep*(1-step-fee); he=ts
                elif l<=tp:
                    p=((ep-tp)/ep)*100; cap*=(1+(p*alav)/100); pa=0.0
                    trades.append({"Data":he,"Direção":"Short","Entrada":ep,"Saída":tp,"Resultado":"Alvo","P&L (%)":p,"Capital":cap})
                    w+=1; l=0; ref=tp; ep=tp; f=step+fee; tp=ep*(1-f); sl=ep*(1+step+fee); he=ts
            if l>=max_losses:
                blk=True; bd+=1
                trades.append({"Data":ts,"Direção":"-","Entrada":0,"Saída":0,"Resultado":"BLOQUEIO","P&L (%)":0,"Capital":cap})
                w=0; l=0
            if w>=max_wins:
                blk=True; bv+=1
                trades.append({"Data":ts,"Direção":"-","Entrada":0,"Saída":0,"Resultado":"BLOQUEIO","P&L (%)":0,"Capital":cap})
                w=0; l=0
        return trades, cap, bd, bv

    def simular_rompimento_ema_c(df, emp, sp, am, fee, mw, ml, banca, alav):
        trades=[]; cap=banca; df=df.copy(); df['ema']=df['close'].ewm(span=emp,adjust=False).mean()
        ac=False; av=False; mx=None; mn=None; d=0; ep=None; tp=None; sl=None
        w=0; l=0; blk=False; he=None; bd=0; bv=0; ap=sp*am
        for i,row in df.iterrows():
            if i==0: continue
            h,l,c,ts,e = row['high'],row['low'],row['close'],row['timestamp'],row['ema']
            pc=df['close'].iloc[i-1]; pe=df['ema'].iloc[i-1]
            if blk: continue
            if pc<=pe and c>e: ac=True; av=False; mx=h
            elif pc>=pe and c<e: av=True; ac=False; mn=l
            if d==0:
                if ac and mx and h>mx: d=1; ep=mx; sl=ep*(1-sp); tp=ep*(1+ap); he=ts; ac=False
                elif av and mn and l<mn: d=-1; ep=mn; sl=ep*(1+sp); tp=ep*(1-ap); he=ts; av=False
            elif d==1:
                if l<=sl:
                    p=((sl-ep)/ep)*100-(fee*100); cap*=(1+(p*alav)/100)
                    trades.append({"Data":he,"Direção":"Long","Entrada":ep,"Saída":sl,"Resultado":"Stop","P&L (%)":p,"Capital":cap})
                    l+=1; w=0; d=0
                elif h>=tp:
                    p=((tp-ep)/ep)*100-(fee*100); cap*=(1+(p*alav)/100)
                    trades.append({"Data":he,"Direção":"Long","Entrada":ep,"Saída":tp,"Resultado":"Alvo","P&L (%)":p,"Capital":cap})
                    w+=1; l=0; d=0
            elif d==-1:
                if h>=sl:
                    p=((ep-sl)/ep)*100-(fee*100); cap*=(1+(p*alav)/100)
                    trades.append({"Data":he,"Direção":"Short","Entrada":ep,"Saída":sl,"Resultado":"Stop","P&L (%)":p,"Capital":cap})
                    l+=1; w=0; d=0
                elif l<=tp:
                    p=((ep-tp)/ep)*100-(fee*100); cap*=(1+(p*alav)/100)
                    trades.append({"Data":he,"Direção":"Short","Entrada":ep,"Saída":tp,"Resultado":"Alvo","P&L (%)":p,"Capital":cap})
                    w+=1; l=0; d=0
            if l>=ml:
                blk=True; bd+=1
                trades.append({"Data":ts,"Direção":"-","Entrada":0,"Saída":0,"Resultado":"BLOQUEIO","P&L (%)":0,"Capital":cap})
                w=0; l=0
            if w>=mw:
                blk=True; bv+=1
                trades.append({"Data":ts,"Direção":"-","Entrada":0,"Saída":0,"Resultado":"BLOQUEIO","P&L (%)":0,"Capital":cap})
                w=0; l=0
        return trades, cap, bd, bv

    def mostrar_resultados_c(df, trades, cap_f, banca, bd, bv, ml, mw, tipo_est):
        if not trades: st.warning("Nenhum trade gerado."); return
        dft = pd.DataFrame(trades)
        if bd>0 or bv>0:
            st.markdown("---")
            c1,c2 = st.columns(2)
            (c1.error(f"🚨 Bloqueios por DERROTAS: **{bd}** (limite {ml})") if bd>0 else c1.success("✅ Sem bloqueio por derrotas."))
            (c2.success(f"🎉 Bloqueios por VITÓRIAS: **{bv}** (meta {mw})") if bv>0 else c2.info("ℹ️ Sem bloqueio por vitórias."))
            st.markdown("---")
        dn = dft[dft['Resultado']!='BLOQUEIO']
        t=len(dn); v=len(dn[dn['Resultado']=='Alvo']); r=len(dn[dn['Resultado']=='Stop'])
        tx=(v/t*100) if t>0 else 0; lc=((cap_f-banca)/banca)*100
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        c1.metric("Total",t); c2.metric("Vencedores",v); c3.metric("Perdedores",r)
        c4.metric("Taxa Acerto",f"{tx:.1f}%"); c5.metric("Lucro",f"{lc:+.2f}%"); c6.metric("Capital",f"${cap_f:.2f}")
        st.subheader("📈 Curva de Capital")
        f1=go.Figure(); f1.add_trace(go.Scatter(x=dft['Data'],y=dft['Capital'],mode='lines+markers',line=dict(color='#00ff88',width=2)))
        f1.update_layout(template="plotly_dark",height=400); st.plotly_chart(f1,use_container_width=True)
        st.subheader("📉 Preço com Entradas e Saídas")
        f2=go.Figure(data=[go.Candlestick(x=df['timestamp'],open=df['open'],high=df['high'],low=df['low'],close=df['close'])])
        if tipo_est=="Rompimento EMA":
            dp=df.copy(); dp['ema']=dp['close'].ewm(span=ema_periodo_c,adjust=False).mean()
            f2.add_trace(go.Scatter(x=dp['timestamp'],y=dp['ema'],mode='lines',name='EMA',line=dict(color='yellow',width=2)))
        L=dn[dn['Direção']=='Long']; S=dn[dn['Direção']=='Short']
        f2.add_trace(go.Scatter(x=L['Data'],y=L['Entrada'],mode='markers',name='Compra',marker=dict(color='#00ff88',size=10,symbol='triangle-up')))
        f2.add_trace(go.Scatter(x=S['Data'],y=S['Entrada'],mode='markers',name='Venda',marker=dict(color='#ff4444',size=10,symbol='triangle-down')))
        f2.update_layout(template="plotly_dark",height=500,xaxis_rangeslider_visible=False); st.plotly_chart(f2,use_container_width=True)
        st.subheader("📋 Histórico de Operações"); st.dataframe(dft,use_container_width=True)

    st.header("📈 Bot Cripto - Yahoo Finance")
    if modo_c=="Backtest (Passado)":
        st.subheader(f"📊 Backtest {symbol_c} | {timeframe_c} | {tipo_estrategia_c}")
        if st.button("🚀 Rodar Backtest Cripto",type="primary",key="c_btn"):
            with st.spinner("Baixando dados..."):
                df=baixar_dados_yahoo(symbol_c,timeframe_c,str(data_inicio_c),str(data_fim_c))
                if not df.empty:
                    if tipo_estrategia_c=="Rompimento EMA":
                        trades,cf,bd,bv=simular_rompimento_ema_c(df,ema_periodo_c,ema_stop_pct_c,ema_alvo_mult_c,fee_c,max_wins_c,max_losses_c,banca_inicial_c,alavancagem_c)
                    else:
                        trades,cf,bd,bv=simular_escada_c(df,step_c,fee_c,max_wins_c,max_losses_c,tipo_estrategia_c,banca_inicial_c,alavancagem_c)
                    mostrar_resultados_c(df,trades,cf,banca_inicial_c,bd,bv,max_losses_c,max_wins_c,tipo_estrategia_c)
    if modo_c=="Live/Demo (Tempo Real)":
        st.info("⚠️ Modo Live/Demo indisponível.")

# ========================================================================== #
# ============================== BOT DERIV ================================= #
# ========================================================================== #
else:
    st.sidebar.header("⚙️ Configurações Deriv")
    modo_d = st.sidebar.selectbox("Modo de Operação", ["Backtest (Passado)", "Operação Demo (Tempo Real)"], key="d_modo")

    st.sidebar.subheader("🔑 Credenciais da API Deriv")
    deriv_app_id = st.sidebar.text_input("App ID da Deriv", "1089", key="d_appid")
    deriv_token = st.sidebar.text_input("API Token (Demo)", type="password", key="d_token")

    st.sidebar.subheader("📊 Mercado")
    symbol_d = st.sidebar.selectbox("Índice Sintético", ["R_10","R_25","R_50","R_75","R_100"], index=3, key="d_symbol")

    # --- TIMEFRAME (escolha do tempo gráfico) ---
    granularity_opts = {"1 minuto":60,"2 minutos":120,"5 minutos":300,"15 minutos":900,"30 minutos":1800,"1 hora":3600,"4 horas":14400,"1 dia":86400}
    gran_nome_d = st.sidebar.selectbox("⏱️ Timeframe (Tempo Gráfico)", list(granularity_opts.keys()), index=2, key="d_tf")
    granularity_d = granularity_opts[gran_nome_d]

    st.sidebar.subheader("🎯 Estratégia")
    tipo_estrategia_d = st.sidebar.radio("Escolha a estratégia:", ["Rompimento EMA","Rompimento Vela com Tendência (Slope)"], key="d_estrategia")

    if tipo_estrategia_d=="Rompimento EMA":
        ema_periodo_d = st.sidebar.number_input("Período da EMA", min_value=2, max_value=500, value=21, key="d_ema")
        ema_stop_pct_d = st.sidebar.number_input("Stop Loss (%)", min_value=0.01, max_value=10.0, value=1.0, step=0.1, key="d_ema_stop") / 100
        ema_alvo_mult_d = st.sidebar.number_input("Multiplicador do Alvo (x Stop)", min_value=0.5, max_value=50.0, value=2.5, step=0.1, key="d_ema_mult")
        slope_periodo_d=0; slope_threshold_d=0; stop_pontos_d=0; alvo_pontos_d=0
    else:
        slope_periodo_d = st.sidebar.number_input("Período do Slope (candles)", min_value=5, max_value=200, value=30, key="d_slope_p")
        slope_threshold_d = st.sidebar.number_input("Força Mínima da Tendência (%)", min_value=0.01, max_value=5.0, value=0.10, step=0.01, key="d_slope_t")
        stop_pontos_d = st.sidebar.number_input("Stop Loss (pontos)", value=30.0, step=1.0, key="d_stop_pts")
        alvo_pontos_d = st.sidebar.number_input("Take Profit (pontos)", value=500.0, step=10.0, key="d_alvo_pts")
        ema_periodo_d=0; ema_stop_pct_d=0; ema_alvo_mult_d=0

    st.sidebar.subheader("💰 Banca e Risco")
    banca_inicial_d = st.sidebar.number_input("Banca Inicial (USD)", value=1000.0, step=100.0, key="d_banca")
    stake_d = st.sidebar.number_input("Stake por Operação (USD)", value=2.0, step=0.5, key="d_stake")
    multiplicador_d = st.sidebar.number_input("Multiplicador (x)", min_value=1, max_value=2000, value=100, step=10, key="d_mult")

    st.sidebar.subheader("🔒 Limites de Segurança")
    max_derrotas_d = st.sidebar.number_input("Máx. Derrotas Seguidas", min_value=1, max_value=20, value=5, key="d_max_l")
    max_vitorias_d = st.sidebar.number_input("Máx. Vitórias Seguidas", min_value=1, max_value=50, value=20, key="d_max_w")

    if modo_d=="Backtest (Passado)":
        st.sidebar.subheader("📅 Período do Backtest")
        data_inicio_d = st.sidebar.date_input("Data de Início", datetime.now()-timedelta(days=7), key="d_data_i")
        data_fim_d = st.sidebar.date_input("Data de Fim", datetime.now(), key="d_data_f")

    async def obter_velas(app_id, symbol, gran, count, end_t):
        uri=f"wss://ws.derivws.com/websockets/v3?app_id={app_id}"
        try:
            async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as ws:
                req={"ticks_history":symbol,"adjust_start_time":1,"count":count,"end":end_t,"granularity":gran,"style":"candles"}
                await ws.send(json.dumps(req)); res=await ws.recv(); data=json.loads(res)
                if 'error' in data: return pd.DataFrame(), data['error']['message']
                c=data.get('candles',[])
                if not c: return pd.DataFrame(), "Sem dados"
                df=pd.DataFrame(c); df['timestamp']=pd.to_datetime(df['epoch'],unit='s')
                df=df.rename(columns={'open':'open','high':'high','low':'low','close':'close'})
                df=df[['timestamp','open','high','low','close']]
                df=df.astype({'open':float,'high':float,'low':float,'close':float})
                return df, None
        except Exception as e: return pd.DataFrame(), str(e)

    def simular_ema_d(df, emp, sp, am, banca, stake, mult, ml, mw):
        if df.empty or len(df)<emp+20: return None,None,None,None,0,0
        df=df.copy(); df['ema']=df['close'].ewm(span=emp,adjust=False).mean()
        cap=banca; pos=None; ep=None; spz=None; tpz=None
        ac=False; av=False; mx=None; mn=None; w=0; l=0; trades=[]; blk=False; he=None; bd=0; bv=0; ap=sp*am
        for i in range(1,len(df)):
            row=df.iloc[i]; prev=df.iloc[i-1]
            h,l,c = row['high'],row['low'],row['close']; ts=row['timestamp']
            ea=row['ema']; ep_=prev['ema']; pc=prev['close']
            if blk: continue
            if pc<=ep_ and c>ea: ac=True; av=False; mx=h
            elif pc>=ep_ and c<ea: av=True; ac=False; mn=l
            if pos is None:
                if ac and mx and h>mx: pos="long"; ep=mx; spz=ep*(1-sp); tpz=ep*(1+ap); he=ts; ac=False
                elif av and mn and l<mn: pos="short"; ep=mn; spz=ep*(1+sp); tpz=ep*(1-ap); he=ts; av=False
            else:
                if pos=="long":
                    if l<=spz:
                        p=((spz-ep)/ep)*100*mult; cap-=stake; l+=1; w=0
                        trades.append({"Data":he,"Direção":"Long","Entrada":round(ep,2),"Saída":round(spz,2),"Resultado":"Stop","P&L (%)":round(p,3),"Capital":round(cap,2)})
                        pos=None
                    elif h>=tpz:
                        p=((tpz-ep)/ep)*100*mult; cap+=stake*(p/100); w+=1; l=0
                        trades.append({"Data":he,"Direção":"Long","Entrada":round(ep,2),"Saída":round(tpz,2),"Resultado":"Alvo","P&L (%)":round(p,3),"Capital":round(cap,2)})
                        pos=None
                elif pos=="short":
                    if h>=spz:
                        p=((ep-spz)/ep)*100*mult; cap-=stake; l+=1; w=0
                        trades.append({"Data":he,"Direção":"Short","Entrada":round(ep,2),"Saída":round(spz,2),"Resultado":"Stop","P&L (%)":-round(p,3),"Capital":round(cap,2)})
                        pos=None
                    elif l<=tpz:
                        p=((ep-tpz)/ep)*100*mult; cap+=stake*(p/100); w+=1; l=0
                        trades.append({"Data":he,"Direção":"Short","Entrada":round(ep,2),"Saída":round(tpz,2),"Resultado":"Alvo","P&L (%)":round(p,3),"Capital":round(cap,2)})
                        pos=None
            if l>=ml:
                blk=True; bd+=1
                trades.append({"Data":ts,"Direção":"-","Entrada":0,"Saída":0,"Resultado":"BLOQUEIO","P&L (%)":0,"Capital":round(cap,2)})
                w=0; l=0
            if w>=mw:
                blk=True; bv+=1
                trades.append({"Data":ts,"Direção":"-","Entrada":0,"Saída":0,"Resultado":"BLOQUEIO","P&L (%)":0,"Capital":round(cap,2)})
                w=0; l=0
        return trades,cap,blk,df,bd,bv

    def simular_vela_d(df, sp_p, sp_t, stop_pts, alvo_pts, banca, stake, mult, ml, mw):
        if df.empty or len(df)<sp_p+20: return None,None,None,None,0,0
        df=df.copy(); df['slope']=((df['close']-df['close'].shift(sp_p))/df['close'].shift(sp_p))*100
        cap=banca; pos=None; ep=None; spz=None; tpz=None; linha=None; tipo=None
        w=0; l=0; trades=[]; blk=False; tend=0; he=None; bd=0; bv=0
        for i in range(sp_p+1,len(df)):
            row=df.iloc[i]; prev=df.iloc[i-1]
            h,l,c,o = row['high'],row['low'],row['close'],row['open']; ts=row['timestamp']; sl=row['slope']
            if pd.isna(sl) or blk: continue
            if sl>=sp_t: tend=1
            elif sl<=-sp_t: tend=-1
            else: tend=0
            if pos is None:
                if tend==0: continue
                if prev['close']>prev['open']: linha=prev['high']; tipo="topo"
                else: linha=prev['low']; tipo="fundo"
                if tipo=="topo" and c>linha and tend==1: pos="long"; ep=c; spz=ep-stop_pts; tpz=ep+alvo_pts; he=ts
                elif tipo=="fundo" and c<linha and tend==-1: pos="short"; ep=c; spz=ep+stop_pts; tpz=ep-alvo_pts; he=ts
            else:
                if pos=="long":
                    if l<=spz:
                        p=((spz-ep)/ep)*100*mult; cap-=stake; l+=1; w=0
                        trades.append({"Data":he,"Direção":"Long","Entrada":round(ep,2),"Saída":round(spz,2),"Resultado":"Stop","Slope (%)":round(sl,4),"P&L (%)":round(p,3),"Capital":round(cap,2)})
                        pos=None
                    elif h>=tpz:
                        p=((tpz-ep)/ep)*100*mult; cap+=stake*(p/100); w+=1; l=0
                        trades.append({"Data":he,"Direção":"Long","Entrada":round(ep,2),"Saída":round(tpz,2),"Resultado":"Alvo","Slope (%)":round(sl,4),"P&L (%)":round(p,3),"Capital":round(cap,2)})
                        pos=None
                elif pos=="short":
                    if h>=spz:
                        p=((ep-spz)/ep)*100*mult; cap-=stake; l+=1; w=0
                        trades.append({"Data":he,"Direção":"Short","Entrada":round(ep,2),"Saída":round(spz,2),"Resultado":"Stop","Slope (%)":round(sl,4),"P&L (%)":-round(p,3),"Capital":round(cap,2)})
                        pos=None
                    elif l<=tpz:
                        p=((ep-tpz)/ep)*100*mult; cap+=stake*(p/100); w+=1; l=0
                        trades.append({"Data":he,"Direção":"Short","Entrada":round(ep,2),"Saída":round(tpz,2),"Resultado":"Alvo","Slope (%)":round(sl,4),"P&L (%)":round(p,3),"Capital":round(cap,2)})
                        pos=None
            if l>=ml:
                blk=True; bd+=1
                trades.append({"Data":ts,"Direção":"-","Entrada":0,"Saída":0,"Resultado":"BLOQUEIO","P&L (%)":0,"Capital":round(cap,2)})
                w=0; l=0
            if w>=mw:
                blk=True; bv+=1
                trades.append({"Data":ts,"Direção":"-","Entrada":0,"Saída":0,"Resultado":"BLOQUEIO","P&L (%)":0,"Capital":round(cap,2)})
                w=0; l=0
        return trades,cap,blk,df,bd,bv

    st.header("📊 Bot Deriv - Índices Sintéticos")
    if modo_d=="Backtest (Passado)":
        st.subheader(f"📊 Backtest {symbol_d} | {gran_nome_d} | {tipo_estrategia_d}")
        if st.button("🚀 Rodar Backtest Deriv",type="primary",key="d_btn"):
            with st.spinner("Baixando dados da Deriv..."):
                se=int(pd.Timestamp(data_inicio_d).timestamp()); ee=int(pd.Timestamp(data_fim_d).timestamp())
                cnt=min(5000,int((ee-se)/granularity_d))
                if cnt<=0: st.error("Período inválido.")
                else:
                    df,erro = asyncio.run(obter_velas(deriv_app_id,symbol_d,granularity_d,cnt,ee))
                    if erro: st.error(f"Erro: {erro}")
                    elif not df.empty:
                        if tipo_estrategia_d=="Rompimento EMA":
                            trades,cf,blk,dfp,bd,bv = simular_ema_d(df,ema_periodo_d,ema_stop_pct_d,ema_alvo_mult_d,banca_inicial_d,stake_d,multiplicador_d,max_derrotas_d,max_vitorias_d)
                        else:
                            trades,cf,blk,dfp,bd,bv = simular_vela_d(df,slope_periodo_d,slope_threshold_d,stop_pontos_d,alvo_pontos_d,banca_inicial_d,stake_d,multiplicador_d,max_derrotas_d,max_vitorias_d)
                        if trades:
                            dft=pd.DataFrame(trades)
                            # --- PAINEL DE AVISOS DE BLOQUEIO ---
                            if bd>0 or bv>0:
                                st.markdown("---")
                                c1,c2=st.columns(2)
                                (c1.error(f"🚨 Bloqueios por DERROTAS: **{bd}** (limite {max_derrotas_d})") if bd>0 else c1.success("✅ Sem bloqueio por derrotas."))
                                (c2.success(f"🎉 Bloqueios por VITÓRIAS: **{bv}** (meta {max_vitorias_d})") if bv>0 else c2.info("ℹ️ Sem bloqueio por vitórias."))
                                st.markdown("---")
                            dn=dft[dft['Resultado']!='BLOQUEIO']
                            t=len(dn); v=len(dn[dn['Resultado']=='Alvo']); r=len(dn[dn['Resultado']=='Stop'])
                            tx=(v/t*100) if t>0 else 0; lc=((cf-banca_inicial_d)/banca_inicial_d)*100
                            c1,c2,c3,c4,c5,c6=st.columns(6)
                            c1.metric("Total",t); c2.metric("Vencedores",v); c3.metric("Perdedores",r)
                            c4.metric("Taxa Acerto",f"{tx:.1f}%"); c5.metric("Lucro",f"{lc:+.2f}%"); c6.metric("Capital",f"${cf:.2f}")
                            if blk: st.warning("⚠️ O bot foi BLOQUEADO por atingir um limite.")
                            st.subheader("📉 Preço com Entradas e Saídas")
                            f2=go.Figure(data=[go.Candlestick(x=dfp['timestamp'],open=dfp['open'],high=dfp['high'],low=dfp['low'],close=dfp['close'])])
                            if tipo_estrategia_d=="Rompimento EMA":
                                f2.add_trace(go.Scatter(x=dfp['timestamp'],y=dfp['ema'],mode='lines',name='EMA',line=dict(color='yellow',width=2)))
                            L=dn[dn['Direção']=='Long']; S=dn[dn['Direção']=='Short']
                            f2.add_trace(go.Scatter(x=L['Data'],y=L['Entrada'],mode='markers',name='Compra',marker=dict(color='#00ff88',size=10,symbol='triangle-up')))
                            f2.add_trace(go.Scatter(x=S['Data'],y=S['Entrada'],mode='markers',name='Venda',marker=dict(color='#ff4444',size=10,symbol='triangle-down')))
                            f2.update_layout(template="plotly_dark",height=500,xaxis_rangeslider_visible=False); st.plotly_chart(f2,use_container_width=True)
                            if tipo_estrategia_d=="Rompimento Vela com Tendência (Slope)":
                                st.subheader("📊 Slope (Força da Tendência em %)")
                                f3=go.Figure()
                                f3.add_trace(go.Scatter(x=dfp['timestamp'],y=dfp['slope'],mode='lines',name='Slope (%)',line=dict(color='#00ccff',width=2)))
                                f3.add_hline(y=slope_threshold_d,line_dash="dash",line_color="green")
                                f3.add_hline(y=-slope_threshold_d,line_dash="dash",line_color="red")
                                f3.update_layout(template="plotly_dark",height=300); st.plotly_chart(f3,use_container_width=True)
                            st.subheader("📈 Curva de Capital")
                            f4=go.Figure(); f4.add_trace(go.Scatter(x=dft['Data'],y=dft['Capital'],mode='lines+markers',line=dict(color='#00ff88',width=2)))
                            f4.update_layout(template="plotly_dark",height=400); st.plotly_chart(f4,use_container_width=True)
                            st.subheader("📋 Histórico de Operações"); st.dataframe(dft,use_container_width=True)
                        else:
                            st.warning("Nenhum trade gerado.")
                    else:
                        st.error("Não foi possível obter dados da Deriv.")
    else:
        if not deriv_token: st.info("Insira o API Token da Deriv (conta Demo) no menu lateral.")
        else: st.warning("⚠️ Modo de operação em tempo real em desenvolvimento. Use o Backtest.")

st.sidebar.markdown("---")
st.sidebar.caption("Bot Multi-Mercados v1.1")
.
