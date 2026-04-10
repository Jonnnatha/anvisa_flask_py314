# Consulta Regulatória ANVISA (Flask + Python 3.14)

Sistema web para consulta por **número de registro ANVISA (11 dígitos)** com foco em estabilidade no Python 3.14.

## O que o sistema faz

1. Consulta dados do equipamento/produto na base pública da Anvisa.
2. Tenta consultar alertas de tecnovigilância no portal antigo da Anvisa.
3. Se houver bloqueio anti-bot (HTTP 403), aplica fallback progressivo em 5 camadas: oficial, alternativa, identificação parcial, fallback externo opcional e validação manual.
4. Mesmo em falha parcial, retorna números de alerta com metadados: `numero_alerta`, `origem_da_descoberta`, `nivel_confianca`, `metodo`, `link_pesquisa_manual` e `link_oficial` quando disponível.

## Stack escolhida

- **Backend:** Flask 3.1 (simples e estável)
- **HTTP:** requests + retry
- **Parse HTML:** BeautifulSoup4
- **Frontend:** HTML/CSS/JS puro

Sem dependências pesadas (FastAPI/Pydantic/Rust build).

## Estrutura

```text
app/
  __init__.py              # factory create_app
  __main__.py              # python -m app
  app.py                   # compat shim (python app/app.py)
  routes.py                # rotas web/API
  core/
    config.py              # configurações e env vars
  services/
    http_client.py         # cliente HTTP com retry e SSL configurável
    product_service.py     # busca/cache do CSV oficial e lookup por registro
    alerts_service.py      # busca de alertas + fallback robusto
    search_service.py      # consolidação produto + alertas
  templates/
    index.html
  static/
    css/style.css
    js/app.js
```

## Requisitos

- Python 3.14
- pip

## Como rodar (VS Code / terminal)

### Linux/macOS

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m app
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m app
```

Abra: `http://127.0.0.1:5000`

## Endpoint API

- `GET /api/consultar?registro=10349000912`

### Exemplo de retorno (sucesso com fallback de alertas)

```json
{
  "registro_anvisa": "10349000912",
  "found": true,
  "product": {"nome_produto": "..."},
  "alerts_count": 0,
  "alerts": [],
  "alerts_warning": "Falha na consulta automática...",
  "alerts_manual_url": "https://antigo.anvisa.gov.br/alertas?tagsName=10349000912"
}
```

## Configurações por variável de ambiente

- `SSL_VERIFY` (default `false`): validação SSL no requests.
- `REQUEST_TIMEOUT` (default `30`)
- `PRODUCT_CACHE_TTL_HOURS` (default `24`)
- `ANVISA_USER_AGENT` (opcional)
- `ENABLE_EXTERNAL_ALERT_FALLBACK` (default `true`): habilita/desabilita fallback externo por registro.
- `EXTERNAL_ALERT_LOOKUP_BASE_URL` (default `https://brunoroma.pythonanywhere.com`): base da consulta externa opcional.

Exemplo:

```bash
export SSL_VERIFY=true
python -m app
```

## Limitações reais das fontes da Anvisa

- O portal de alertas pode bloquear acesso automatizado (403).
- Alguns endpoints antigos podem falhar com SSL dependendo do ambiente local/rede.
- Estrutura HTML do portal de alertas pode mudar, exigindo ajuste no parser.
- Para reduzir indisponibilidade total, existe fallback de contingência para extração parcial de números de alerta.

Por isso, a consulta de alertas foi isolada em `services/alerts_service.py` e organizada por camadas, com log por estratégia, motivo exato de falha e fallback externo configurável para manter utilidade mesmo com bloqueio 403.
