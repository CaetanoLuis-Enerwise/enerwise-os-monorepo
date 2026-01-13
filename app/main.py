from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
import logging
import numpy as np
from datetime import datetime

# --- IMPORTAÇÃO DO MOTOR HÍBRIDO (CÉREBRO REAL) ---
try:
    from app.ml.inference_hybrid import get_forecast
    ENGINE_STATUS = "online"
except ImportError as e:
    ENGINE_STATUS = f"offline_error_{str(e)}"
    print(f"⚠️ AVISO: Não consegui importar o motor híbrido. Detalhe: {e}")
except Exception as e:
    ENGINE_STATUS = "offline_generic"
    print(f"⚠️ AVISO: Erro ao carregar motor. Tens os modelos treinados na pasta assets? {e}")

# --- CONFIGURAÇÃO DE LOGS ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("enerwise-api")

# --- DEFINIÇÃO DA APP ---
app = FastAPI(
    title="Enerwise Human OS API",
    description="Enterprise-grade AI Engine for Microgrid Management",
    version="2.1.0-cors-enabled"
)

# --- 🔓 CORS (CRUCIAL PARA O FRONTEND FUNCIONAR) ---
# Isto permite que o Lovable ou o Localhost:3000 falem com este servidor
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite TODOS os sites (ideal para desenvolvimento)
    allow_credentials=True,
    allow_methods=["*"],  # Permite POST, GET, OPTIONS, etc.
    allow_headers=["*"],
)

# --- MODELOS DE DADOS (VALIDAÇÃO) ---
class EnergyRequest(BaseModel):
    historical_data: List[float] = Field(
        ..., 
        description="Lista de consumo histórico (kW). Mínimo recomendado: 24h.",
        min_length=1
    )
    horizon: int = Field(
        24, 
        ge=1, le=48, 
        description="Horizonte de previsão em horas."
    )

    @field_validator('historical_data')
    def check_min_length(cls, v):
        if len(v) < 1:
            raise ValueError('A lista de dados não pode estar vazia.')
        return v

# --- ENDPOINTS ---

@app.get("/", tags=["System"])
async def health_check():
    """Verifica se o sistema está operacional."""
    return {
        "status": "active", 
        "engine_mode": ENGINE_STATUS,
        "timestamp": datetime.now().isoformat(),
        "version": "v2.1_ready_for_frontend"
    }

@app.post("/predict", tags=["Intelligence"])
async def generate_prediction(payload: EnergyRequest):
    """
    ENDPOINT PRINCIPAL:
    Recebe dados do Frontend -> Processa no Motor Híbrido -> Devolve Decisão.
    """
    logger.info(f"⚡ Pedido recebido. Pontos de dados: {len(payload.historical_data)}")
    
    # Se o motor não carregou (ex: falta treinar), devolve erro claro
    if "offline" in ENGINE_STATUS:
        raise HTTPException(
            status_code=503, 
            detail=f"Motor de IA indisponível ({ENGINE_STATUS}). Verifica se treinaste os modelos."
        )

    try:
        # 1. CHAMAR O MOTOR (INFERÊNCIA)
        # O get_forecast retorna uma lista de dicionários com {net_load_kw, pv_kw, etc.}
        forecast_result = get_forecast(payload.historical_data)
        
        # 2. PÓS-PROCESSAMENTO DE DADOS
        # Extrair vetores simples para o gráfico
        net_load_values = [item['net_load_kw'] for item in forecast_result]
        solar_values = [item['pv_kw'] for item in forecast_result]
        load_values = [item['load_kw'] for item in forecast_result]
        timeline = [item['timestamp'] for item in forecast_result]
        
        # 3. LÓGICA DE DECISÃO (BMS - BATTERY MANAGEMENT SYSTEM)
        # Detetar Excedente Solar (Net Load Negativo)
        solar_surplus = any(val < 0 for val in net_load_values)
        
        # Calcular Volatilidade
        avg_load = np.mean(np.abs(net_load_values)) + 1e-6
        volatility_index = np.std(net_load_values) / avg_load
        
        # Árvore de Decisão
        recommendation = "hold"
        reason = "Rede estável. Bateria em standby."
        
        if solar_surplus:
            recommendation = "charge_solar"
            reason = "Detetado excedente fotovoltaico. Aproveitar energia solar gratuita."
        elif volatility_index > 0.25:
            recommendation = "discharge"
            reason = f"Alta volatilidade ({volatility_index:.2f}). Descarregar para estabilização (Peak Shaving)."
        
        logger.info(f"✅ Decisão: {recommendation.upper()} | Volatilidade: {volatility_index:.2f}")

        # 4. RESPOSTA FINAL (JSON para o Lovable)
        return {
            "status": "success",
            "meta": {
                "server_time": datetime.now().isoformat(),
                "volatility": round(float(volatility_index), 3),
                "recommendation": recommendation, # "charge_solar", "discharge", "hold"
                "reason": reason
            },
            "data": {
                "net_load_forecast": net_load_values,
                "solar_forecast": solar_values,
                "consumption_forecast": load_values,
                "timeline": timeline
            }
        }

    except Exception as e:
        logger.error(f"❌ Falha no Motor Híbrido: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erro interno no processamento da IA: {str(e)}"
        )