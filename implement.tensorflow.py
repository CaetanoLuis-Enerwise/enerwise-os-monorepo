import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.callbacks import EarlyStopping

class EnergyForecaster:
    def __init__(self, input_shape):
        self.model = self.build_generator(input_shape)
    
    def build_generator(self, input_shape):
        """Constrói modelo generativo para previsão de séries temporais"""
        model = Sequential([
            LSTM(128, return_sequences=True, input_shape=input_shape),
            Dropout(0.2),
            LSTM(64, return_sequences=True),
            Dropout(0.2),
            LSTM(32),
            Dense(32, activation='relu'),
            Dense(1)
        ])
        
        model.compile(optimizer='adam', loss='mse', metrics=['mae'])
        return model
    
    def train(self, X_train, y_train, epochs=50, batch_size=32, validation_split=0.1):
        early_stop = EarlyStopping(monitor='val_loss', patience=5)
        
        history = self.model.fit(
            X_train, y_train,
            epochs=epochs,
            batch_size=batch_size,
            validation_split=validation_split,
            callbacks=[early_stop],
            verbose=1
        )
        
        return history
    
    def predict(self, X):
        return self.model.predict(X)
    
    def evaluate(self, X_test, y_test):
        return self.model.evaluate(X_test, y_test, verbose=0)

# Uso do modelo
input_shape = (X_train.shape[1], 1)  # (time_steps, features)
forecaster = EnergyForecaster(input_shape)

# Treinamento
history = forecaster.train(X_train, y_train)

# Avaliação
loss, mae = forecaster.evaluate(X_test, y_test)
print(f"\nErro Médio Absoluto no Teste: {mae:.4f}")

# Previsões
predictions = forecaster.predict(X_test)

# Visualização
processor.plot_results(y_test, predictions.flatten(), 'Previsão vs Real (Teste)')