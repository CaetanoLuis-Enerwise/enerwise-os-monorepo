import os
import glob
import time
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import tensorflow as tf
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import (
    mean_absolute_error, mean_squared_error, r2_score,
    mean_absolute_percentage_error
)
from tensorflow.keras.models import Sequential, Model
from tensorflow.keras.layers import (
    LSTM, Dense, Input, MultiHeadAttention,
    LayerNormalization, Dropout, Bidirectional
)
from tensorflow.keras.callbacks import (
    EarlyStopping, ModelCheckpoint,
    ReduceLROnPlateau
)
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.losses import Huber
from prophet import Prophet
import logging
from typing import Tuple, Dict, Optional
import warnings

# Configurações iniciais
warnings.filterwarnings("ignore")
pd.set_option('display.max_columns', None)
sns.set(style='whitegrid')

class Config:
    DIR_CONSUMO = r"C:\\Users\\HP\\Documents\\Projeto Final de curso\\Consumo"
    DIR_PV = r"C:\\Users\\HP\\Documents\\Projeto Final de curso\\PV"
    SAIDA = r"C:\\Users\\HP\\Documents\\Projeto Final de curso\\Resultados_Avancados"

    SEED = 42
    TIMESTEPS = 24 * 3
    HORIZON = 24 * 3
    TEST_SIZE = 0.2
    EPOCHS = 150
    BATCH_SIZE = 128
    EARLY_STOPPING_PATIENCE = 12
    LR_PATIENCE = 8
    MIN_LR = 1e-7
    VALIDATION_SPLIT = 0.15

    PROPHET_CONFIG = {
        'changepoint_prior_scale': 0.05,
        'seasonality_prior_scale': 10.0,
        'seasonality_mode': 'additive',
        'daily_seasonality': True,
        'weekly_seasonality': True,
        'yearly_seasonality': False
    }

# Verificação de GPU
gpus = tf.config.list_physical_devices('GPU')
if gpus:
    print(f"GPU disponível: {gpus}")
    for gpu in gpus:
        tf.config.experimental.set_memory_growth(gpu, True)
else:
    print("Nenhuma GPU detectada - usando CPU")

