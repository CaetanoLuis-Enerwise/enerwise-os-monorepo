import requests
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- CONFIGURAÇÃO VISUAL DEEP TECH (DARK MODE) ---
plt.style.use('dark_background')
COLOR_BG = '#0b0c10'
COLOR_NET_LOAD = '#45a29e'    # Ciano (Energia Líquida)
COLOR_SOLAR = '#f9d71c'       # Amarelo (Solar)
COLOR_CONSUMPTION = '#c5c6c7' # Cinzento (Consumo Bruto)
COLOR_ZERO_LINE = '#666666'   # Linha de Zero
COLOR_DECISION_BOX = '#1f2833'

def get_prediction():
    url = "http://127.0.0.1:8000/predict"
    
    # Simulação de um dia com perfil "Duck Curve" (Muito sol à tarde)
    # Lista com 24h de dados recentes para alimentar a IA
    # (Na vida real, isto viria do teu ficheiro CSV recente)
    simulated_history = [
        250, 240, 230, 220, 225, 240, # 00-06h (Madrugada)
        300, 450, 550, 600, 650, 620, # 06-12h (Manhã)
        600, 580, 550, 500, 550, 650, # 12-18h (Tarde)
        800, 850, 800, 700, 500, 400  # 18-24h (Noite - Pico)
    ]
    
    payload = {
        "historical_data": simulated_history,
        "horizon": 24
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Erro de Conexão: {e}")
        print("Dica: Verifica se o servidor está a correr (python -m uvicorn app.main:app --reload)")
        return None

def plot_dashboard(api_response):
    data = api_response['data']
    meta = api_response['meta']
    
    # Extrair vetores
    net_load = data['net_load_forecast']
    solar = data['solar_forecast']
    consumption = data['consumption_forecast']
    
    # Criar Timestamps Fictícios para o Eixo X (próximas 24h)
    start_time = datetime.now()
    timestamps = [start_time + timedelta(hours=i) for i in range(len(net_load))]
    
    # --- CRIAÇÃO DO GRÁFICO ---
    fig, ax = plt.subplots(figsize=(14, 8))
    fig.patch.set_facecolor(COLOR_BG)
    ax.set_facecolor(COLOR_BG)
    
    # 1. Área Solar (Fundo)
    # Mostra a energia "grátis" gerada
    ax.fill_between(timestamps, 0, solar, color=COLOR_SOLAR, alpha=0.2, label='Produção Solar (PV)')
    ax.plot(timestamps, solar, color=COLOR_SOLAR, linestyle=':', linewidth=1)

    # 2. Linha de Consumo (Referência)
    ax.plot(timestamps, consumption, color=COLOR_CONSUMPTION, linestyle='--', alpha=0.6, label='Consumo Bruto')

    # 3. Linha Principal (Net Load) - O que a bateria vê
    ax.plot(timestamps, net_load, color=COLOR_NET_LOAD, linewidth=3, marker='o', markersize=4, label='Net Load (Bateria)')
    
    # Destacar zona de carregamento (Net Load Negativo = Excedente)
    # Se a linha azul for abaixo de zero, pintamos de verde
    ax.fill_between(timestamps, net_load, 0, where=(np.array(net_load) < 0), 
                    color='#00ff00', alpha=0.3, interpolate=True, label='Excedente (Carregar Bateria)')

    # 4. Linha Zero (Referência Importante)
    ax.axhline(0, color=COLOR_ZERO_LINE, linewidth=1.5)

    # --- DECORAÇÃO ---
    ax.set_title(f"ENERWISE TWIN-ENGINE | Gestão Híbrida em Tempo Real", fontsize=16, fontweight='bold', color='white', pad=20)
    ax.set_ylabel("Potência (kW)", fontsize=12, color='white')
    ax.grid(True, linestyle=':', alpha=0.15, color='white')
    
    # Formatação de Datas no Eixo X
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.xticks(rotation=45)
    
    # Cores dos Eixos
    ax.tick_params(colors='white')
    for spine in ax.spines.values():
        spine.set_edgecolor('#333333')

    # --- CAIXA DE DECISÃO INTELIGENTE ---
    rec = meta['recommendation'].upper()
    volatility = meta['volatility']
    reason = meta.get('reason', 'N/A')
    
    # Cor da caixa muda conforme a decisão
    if "CHARGE" in rec:
        box_color = "#00ff00" # Verde
    elif "DISCHARGE" in rec:
        box_color = "#ff0055" # Vermelho
    else:
        box_color = "#00aaff" # Azul (Hold)

    info_text = (
        f"🤖 AGENTE DE DECISÃO\n"
        f"-------------------\n"
        f"AÇÃO:  {rec}\n"
        f"VOLAT: {volatility:.3f}\n\n"
        f"MOTIVO:\n{reason}"
    )
    
    props = dict(boxstyle='round,pad=1', facecolor=COLOR_BG, alpha=0.9, edgecolor=box_color, linewidth=2)
    ax.text(0.02, 0.95, info_text, transform=ax.transAxes, fontsize=10,
            verticalalignment='top', bbox=props, color='white', family='monospace')

    # Legenda
    ax.legend(loc='upper right', facecolor=COLOR_BG, edgecolor='white', labelcolor='white')
    
    # Guardar e Mostrar
    print("📸 A renderizar gráfico de alta fidelidade...")
    plt.tight_layout()
    plt.savefig("enerwise_twin_dashboard.png", dpi=300, facecolor=COLOR_BG)
    print("✅ Gráfico gerado: 'enerwise_twin_dashboard.png'")
    plt.show()

if __name__ == "__main__":
    print("📡 A ligar ao Twin Engine...")
    result = get_prediction()
    if result:
        plot_dashboard(result)