import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / 'app' / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)


# Carrega .env local de forma simples (sem dependência adicional).
def _load_local_env() -> None:
    env_path = BASE_DIR / '.env'
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_local_env()


PRODUCT_CACHE_FILE = DATA_DIR / 'anvisa_products.csv'
PRODUCT_CACHE_TTL_HOURS = int(os.getenv('PRODUCT_CACHE_TTL_HOURS', '24'))

ANVISA_API_BASE_URL = os.getenv('ANVISA_API_BASE_URL', 'https://consultas.anvisa.gov.br/api')
ANVISA_API_TOKEN = os.getenv('ANVISA_API_TOKEN', '')
PRODUCTS_PAGE_URL = f"{ANVISA_API_BASE_URL.rstrip('/')}/consulta/saude"
ALERTS_PAGE_URL = 'https://antigo.anvisa.gov.br/alertas'

REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '30'))
USER_AGENT = os.getenv(
    'ANVISA_USER_AGENT',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/123.0 Safari/537.36',
)

# Em ambiente local alguns endpoints antigos da Anvisa falham em SSL.
# Mantemos valor padrão False para não quebrar a experiência local.
SSL_VERIFY = os.getenv('SSL_VERIFY', 'false').lower() in ('1', 'true', 'yes')

ENABLE_EXTERNAL_ALERT_FALLBACK = os.getenv('ENABLE_EXTERNAL_ALERT_FALLBACK', 'true').lower() in ('1', 'true', 'yes')
EXTERNAL_ALERT_LOOKUP_BASE_URL = os.getenv('EXTERNAL_ALERT_LOOKUP_BASE_URL', 'https://brunoroma.pythonanywhere.com')
