import pandas as pd
import numpy as np
import os
from datetime import datetime
import matplotlib.pyplot as plt
from sklearn.preprocessing import MinMaxScaler

class EnergyDataProcessor:
    def __init__(self, consumo_files, pv_files):
        self.consumo_files = consumo_files
        self.pv_files = pv_files
        self.scaler = MinMaxScaler()
    
    def _load_phase_file(self, file_path):
        """Carrega e processa um único arquivo de fase"""
        try:
            # Carrega o arquivo considerando múltiplos separadores
            df = pd.read_csv(file_path, sep='\t|;|,', engine='python', header=None)
            
            # Extrai timestamp da primeira coluna e valores das demais
            timestamps = df.iloc[:, 0]
            values = df.iloc[:, 1:].apply(pd.to_numeric, errors='coerce')
            
            # Processamento do timestamp
            timestamps = pd.to_datetime(timestamps, infer_datetime_format=True, dayfirst=True, errors='coerce')
            
            # Cria DataFrame final
            phase_df = pd.DataFrame({
                'timestamp': timestamps,
                'total': values.sum(axis=1)  # Soma todos os nós da fase
            }).dropna()
            
            return phase_df.set_index('timestamp')
        
        except Exception as e:
            print(f"Erro ao processar {file_path}: {str(e)}")
            return pd.DataFrame()

    def _aggregate_phases(self, file_paths):
        """Agrega múltiplas fases em um único DataFrame"""
        phase_dfs = []
        
        for file_path in file_paths:
            if os.path.exists(file_path):
                phase_df = self._load_phase_file(file_path)
                if not phase_df.empty:
                    phase_dfs.append(phase_df)
        
        if not phase_dfs:
            return pd.DataFrame()
        
        # Combina todas as fases e soma
        combined = pd.concat(phase_dfs, axis=1)
        combined['total'] = combined.sum(axis=1)
        
        return combined[['total']].sort_index()

    def process_all_data(self, resample_freq='15T'):
        """Processa todos os dados e retorna um DataFrame consolidado"""
        # Processa consumo
        consumo_total = self._aggregate_phases(self.consumo_files)
        if consumo_total.empty:
            raise ValueError("Nenhum dado de consumo válido encontrado")
        consumo_total.columns = ['consumo_total']
        
        # Processa produção PV
        pv_total = self._aggregate_phases(self.pv_files)
        if pv_total.empty:
            pv_total = pd.DataFrame(0, index=consumo_total.index, columns=['producao_pv'])
        else:
            pv_total.columns = ['producao_pv']
        
        # Combina os dados
        full_data = pd.concat([consumo_total, pv_total], axis=1).fillna(0)
        
        # Calcula consumo líquido
        full_data['consumo_liquido'] = full_data['consumo_total'] - full_data['producao_pv']
        
        # Resample para frequência uniforme
        if resample_freq:
            full_data = full_data.resample(resample_freq).mean().fillna(method='ffill')
        
        return full_data

    def prepare_for_forecasting(self, data, target_column='consumo_liquido', n_steps=96, test_size=0.2):
        """Prepara dados para modelos de forecasting"""
        # Normalização
        scaled_data = self.scaler.fit_transform(data[[target_column]])
        
        # Criação de sequências
        X, y = [], []
        for i in range(n_steps, len(scaled_data)):
            X.append(scaled_data[i-n_steps:i, 0])
            y.append(scaled_data[i, 0])
        
        X, y = np.array(X), np.array(y)
        
        # Divisão treino/teste
        split_idx = int(len(X) * (1 - test_size))
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        return X_train, X_test, y_train, y_test

    def plot_results(self, y_true, y_pred, title='Resultados do Modelo'):
        """Visualização dos resultados de previsão"""
        plt.figure(figsize=(15, 6))
        plt.plot(y_true, label='Valor Real', alpha=0.7)
        plt.plot(y_pred, label='Previsão', alpha=0.7)
        plt.title(title)
        plt.xlabel('Tempo')
        plt.ylabel('Consumo Líquido (Normalizado)')
        plt.legend()
        plt.grid()
        plt.show()

# Configuração dos arquivos
consumo_files = ['Consumo_fase_a.txt', 'Consumo_fase_b.txt', 'Consumo_fase_c.txt']
pv_files = ['Fotovoltaico_fase_a.txt', 'Fotovoltaico_fase_b.txt', 'Fotovoltaico_fase_c.txt']

# Processamento dos dados
processor = EnergyDataProcessor(consumo_files, pv_files)
energy_data = processor.process_all_data()

# Salvar dados processados
energy_data.to_csv('energy_dataset_processed.csv')

# Preparação para modelos de forecasting
X_train, X_test, y_train, y_test = processor.prepare_for_forecasting(energy_data)

print(f"Dados processados com shape: {energy_data.shape}")
print(f"Shape dos dados para modelo: X_train{X_train.shape}, y_train{y_train.shape}")