# Cria diretórios e configura logging
os.makedirs(Config.SAIDA, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(Config.SAIDA, "execucao.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
np.random.seed(Config.SEED)
tf.random.set_seed(Config.SEED)

class DataProcessor:
    @staticmethod
    def processar_arquivo(arquivo: str) -> Optional[pd.DataFrame]:
        try:
            df = pd.read_csv(
                arquivo,
                sep=';|,|\t',
                engine='python',
                dtype=str
            )
            # Detecta coluna de tempo
            cols = df.columns.tolist()
            time_col = next((col for col in cols if 'date' in col.lower() or 'time' in col.lower()), cols[0])
            # Converte coluna de tempo com dayfirst e erros coerção
            df[time_col] = pd.to_datetime(
                df[time_col],
                dayfirst=True,
                infer_datetime_format=True,
                errors='coerce'
            )
            df = df.dropna(subset=[time_col])
            # Converte colunas numéricas
            numeric_df = df.drop(columns=[time_col]).apply(pd.to_numeric, errors='coerce')
            # Soma de todas colunas numéricas por timestamp
            numeric_df['total'] = numeric_df.sum(axis=1)
            df = pd.DataFrame({
                'timestamp': df[time_col],
                'total': numeric_df['total']
            }).set_index('timestamp')
            # Reamostragem e interpolação
            df = df.resample('30T').sum().interpolate()
            return df.dropna()
        except Exception as e:
            logger.error(f"Erro processando {os.path.basename(arquivo)}: {str(e)}")
            return None

    @staticmethod
    def consolidar_dados(diretorio: str, tipo: str) -> Optional[pd.DataFrame]:
        try:
            arquivos = glob.glob(os.path.join(diretorio, '*.csv')) + glob.glob(os.path.join(diretorio, '*.txt'))
            dfs = [DataProcessor.processar_arquivo(arquivo) for arquivo in arquivos]
            dfs = [df for df in dfs if df is not None]
            if not dfs:
                raise ValueError(f"Nenhum dado válido encontrado para {tipo}")
            # Soma total de cada arquivo em um único timestamp
            df_total = pd.concat(dfs, axis=1).fillna(0).sum(axis=1).to_frame(f'total_{tipo}')
            return df_total[~df_total.index.duplicated()]
        except Exception as e:
            logger.error(f"Erro consolidando {tipo}: {str(e)}")
            return None

    @staticmethod
    def calcular_consumo_liquido(consumo: pd.DataFrame, pv: pd.DataFrame) -> pd.DataFrame:
        df = pd.concat([consumo, pv], axis=1).dropna()
        df.columns = ['total_consumo', 'total_pv']
        df['consumo_liquido'] = (df['total_consumo'] - df['total_pv']).clip(lower=0)
        return df[['consumo_liquido']]

        except Exception as e:
            logger.error(f"Erro cálculo consumo líquido: {str(e)}")
            raise

class ModelBuilder:
    @staticmethod
    def criar_lstm(timesteps: int, features: int) -> tf.keras.Model:
        model = Sequential([
            Bidirectional(LSTM(64, return_sequences=False, input_shape=(timesteps, features))),
            Dropout(0.2),
            Dense(32, activation='relu'),
            Dense(1)
        ])
        model.compile(
            optimizer=Adam(learning_rate=0.001),
            loss=Huber(),
            metrics=['mae']
        )
        return model

    @staticmethod
    def criar_transformer(timesteps: int, features: int) -> tf.keras.Model:
        inputs = Input(shape=(timesteps, features))
        x = LayerNormalization(epsilon=1e-6)(inputs)
        x = MultiHeadAttention(num_heads=2, key_dim=64)(x, x)
        x = Dropout(0.1)(x)
        x = Dense(32, activation='relu')(x)
        outputs = Dense(1)(x)
        model = Model(inputs=inputs, outputs=outputs)
        model.compile(
            optimizer=Adam(learning_rate=0.001),
            loss=Huber(),
            metrics=['mae']
        )
        return model

    @staticmethod
    def criar_prophet() -> Prophet:
        return Prophet(**Config.PROPHET_CONFIG)

class TimeCallback(tf.keras.callbacks.Callback):
    def __init__(self):
        self.times = []

    def on_epoch_begin(self, epoch, logs=None):
        self.start_time = time.time()

    def on_epoch_end(self, epoch, logs=None):
        epoch_time = time.time() - self.start_time
        self.times.append(epoch_time)
        if epoch % 10 == 0:
            logger.info(f"Epoch {epoch} - Tempo: {epoch_time:.2f}s")

class ModelTrainer:
    @staticmethod
    def preparar_dados(dados: pd.DataFrame) -> Tuple:
        scaler = RobustScaler()
        dados_scaled = scaler.fit_transform(dados)
        X, y = [], []
        for i in range(Config.TIMESTEPS, len(dados_scaled) - Config.HORIZON):
            X.append(dados_scaled[i-Config.TIMESTEPS:i, 0])
            y.append(dados_scaled[i:i+Config.HORIZON, 0])
        X, y = np.array(X), np.array(y)
        X = X.reshape(X.shape[0], X.shape[1], 1)
        split = int(len(X) * (1 - Config.TEST_SIZE))
        return X[:split], X[split:], y[:split], y[split:], scaler

    @staticmethod
    def treinar_modelo(modelo: tf.keras.Model, X_train, y_train, X_test, y_test, nome: str):
        callbacks = [
            EarlyStopping(patience=Config.EARLY_STOPPING_PATIENCE, restore_best_weights=True),
            ReduceLROnPlateau(patience=Config.LR_PATIENCE, min_lr=Config.MIN_LR),
            ModelCheckpoint(os.path.join(Config.SAIDA, f'melhor_{nome}.h5'), save_best_only=True),
            TimeCallback()
        ]
        history = modelo.fit(
            X_train, y_train,
            validation_data=(X_test, y_test),
            epochs=Config.EPOCHS,
            batch_size=Config.BATCH_SIZE,
            callbacks=callbacks,
            verbose=1
        )
        modelo.save(os.path.join(Config.SAIDA, f'modelo_final_{nome}.h5'))
        return history

    @staticmethod
    def avaliar_modelo(modelo, X_test, y_test, scaler, nome: str):
        y_pred = modelo.predict(X_test)
        y_true = scaler.inverse_transform(y_test.reshape(-1, 1)).flatten()
        y_pred = scaler.inverse_transform(y_pred.reshape(-1, 1)).flatten()
        metrics = {
            'MAE': mean_absolute_error(y_true, y_pred),
            'RMSE': np.sqrt(mean_squared_error(y_true, y_pred)),
            'R2': r2_score(y_true, y_pred),
            'MAPE': mean_absolute_percentage_error(y_true, y_pred)
        }
        resultados = pd.DataFrame({'Real': y_true, 'Previsto': y_pred})
        resultados.to_csv(os.path.join(Config.SAIDA, f'resultados_{nome}.csv'), index=False)
        plt.figure(figsize=(12, 6))
        plt.plot(y_true[:500], label='Real')
        plt.plot(y_pred[:500], label='Previsto', alpha=0.7)
        plt.title(f'Comparação Real vs Previsto - {nome}')
        plt.legend()
        plt.savefig(os.path.join(Config.SAIDA, f'comparacao_{nome}.png'))
        plt.close()
        return metrics

    @staticmethod
    def treinar_prophet(dados: pd.DataFrame) -> Dict:
        df = dados.reset_index()
        df.columns = ['ds', 'y']
        df['ds'] = pd.to_datetime(df['ds'])
        split = int(len(df) * (1 - Config.TEST_SIZE))
        train, test = df.iloc[:split], df.iloc[split:]
        modelo = ModelBuilder.criar_prophet()
        modelo.fit(train)
        future = modelo.make_future_dataframe(periods=len(test), freq='30T', include_history=False)
        forecast = modelo.predict(future)
        resultados = test.merge(forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']], on='ds')
        resultados.to_csv(os.path.join(Config.SAIDA, 'resultados_prophet.csv'), index=False)
        y_true = resultados['y'].values
        y_pred = resultados['yhat'].values
        metrics = {
            'MAE': mean_absolute_error(y_true, y_pred),
            'RMSE': np.sqrt(mean_squared_error(y_true, y_pred)),
            'R2': r2_score(y_true, y_pred),
            'MAPE': mean_absolute_percentage_error(y_true, y_pred)
        }
        fig1 = modelo.plot(forecast)
        plt.title('Previsão Prophet')
        plt.savefig(os.path.join(Config.SAIDA, 'prophet_previsao.png'))
        plt.close()
        fig2 = modelo.plot_components(forecast)
        plt.savefig(os.path.join(Config.SAIDA, 'prophet_componentes.png'))
        plt.close()
        return {'metrics': metrics, 'model': modelo}

def main():
    try:
        logger.info("Iniciando processamento...")
        consumo = DataProcessor.consolidar_dados(Config.DIR_CONSUMO, 'consumo')
        pv = DataProcessor.consolidar_dados(Config.DIR_PV, 'pv')
        if consumo is None or pv is None:
            raise ValueError("Dados não carregados corretamente")
        dados = DataProcessor.calcular_consumo_liquido(consumo, pv)
        dados.to_csv(os.path.join(Config.SAIDA, 'dados_consolidados.csv'))
        metricas = {}
        X_train, X_test, y_train, y_test, scaler = ModelTrainer.preparar_dados(dados)
        lstm = ModelBuilder.criar_lstm(Config.TIMESTEPS, 1)
        ModelTrainer.treinar_modelo(lstm, X_train, y_train, X_test, y_test, 'LSTM')
        metricas['LSTM'] = ModelTrainer.avaliar_modelo(lstm, X_test, y_test, scaler, 'LSTM')
        transformer = ModelBuilder.criar_transformer(Config.TIMESTEPS, 1)
        ModelTrainer.treinar_modelo(transformer, X_train, y_train, X_test, y_test, 'Transformer')
        metricas['Transformer'] = ModelTrainer.avaliar_modelo(transformer, X_test, y_test, scaler, 'Transformer')
        prophet_results = ModelTrainer.treinar_prophet(dados)
        metricas['Prophet'] = prophet_results['metrics']
        logger.info("\n=== Métricas Finais ===")
        for modelo, metrica in metricas.items():
            logger.info(f"\n{modelo}:")
            for k, v in metrica.items():
                logger.info(f"{k}: {v:.4f}")
        pd.DataFrame(metricas).to_csv(os.path.join(Config.SAIDA, 'metricas_finais.csv'))
        logger.info("\nProcesso concluído com sucesso!")
    except Exception as e:
        logger.error(f"Erro no processo principal: {str(e)}")
        raise

if __name__ == "__main__":
    main()