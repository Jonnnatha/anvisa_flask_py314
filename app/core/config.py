import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / 'app' / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)
PRODUCT_CACHE_FILE = DATA_DIR / 'anvisa_products.csv'
PRODUCT_CACHE_TTL_HOURS = 24
PRODUCTS_PAGE_URL = 'https://www.gov.br/anvisa/pt-br/assuntos/produtosparasaude/lista-de-dispositivos-medicos-regularizados'
ALERTS_PAGE_URL = 'https://antigo.anvisa.gov.br/alertas'
REQUEST_TIMEOUT = 30
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0 Safari/537.36'
