import pandas as pd
import numpy as np
import joblib
import os
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
from app.ml.solar_manager import SolarPhysicsEngine

# CONFIGURAÇÃO
DATA_PATH = "app/data/dataset_enerwise_master.csv"
MODEL_DIR = "assets/models"
os.makedirs(MODEL_DIR, exist_ok=True)

def train_twin_engines():
    print("🚀 A INICIAR TREINO HÍBRIDO (Consumo vs Solar)...")
    
    # 1. Carregar Dados Reais
    if not os.path.exists(DATA_PATH):
        print(f"❌ ERRO: Não encontrei {DATA_PATH}. Corre o processor_tese.py primeiro!")
        return

    df = pd.read_csv(DATA_PATH)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    
    # 2. Engenharia de Features FÍSICA (Solar)
    print("☀️ Calculando Geometria Solar (Clear Sky Model)...")
    physics = SolarPhysicsEngine()
    df = physics.add_solar_features(df)
    
    # 3. Engenharia de Features TEMPORAL (Consumo)
    df['hour'] = df.index.hour
    df['dayofweek'] = df.index.dayofweek
    df['month'] = df.index.month
    
    # Lags (O passado recente explica o futuro)
    # A IA precisa saber quanto foi consumido há 24h e há 1 semana
    for lag in [1, 2, 24, 48, 168]: # 168h = 1 semana
        df[f'lag_load_{lag}'] = df['total_consumo'].shift(lag)
        df[f'lag_pv_{lag}'] = df['total_pv'].shift(lag)
        
    df = df.dropna()
    
    # --- MOTOR 1: PREVISÃO DE CONSUMO (HUMANOS) ---
    print("\n🧠 A Treinar Motor de Consumo (Human Behavior)...")
    features_load = ['hour', 'dayofweek', 'month', 'lag_load_1', 'lag_load_24', 'lag_load_168']
    target_load = 'total_consumo'
    
    X_load = df[features_load]
    y_load = df[target_load]
    
    X_train_l, X_test_l, y_train_l, y_test_l = train_test_split(X_load, y_load, test_size=0.2, shuffle=False)
    
    model_load = GradientBoostingRegressor(n_estimators=100, random_state=42)
    model_load.fit(X_train_l, y_train_l)
    
    p_load = model_load.predict(X_test_l)
    mae_load = mean_absolute_error(y_test_l, p_load)
    print(f"✅ Motor Consumo Treinado. Erro MAE: {mae_load:.2f} kW")
    
    # --- MOTOR 2: PREVISÃO SOLAR (FÍSICA) ---
    print("\n☀️ A Treinar Motor Solar (Physics-Aware)...")
    # Nota: Aqui usamos as features físicas que calculámos (elevation, theoretical_radiation)
    features_pv = ['solar_elevation', 'theoretical_radiation', 'doy_sin', 'lag_pv_1', 'lag_pv_24']
    target_pv = 'total_pv'
    
    X_pv = df[features_pv]
    y_pv = df[target_pv]
    
    X_train_p, X_test_p, y_train_p, y_test_p = train_test_split(X_pv, y_pv, test_size=0.2, shuffle=False)
    
    model_pv = GradientBoostingRegressor(n_estimators=100, random_state=42)
    model_pv.fit(X_train_p, y_train_p)
    
    p_pv = model_pv.predict(X_test_p)
    # Forçar zero à noite (Física!)
    p_pv = np.where(X_test_p['solar_elevation'] <= 0, 0, p_pv)
    p_pv = np.maximum(0, p_pv) # Sem energia negativa
    
    mae_pv = mean_absolute_error(y_test_p, p_pv)
    print(f"✅ Motor Solar Treinado. Erro MAE: {mae_pv:.2f} kW")
    
    # --- GUARDAR TUDO ---
    print("\n💾 A Gravar Motores na pasta assets/models...")
    joblib.dump(model_load, f"{MODEL_DIR}/engine_load_v1.pkl")
    joblib.dump(model_pv, f"{MODEL_DIR}/engine_pv_v1.pkl")
    print("🏁 CONCLUÍDO. O sistema está pronto para inferência.")

if __name__ == "__main__":
    train_twin_engines()