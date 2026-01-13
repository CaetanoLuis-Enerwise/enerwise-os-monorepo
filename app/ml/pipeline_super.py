import numpy as np
import logging
from typing import List, Dict, Any
from datetime import datetime
import math

logger = logging.getLogger("enerwise.ml_pipeline")

class HighFidelityInference:
    def __init__(self, model_path: str = "assets/models/prod_v1.pth"):
        self.model_ready = True # Simulamos que carregou bem
        
    def _engineer_features(self, raw_data: List[float], timestamp: datetime) -> np.ndarray:
        # Aqui entra a física: transformar horas em ciclos (Seno/Cosseno)
        return np.array(raw_data)

    def infer(self, historical_data: List[float], horizon: int = 24, features: Any = None) -> Dict[str, Any]:
        if not historical_data:
            return {"error": "No data"}

        # Simulação de IA Avançada (Physics-Informed)
        last_val = historical_data[-1]
        avg_window = np.mean(historical_data[-12:]) # Média das últimas 12h
        
        forecast_values = []
        confidence_intervals = []
        
        current_time = datetime.now()
        
        for i in range(horizon):
            # Lógica de Micro-Grid: Padrão diário + Inércia
            hour_offset = (current_time.hour + i) % 24
            
            # Perfil de carga típico (pico às 19h)
            profile_factor = 1.0 + 0.4 * math.sin((hour_offset - 6) * math.pi / 12)
            inertia = 0.7 ** (i/5.0)
            
            val = (last_val * inertia) + (avg_window * (1-inertia)) * profile_factor
            forecast_values.append(max(0, val)) 
            
            # Incerteza cresce com o tempo
            uncertainty = 0.05 * val * (1 + 0.1 * i)
            confidence_intervals.append(uncertainty)

        forecast_array = np.array(forecast_values)
        uncertainty_array = np.array(confidence_intervals)
        
        # Análise para Baterias (BMS)
        volatility = np.std(forecast_array) / np.mean(forecast_array)
        
        return {
            "forecast": forecast_array.tolist(),
            "confidence": {
                "upper_bound": (forecast_array + 1.96 * uncertainty_array).tolist(),
                "std_dev": uncertainty_array.tolist()
            },
            "meta": {
                "volatility_index": float(volatility),
                "recommendation": "discharge" if volatility > 0.2 else "hold"
            }
        }

# Instância Global
_pipeline_instance = HighFidelityInference()

def infer_from_series(data: List[float], horizon: int = 24, features: Any = None):
    return _pipeline_instance.infer(data, horizon, features)