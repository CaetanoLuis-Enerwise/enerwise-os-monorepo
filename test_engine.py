import sys
import os

# --- BLOCO DE DIAGNÓSTICO ---
# Pega na pasta onde ESTE ficheiro (test_engine.py) está guardado
diretorio_atual = os.path.dirname(os.path.abspath(__file__))

# Força o Python a olhar para esta pasta
sys.path.insert(0, diretorio_atual)

print(f"📍 O script está na pasta: {diretorio_atual}")
print("📂 O Python vê estes ficheiros aqui:")
try:
    ficheiros = os.listdir(diretorio_atual)
    print(ficheiros)
except Exception as e:
    print(f"Erro a ler pasta: {e}")

print("-" * 30)
# ---------------------------

try:
    # Tenta importar agora com o caminho forçado
    from app.ml.pipeline_super import infer_from_series
    print("✅ SUCESSO! O módulo 'app' foi encontrado.")
    
    # Se passou, corre o teste
    dados_teste = [350, 340, 330, 320, 310, 305, 310, 350, 450, 500, 550, 580]
    resultado = infer_from_series(dados_teste, horizon=24)
    print(f"⚡ Previsão gerada. Volatilidade: {resultado['meta']['volatility_index']:.2f}")

except ImportError as e:
    print(f"❌ ERRO CRÍTICO: {e}")
    print("\n⚠️ PISTAS PARA RESOLVER:")
    if 'app' not in ficheiros:
        print("1. O Python NÃO VÊ a pasta 'app' aqui. Verifica se criaste a pasta 'app' no mesmo sítio deste ficheiro.")
    else:
        print("1. A pasta 'app' existe, mas falta o ficheiro '__init__.py' lá dentro.")
        print("2. Ou tens um ficheiro chamado 'app.py' que está a confundir o sistema.")