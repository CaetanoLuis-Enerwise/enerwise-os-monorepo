def add_time_features(df):
    """Adiciona features temporais para melhorar a previsão"""
    df = df.copy()
    df['hora'] = df.index.hour
    df['dia_semana'] = df.index.dayofweek  # 0=Segunda, 6=Domingo
    df['fim_de_semana'] = df['dia_semana'].isin([5, 6]).astype(int)
    df['mes'] = df.index.month
    return df

# Adicionar features temporais
enhanced_data = add_time_features(energy_data)

# Visualizar padrões
plt.figure(figsize=(12, 8))
plt.subplot(2, 1, 1)
energy_data.groupby('hora')['consumo_liquido'].mean().plot(title='Padrão Diário')
plt.subplot(2, 1, 2)
energy_data.groupby('dia_semana')['consumo_liquido'].mean().plot(title='Padrão Semanal')
plt.tight_layout()
plt.show()