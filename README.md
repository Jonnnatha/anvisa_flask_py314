# Consulta Regulatória ANVISA (Flask + Python 3.14)

Aplicação web para consulta por **número de registro ANVISA (11 dígitos)** com resposta em três blocos:

1. **Dados do produto** (API oficial da ANVISA)
2. **Alertas associados ao registro** (base local coletada e indexada)
3. **Materiais/sinais públicos úteis** (busca pública filtrada por contexto real do produto)

## Arquitetura de serviços

```text
app/services/
  anvisa_auth.py       # autenticação OAuth2 da API oficial
  product_service.py   # consulta oficial do produto
  product_enrichment_service.py # enriquecimento de marca/modelo e sinais úteis
  alerts_collector.py  # coleta estruturada dos alertas da Anvisa
  alerts_index.py      # indexação por alerta/registro/empresa/produto/modelo
  alerts_service.py    # consulta da base local indexada
  materials_service.py # materiais técnicos e sinais públicos relevantes
  search_service.py    # consolida resposta final para o frontend
```

## Estratégia implementada para alertas

### Etapa 1 — Coleta e estruturação

- Percorre páginas de alertas da Anvisa (`/alertas?pagina=N`).
- Abre cada página de detalhe.
- Extrai campos estruturados como resumo, problema, ação, recomendações e identificação do produto.
- Persiste base local em `app/data/anvisa_alertas.json`.

### Etapa 2 — Indexação

- Gera índice local em `app/data/anvisa_alertas_index.json`.
- Indexa por:
  - número do alerta
  - número de registro ANVISA
  - empresa
  - nome comercial
  - nome técnico
  - modelo afetado

### Etapa 3 — Consulta

- Consulta produto via API oficial Anvisa.
- Consulta alertas na base local indexada por registro.
- Retorna alertas associados no mesmo payload da busca.

## Materiais e sinais públicos

- Busca no portal público da Anvisa (`gov.br`) com termos reais do produto e do registro.
- Mantém apenas itens com evidência forte por palavras-chave técnicas (manual, recall, ação de campo, field safety notice etc.).
- Se não houver evidência forte, retorna seção vazia com mensagem honesta.

## Execução

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# configure credenciais ANVISA no .env
python -m app
```

Abra: `http://127.0.0.1:5000`

## Variáveis de ambiente

Obrigatórias para API oficial de produto:

- `ANVISA_AUTH_CLIENT_ID`
- `ANVISA_AUTH_CLIENT_SECRET`

Principais opcionais:

- `ANVISA_AUTH_TOKEN_URL`
- `ANVISA_AUTH_SCOPE`
- `ANVISA_PRODUCT_API_URL`
- `REQUEST_TIMEOUT`
- `SSL_VERIFY`
- `ALERTS_DATA_TTL_HOURS` (default `24`)
- `ALERTS_MAX_PAGES` (default `12`)

## Endpoint da aplicação

- `GET /api/consultar?registro=80146502070`
- `GET /api/alertas?fabricante=&registro=&nome_comercial=&nome_tecnico=&data_inicio=DD/MM/AAAA&data_fim=DD/MM/AAAA`
- `GET /api/relatorios/resumo?periodo=diario|mensal&referencia=YYYY-MM-DD&registros_base=80146502070,12345678901`
