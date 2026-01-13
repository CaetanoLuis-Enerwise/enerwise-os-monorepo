import pandas as pd
import numpy as np
from pathlib import Path
import os
import sys

# --- CONFIGURAÇÃO PROFISSIONAL (CAMINHOS RELATIVOS) ---
# O código descobre onde está a correr (Seja no teu PC ou na Cloud)
BASE_DIR = Path.cwd()

# Define as pastas relativas à raiz do projeto
DIR_CONSUMO = BASE_DIR / "Consumo"
DIR_PV = BASE_DIR / "PV"
OUTPUT_FILE = BASE_DIR / "app/data/dataset_enerwise_master.csv"

# Listas de ficheiros alvo (apenas os nomes, sem o C:\Users...)
TARGET_FILES_CONSUMO = ["Consumo_fase_a.txt", "Consumo_fase_b.txt", "Consumo_fase_c.txt"]
TARGET_FILES_PV = ["Fotovoltaico_fase_a.txt", "Fotovoltaico_fase_b.txt", "Fotovoltaico_fase_c.txt"]

class TeseLoader:
    """
    Processador Industrial Agnostic-Path.
    Funciona em Windows, Linux e Mac sem alterações.
    """
    
    @staticmethod
    def read_phase_file(file_path: Path) -> pd.DataFrame:
        if not file_path.exists():
            print(f"❌ ERRO CRÍTICO: Ficheiro não encontrado: {file_path.name}")
            return None

        try:
            # Leitura robusta
            df = pd.read_csv(file_path, sep=None, engine='python', dtype=str)
            
            # Limpeza e Timestamp
            timestamp_col = df.columns[0]
            df[timestamp_col] = pd.to_datetime(df[timestamp_col], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[timestamp_col]).set_index(timestamp_col)
            
            # Limpeza Numérica
            for col in df.columns:
                df[col] = pd.to_numeric(df[col].str.replace(',', '.', regex=False), errors='coerce')
            
            # Agregação (Soma dos Nós)
            df_total = df.sum(axis=1, skipna=True).to_frame("value")
            
            # Normalização 30min
            df_total = df_total.resample("30min").mean().interpolate(method='time').fillna(0)
            
            return df_total
        except Exception as e:
            print(f"⚠️ Erro em {file_path.name}: {e}")
            return None

    @staticmethod
    def aggregate_specific_files(directory: Path, file_names: list, prefix: str) -> pd.DataFrame:
        print(f"🔄 A processar {prefix.upper()} em: {directory}")
        dfs = []
        
        for fname in file_names:
            full_path = directory / fname
            print(f"   -> Lendo: {fname}")
            df = TeseLoader.read_phase_file(full_path)
            if df is not None:
                dfs.append(df)
        
        if not dfs:
            return pd.DataFrame()

        # Soma Trifásica
        total = pd.concat(dfs, axis=1).sum(axis=1).to_frame(f"total_{prefix}")
        return total

def gerar_dataset_mestre():
    print(f"🚀 ENERWISE DATA ENGINE | Root: {BASE_DIR}")
    
    # Validação de Pastas
    if not DIR_CONSUMO.exists() or not DIR_PV.exists():
        print("❌ ERRO: Pastas 'Consumo' ou 'PV' não encontradas na raiz do projeto.")
        return

    # 1. Processar
    df_consumo = TeseLoader.aggregate_specific_files(DIR_CONSUMO, TARGET_FILES_CONSUMO, "consumo")
    df_pv = TeseLoader.aggregate_specific_files(DIR_PV, TARGET_FILES_PV, "pv")
    
    if df_consumo.empty:
        print("❌ FALHA: Consumo vazio.")
        return
    
    # 2. Cruzar e Calcular
    if df_pv.empty:
        df_pv = pd.DataFrame(0, index=df_consumo.index, columns=['total_pv'])

    print("⚡ Cruzando dados (Load vs Solar)...")
    df_final = df_consumo.join(df_pv, how='inner')
    df_final['consumo_liquido_kw'] = df_final['total_consumo'] - df_final['total_pv']
    
    # 3. Guardar
    df_final = df_final.reset_index().rename(columns={'index': 'timestamp'})
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df_final.to_csv(OUTPUT_FILE, index=False)
    
    print(f"\n✅ DATASET MESTRE ATUALIZADO: {OUTPUT_FILE}")
    print(f"📊 Registos: {len(df_final)}")

if __name__ == "__main__":
    gerar_dataset_mestre()