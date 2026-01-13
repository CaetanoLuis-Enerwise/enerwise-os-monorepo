import requests
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
import os
from datetime import datetime

# --- CONFIGURAÇÃO DEEP TECH (DARK MODE) ---
plt.style.use('dark_background')
COLOR_BG = '#0b0c10'
COLOR_NET_LOAD = '#45a29e'    # Ciano (Energia Líquida)
COLOR_SOLAR = '#f9d71c'       # Amarelo (Solar)
COLOR_CONSUMPTION = '#c5c6c7' # Cinzento (Consumo Bruto)
COLOR_ZERO_LINE = '#666666'   # Linha de Zero

# Caminho para o teus dados reais
CSV_PATH = "app/data/dataset_enerwise_master.csv"

def load_real_sample():
    """
    Carrega o dataset mestre e escolhe um dia interessante (com Sol).
    """
    if not os.path.exists(CSV_PATH):
        print(f"❌ ERRO: Não encontrei {CSV_PATH}")
        return None

    print(f"📂 A ler dados reais de: {CSV_PATH}")
    df = pd.read_csv(CSV_PATH)
    
    # Escolher um dia específico de Maio/Junho de 2011 (onde sabemos que há sol)
    # Vamos pegar numa fatia aleatória mas válida
    # Dica: O índice 10000 costuma ser algures em Maio
    start_idx = 10000 
    end_idx = start_idx + 24 # 24 horas
    
    sample = df.iloc[start_idx:end_idx].copy()
    
    # Extrair apenas o consumo para enviar à API
    # (A API vai prever o Solar e o Net Load sozinha)
    consumption_list = sample['total_consumo'].tolist()
    
    print(f"📅 Data da Amostra Real: {sample['timestamp'].iloc[0]}")
    return consumption_list

def get_prediction(real_data):
    url = "http://127.0.0.1:8000/predict"
    
    payload = {
        "historical_data": real_data,
        "horizon": 24
    }
    
    try:
        print("📡 A enviar dados reais para o Cérebro Enerwise...")
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Erro de Conexão: {e}")
        print("Dica: O servidor está ligado? (python -m uvicorn app.main:app --reload)")
        return None

def plot_dashboard(api_response):
    data = api_response['data']
    meta = api_response['meta']
    
    # Extrair vetores devolvidos pela IA
    net_load = data['net_load_forecast']
    solar = data['solar_forecast']
    consumption = data['consumption_forecast']
    
    # Usar a timeline gerada pela API
    timestamps = [datetime.fromisoformat(ts) for ts in data['timeline']]
    
    # --- VISUALIZAÇÃO ---
    fig, ax = plt.subplots(figsize=(14, 8))
    fig.patch.set_facecolor(COLOR_BG)
    ax.set_facecolor(COLOR_BG)
    
    # 1. Área Solar (Fundo)
    ax.fill_between(timestamps, 0, solar, color=COLOR_SOLAR, alpha=0.2, label='Produção Solar (Prevista)')
    ax.plot(timestamps, solar, color=COLOR_SOLAR, linestyle=':', linewidth=1)

    # 2. Consumo Real (Referência)
    ax.plot(timestamps, consumption, color=COLOR_CONSUMPTION, linestyle='--', alpha=0.6, label='Consumo (Humano)')

    # 3. Net Load (Onde a bateria atua)
    ax.plot(timestamps, net_load, color=COLOR_NET_LOAD, linewidth=3, marker='o', markersize=4, label='Net Load (Rede)')
    
    # 4. Zona de Carregamento Inteligente (Verde)
    # Pinta onde o Net Load é negativo (Solar > Consumo)
    ax.fill_between(timestamps, net_load, 0, where=(np.array(net_load) < 0), 
                    color='#00ff00', alpha=0.4, interpolate=True, label='EXCEDENTE: Carregar Bateria')

    ax.axhline(0, color=COLOR_ZERO_LINE, linewidth=1)

    # --- DECISÃO DA IA ---
    rec = meta['recommendation'].upper()
    volat = meta['volatility']
    reason = meta.get('reason', 'Análise complexa efetuada.')
    
    if "CHARGE" in rec:
        box_c = "#00ff00" # Verde
    elif "DISCHARGE" in rec:
        box_c = "#ff0055" # Vermelho
    else:
        box_c = "#00aaff" # Azul

    info_text = (
        f"🤖 ENERWISE AI DECISION\n"
        f"──────────────────────\n"
        f"ESTRATÉGIA: {rec}\n"
        f"VOLATILIDADE: {volat:.3f}\n\n"
        f"DIAGNÓSTICO:\n{reason}"
    )
    
    props = dict(boxstyle='round,pad=1', facecolor=COLOR_BG, alpha=0.9, edgecolor=box_c, linewidth=2)
    ax.text(0.02, 0.95, info_text, transform=ax.transAxes, fontsize=10,
            verticalalignment='top', bbox=props, color='white', family='monospace')

    # Configuração Final
    ax.set_title("ENERWISE OS | Live Twin-Engine Simulation (Real Data)", fontsize=16, fontweight='bold', color='white', pad=20)
    ax.set_ylabel("Potência (kW)", color='white')
    ax.grid(True, linestyle=':', alpha=0.2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.tick_params(colors='white')
    for s in ax.spines.values(): s.set_edgecolor('#333333')
    ax.legend(loc='upper right', facecolor=COLOR_BG, edgecolor='white', labelcolor='white')

    plt.tight_layout()
    output_file = "enerwise_real_data_proof.png"
    plt.savefig(output_file, dpi=300, facecolor=COLOR_BG)
    print(f"✅ GRÁFICO FINAL GERADO: {output_file}")
    plt.show()

if __name__ == "__main__":
    # 1. Carregar Dados
    real_cons = load_real_sample()
    
    # 2. Obter Inteligência
    if real_cons:
        ai_result = get_prediction(real_cons)
        
        # 3. Visualizar Sucesso
        if ai_result:
            plot_dashboard(ai_result)