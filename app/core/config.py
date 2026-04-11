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

ANVISA_AUTH_TOKEN_URL = os.getenv(
    'ANVISA_AUTH_TOKEN_URL',
    'https://acesso.prd.apps.anvisa.gov.br/auth/realms/externo/protocol/openid-connect/token',
)
ANVISA_AUTH_CLIENT_ID = os.getenv('ANVISA_AUTH_CLIENT_ID', '')
ANVISA_AUTH_CLIENT_SECRET = os.getenv('ANVISA_AUTH_CLIENT_SECRET', '')
ANVISA_AUTH_SCOPE = os.getenv('ANVISA_AUTH_SCOPE', 'openid')

ANVISA_PRODUCT_API_URL = os.getenv(
    'ANVISA_PRODUCT_API_URL',
    'https://api-gateway.prd.apps.anvisa.gov.br/consultas-externas-api/api/v1/consulta/saude',
)
ANVISA_API_BASE_URL = os.getenv('ANVISA_API_BASE_URL', 'https://api-gateway.prd.apps.anvisa.gov.br/consultas-externas-api/api/v1')
PRODUCTS_PAGE_URL = ANVISA_PRODUCT_API_URL
ALERTS_PAGE_URL = 'https://antigo.anvisa.gov.br/alertas'

ALERTS_DATA_FILE = DATA_DIR / 'anvisa_alertas.json'
ALERTS_INDEX_FILE = DATA_DIR / 'anvisa_alertas_index.json'
ALERTS_DATA_TTL_HOURS = int(os.getenv('ALERTS_DATA_TTL_HOURS', '24'))
ALERTS_MAX_PAGES = int(os.getenv('ALERTS_MAX_PAGES', '12'))
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '30'))
USER_AGENT = os.getenv(
    'ANVISA_USER_AGENT',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/123.0 Safari/537.36',
)

SSL_VERIFY = os.getenv('SSL_VERIFY', 'true').lower() in ('1', 'true', 'yes')

