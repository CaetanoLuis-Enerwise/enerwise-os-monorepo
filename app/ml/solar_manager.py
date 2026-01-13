import numpy as np
import pandas as pd
import math

class SolarPhysicsEngine:
    def __init__(self, lat=41.15, lon=-8.62): # Coordenadas do Porto/Gaia
        self.lat = lat
        self.lon = lon
        
    def add_solar_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adiciona geometria solar a um DataFrame que tenha índice de tempo.
        Substitui a falta de estação meteorológica.
        """
        # Garante índice datetime
        if not isinstance(df.index, pd.DatetimeIndex):
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
                
        # Dia do ano (1-365) e Hora Decimal
        doy = df.index.dayofyear
        hour = df.index.hour + df.index.minute / 60.0
        
        # --- CÁLCULOS FÍSICOS (ASTRONOMIA) ---
        # Declinação Solar (delta) - Ângulo do sol com o equador
        delta = 23.45 * np.sin(np.radians(360/365 * (284 + doy)))
        
        # Ângulo Horário (omega) - 15 graus por hora longe do meio-dia solar
        # (Simplificado, assumindo meio-dia às 12h locais para este MVP)
        omega = 15 * (hour - 12)
        
        # Conversão para radianos
        lat_rad = np.radians(self.lat)
        delta_rad = np.radians(delta)
        omega_rad = np.radians(omega)
        
        # Elevação Solar (alpha) - Altura do sol no céu
        sin_alpha = np.sin(lat_rad) * np.sin(delta_rad) + \
                    np.cos(lat_rad) * np.cos(delta_rad) * np.cos(omega_rad)
        alpha = np.degrees(np.arcsin(np.clip(sin_alpha, -1, 1)))
        
        # Radiação Extraterrestre Teórica (Io)
        # Se alpha < 0 (noite), radiação é 0.
        # Isto ensina à IA que À NOITE NÃO HÁ PRODUÇÃO (Física básica!)
        df['solar_elevation'] = np.maximum(0, alpha)
        df['theoretical_radiation'] = np.where(
            df['solar_elevation'] > 0,
            1367 * sin_alpha, # 1367 W/m2 é a constante solar
            0
        )
        
        # Features cíclicas para ajudar a IA
        df['doy_sin'] = np.sin(2 * np.pi * doy / 365.0)
        df['doy_cos'] = np.cos(2 * np.pi * doy / 365.0)
        
        return df