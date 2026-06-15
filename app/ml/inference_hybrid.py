from datetime import timedelta
from pathlib import Path
from typing import Optional, Sequence

import joblib
import pandas as pd

from app.ml.solar_manager import SolarPhysicsEngine


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = PROJECT_ROOT / "assets" / "models"
PATH_LOAD = MODEL_DIR / "engine_load_v1.pkl"
PATH_PV = MODEL_DIR / "engine_pv_v1.pkl"


class HybridPredictor:
    """Recursive load and photovoltaic forecasting engine."""

    def __init__(self) -> None:
        if not PATH_LOAD.exists() or not PATH_PV.exists():
            raise FileNotFoundError(
                "Trained models were not found in assets/models. "
                "Run app.ml.train_hybrid first."
            )

        self.model_load = joblib.load(PATH_LOAD)
        self.model_pv = joblib.load(PATH_PV)
        self.physics = SolarPhysicsEngine()

    def predict(
        self,
        recent_data: pd.DataFrame,
        horizon: int = 24,
        interval_minutes: int = 60,
    ) -> list[dict]:
        if recent_data.empty:
            raise ValueError("At least one historical observation is required.")
        if horizon < 1:
            raise ValueError("Forecast horizon must be positive.")

        history = recent_data.copy()
        if not isinstance(history.index, pd.DatetimeIndex):
            history["timestamp"] = pd.to_datetime(history["timestamp"])
            history.set_index("timestamp", inplace=True)

        required_columns = {"total_consumo", "total_pv"}
        missing_columns = required_columns.difference(history.columns)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"Historical data is missing columns: {missing}")

        history = history.sort_index()
        last_timestamp = history.index[-1]
        future_predictions = []

        for offset in range(1, horizon + 1):
            next_time = last_timestamp + timedelta(
                minutes=interval_minutes * offset
            )
            row = pd.DataFrame(index=[next_time])
            row["hour"] = next_time.hour
            row["dayofweek"] = next_time.dayofweek
            row["month"] = next_time.month
            row = self.physics.add_solar_features(row)

            def get_lag(column: str, hours_back: int) -> float:
                target_time = next_time - timedelta(
                    minutes=interval_minutes * hours_back
                )
                if target_time in history.index:
                    value = history.loc[target_time, column]
                    if isinstance(value, pd.Series):
                        value = value.iloc[-1]
                    return float(value)
                return float(history.iloc[-1][column])

            for lag in (1, 24, 168):
                row[f"lag_load_{lag}"] = get_lag("total_consumo", lag)
                row[f"lag_pv_{lag}"] = get_lag("total_pv", lag)

            load_features = [
                "hour",
                "dayofweek",
                "month",
                "lag_load_1",
                "lag_load_24",
                "lag_load_168",
            ]
            pv_features = [
                "solar_elevation",
                "theoretical_radiation",
                "doy_sin",
                "lag_pv_1",
                "lag_pv_24",
            ]

            predicted_load = max(
                0.0, float(self.model_load.predict(row[load_features])[0])
            )
            predicted_pv = float(self.model_pv.predict(row[pv_features])[0])
            if float(row["solar_elevation"].iloc[0]) <= 0:
                predicted_pv = 0.0
            predicted_pv = max(0.0, predicted_pv)

            history = pd.concat(
                [
                    history,
                    pd.DataFrame(
                        {
                            "total_consumo": [predicted_load],
                            "total_pv": [predicted_pv],
                        },
                        index=[next_time],
                    ),
                ]
            )

            future_predictions.append(
                {
                    "timestamp": next_time.isoformat(),
                    "load_kw": round(predicted_load, 2),
                    "pv_kw": round(predicted_pv, 2),
                    "net_load_kw": round(predicted_load - predicted_pv, 2),
                }
            )

        return future_predictions


_predictor: Optional[HybridPredictor] = None


def get_forecast(
    historical_data: Sequence[float],
    horizon: int = 24,
    historical_pv: Optional[Sequence[float]] = None,
    historical_timestamps: Optional[Sequence[str]] = None,
    interval_minutes: Optional[int] = None,
) -> list[dict]:
    """Build an hourly history and generate a forecast with the trained engine."""
    global _predictor

    if not historical_data:
        raise ValueError("historical_data cannot be empty.")
    if historical_pv is None:
        historical_pv = [0.0] * len(historical_data)
    if len(historical_pv) != len(historical_data):
        raise ValueError(
            "historical_pv must have the same length as historical_data."
        )

    if _predictor is None:
        _predictor = HybridPredictor()

    if historical_timestamps is not None:
        if len(historical_timestamps) != len(historical_data):
            raise ValueError(
                "historical_timestamps must match historical_data length."
            )
        dates = pd.DatetimeIndex(pd.to_datetime(historical_timestamps))
        if not dates.is_monotonic_increasing or dates.has_duplicates:
            raise ValueError(
                "historical_timestamps must be unique and increasing."
            )
        if interval_minutes is None and len(dates) > 1:
            interval_minutes = int(
                round((dates.to_series().diff().dropna().median()).total_seconds() / 60)
            )
    else:
        interval_minutes = interval_minutes or 60
        end_date = pd.Timestamp.now().floor(f"{interval_minutes}min")
        dates = pd.date_range(
            end=end_date,
            periods=len(historical_data),
            freq=f"{interval_minutes}min",
        )

    interval_minutes = interval_minutes or 60
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be positive.")
    history = pd.DataFrame(
        {
            "total_consumo": [float(value) for value in historical_data],
            "total_pv": [float(value) for value in historical_pv],
        },
        index=dates,
    )
    return _predictor.predict(
        history,
        horizon=horizon,
        interval_minutes=interval_minutes,
    )
