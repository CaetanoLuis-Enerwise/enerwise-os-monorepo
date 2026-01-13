import pandas as pd
import numpy as np
import joblib
import os
import sys
from datetime import timedelta
from app.ml.solar_manager import SolarPhysicsEngine

# Caminhos dos modelos treinados
MODEL_DIR = "assets/models"
PATH_LOAD = f"{MODEL_DIR}/engine_load_v1.pkl"
PATH_PV = f"{MODEL_DIR}/engine_pv_v1.pkl"

class HybridPredictor:
    def __init__(self):
        # Carregar os cérebros
        print("🧠 A carregar modelos de IA...")
        if not os.path.exists(PATH_LOAD) or not os.path.exists(PATH_PV):
            raise FileNotFoundError("Modelos não encontrados! Corre o treino primeiro.")
            
        self.model_load = joblib.load(PATH_LOAD)
        self.model_pv = joblib.load(PATH_PV)
        self.physics = SolarPhysicsEngine()
        print("✅ Modelos carregados com sucesso.")

    def predict_next_24h(self, recent_data_df: pd.DataFrame):
        """
        Gera previsão para as próximas 24h usando estratégia recursiva.
        recent_data_df: DataFrame com as últimas 168h (semana) de dados reais.
        """
        # Preparar o buffer de dados (cópia para não estragar o original)
        history = recent_data_df.copy()
        
        # Garantir índice de tempo
        if not isinstance(history.index, pd.DatetimeIndex):
            history['timestamp'] = pd.to_datetime(history['timestamp'])
            history.set_index('timestamp', inplace=True)
            
        future_predictions = []
        
        # Último momento conhecido
        last_timestamp = history.index[-1]
        
        print(f"🔮 A prever o futuro a partir de: {last_timestamp}")

        # LOOP RECURSIVO (Hora a Hora)
        for i in range(1, 25): # Próximas 24 horas
            next_time = last_timestamp + timedelta(hours=i)
            
            # 1. Construir a linha de Features para este momento futuro
            # Criamos um DataFrame temporário só com este timestamp
            row = pd.DataFrame(index=[next_time])
            
            # Features Temporais
            row['hour'] = next_time.hour
            row['dayofweek'] = next_time.dayofweek
            row['month'] = next_time.month
            
            # Features Físicas (Solar) - O nosso motor sabe onde está o sol amanhã!
            row = self.physics.add_solar_features(row)
            
            # Features de Atraso (Lags) - A parte difícil!
            # Temos de ir buscar valores ao 'history' (que inclui previsões anteriores)
            def get_lag(col, hours_back):
                target_time = next_time - timedelta(hours=hours_back)
                # Tenta encontrar no histórico exato
                if target_time in history.index:
                    return history.loc[target_time, col]
                else:
                    # Fallback (pega no mais próximo se falhar)
                    return history.iloc[-1][col]

            # Preencher Lags (igual ao treino)
            for lag in [1, 24, 168]:
                row[f'lag_load_{lag}'] = get_lag('total_consumo', lag)
                row[f'lag_pv_{lag}'] = get_lag('total_pv', lag)
            
            # 2. Previsão: Consumo
            features_load = ['hour', 'dayofweek', 'month', 'lag_load_1', 'lag_load_24', 'lag_load_168']
            pred_load = self.model_load.predict(row[features_load])[0]
            
            # 3. Previsão: Solar
            features_pv = ['solar_elevation', 'theoretical_radiation', 'doy_sin', 'lag_pv_1', 'lag_pv_24']
            pred_pv = self.model_pv.predict(row[features_pv])[0]
            
            # Física: Sem sol negativo e sem sol à noite
            if row['solar_elevation'].values[0] <= 0:
                pred_pv = 0
            pred_pv = max(0, pred_pv)
            
            # 4. Adicionar ao Histórico (para o próximo loop usar como lag)
            # Isto é o que torna o modelo "inteligente" e contínuo
            new_row = pd.DataFrame({
                'total_consumo': [pred_load],
                'total_pv': [pred_pv]
            }, index=[next_time])
            
            # Adiciona ao fim do histórico
            history = pd.concat([history, new_row])
            
            # 5. Guardar resultado
            future_predictions.append({
                'timestamp': next_time.isoformat(),
                'load_kw': round(pred_load, 2),
                'pv_kw': round(pred_pv, 2),
                'net_load_kw': round(pred_load - pred_pv, 2)
            })
            
        return future_predictions

# Instância global
_predictor = None

def get_forecast(historical_data_list):
    """
    Função wrapper para ser chamada pela API.
    Reconstrói um DataFrame a partir da lista simples de floats.
    """
    global _predictor
    if _predictor is None:
        _predictor = HybridPredictor()
        
    # Reconstruir DataFrame com timestamps simulados (Recente)
    # Assumimos que o último dado é "Agora"
    # Precisamos de pelo menos 168 pontos (1 semana) para os lags funcionarem bem
    # Mas se vier menos, o pandas lida com NaNs (o modelo pode reclamar, mas para demo serve)
    
    end_date = pd.Timestamp.now().floor('h')
    dates = pd.date_range(end=end_date, periods=len(historical_data_list), freq='h')
    
    # Assumimos que a lista vem com [Consumo, PV, Consumo, PV...] ou simplificamos
    # Para simplificar neste passo, vamos assumir que a API recebe apenas CONSUMO
    # e nós "estimamos" o PV passado como 0 ou média (limitação do MVP)
    # IDEALMENTE: A API devia receber um JSON complexo.
    
    # HACK PARA DEMO: Vamos assumir que os dados de entrada são só Consumo
    # e geramos PV sintético para o passado para não crachar.
    
    df = pd.DataFrame({
        'total_consumo': historical_data_list,
        'total_pv': [0] * len(historical_data_list) # Placeholder
    }, index=dates)
    
    return _predictor.predict_next_24h(df)