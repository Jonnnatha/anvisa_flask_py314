# Consulta Regulatória ANVISA (Flask + Python 3.14)

Sistema web para consulta por **número de registro ANVISA (11 dígitos)** com foco em estabilidade no Python 3.14.

## O que o sistema faz

1. Consulta dados do produto de saúde via **API oficial da Anvisa** (`POST /consulta/saude`) usando `filter.numeroRegistro`.
2. Mantém a consulta de alertas em **módulo isolado**, com estratégia de fallback/assistida quando há bloqueio das fontes (HTTP 403).
3. Exibe no frontend, de forma separada, o resultado do produto (API oficial) e o status da busca de alertas.

> Importante: a integração oficial implementada nesta refatoração cobre **consulta de produtos de saúde**. A camada de alertas continua independente e não assume API oficial para tecnovigilância sem evidência.

## Stack escolhida

- **Backend:** Flask 3.1
- **HTTP:** requests
- **Parse HTML (alertas):** BeautifulSoup4
- **Frontend:** HTML/CSS/JS puro

## Estrutura

```text
app/
  __init__.py
  __main__.py
  app.py
  routes.py
  core/
    config.py              # env vars + carregamento opcional de .env
  services/
    product_service.py     # integração API oficial de produto
    alerts_service.py      # consulta de alertas isolada + fallback assistido
    search_service.py      # orquestra produto + alertas mantendo separação lógica
  templates/
    index.html
  static/
    css/style.css
    js/app.js
.env.example               # variáveis para API oficial
```

## Requisitos

- Python 3.14
- pip

## Como rodar

### Linux/macOS

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
# edite .env e preencha ANVISA_API_TOKEN
python -m app
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# edite .env e preencha ANVISA_API_TOKEN
python -m app
```

Abra: `http://127.0.0.1:5000`

## Variáveis de ambiente

Obrigatórias para produto (API oficial):

- `ANVISA_API_TOKEN`: token Bearer da API oficial.
- `ANVISA_API_BASE_URL`: base da API oficial (default: `https://consultas.anvisa.gov.br/api`).

Opcionais:

- `REQUEST_TIMEOUT` (default `30`)
- `SSL_VERIFY` (default `false`)
- `ANVISA_USER_AGENT`
- `ENABLE_EXTERNAL_ALERT_FALLBACK` (default `true`)
- `EXTERNAL_ALERT_LOOKUP_BASE_URL`

> Nunca hardcode token no código. Use sempre variável de ambiente.

## Estratégia de tratamento de erros (produto)

A camada de produto trata explicitamente:

- erro de autenticação (`401/403`) → token ausente/inválido/expirado;
- rate limit (`429`) → limite excedido na API;
- resposta vazia ou inválida → retorno inconclusivo da API;
- falhas de rede/HTTP genéricas.

## Endpoint API

- `GET /api/consultar?registro=10349000912`

Exemplo resumido de retorno:

```json
{
  "registro_anvisa": "10349000912",
  "found": true,
  "product": {
    "registro_anvisa": "10349000912",
    "nome_produto": "..."
  },
  "alerts_status": "anti_bot_block",
  "alerts_warning": "Fonte oficial bloqueou automação...",
  "alerts_manual_links": {
    "tecnovigilancia": "https://www.gov.br/anvisa/..."
  }
}
```

## Limitações reais (alertas)

- Fontes de alertas podem bloquear automação (HTTP 403).
- Por isso, a aplicação preserva fallback e **modo assistido** sem quebrar a consulta de produto.
- Resultados de sinais públicos/web não equivalem a validação oficial automática.
