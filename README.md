# Consulta Regulatória ANVISA (Flask + Python 3.14)

Aplicação web para consulta por **número de registro ANVISA (11 dígitos)** com resposta separada em três blocos:

1. **Dados do produto** (API oficial da ANVISA)
2. **Alertas** (fonte externa de apoio)
3. **Reclamações / sinais públicos relacionados** (busca pública com filtro de relevância)

## Arquitetura de serviços

```text
app/services/
  anvisa_auth.py      # autenticação OAuth2 da API oficial
  product_service.py  # POST /consulta/saude com filter.numeroRegistro
  alerts_service.py   # consulta em https://brunoroma.pythonanywhere.com/registro/<registro>
  signals_service.py  # busca pública com validação de relevância
  search_service.py   # consolida resposta final para o frontend
```

## Regras implementadas

### 1) Dados do produto (API oficial)

- Consulta oficial em `POST /consulta/saude`.
- Filtro utilizado: `filter.numeroRegistro`.
- Normalização apenas com campos coerentes com o retorno oficial:
  - `numeroRegistro`
  - `nomeProduto`
  - `numeroProcesso`
  - `situacaoNotificacaoRegistro`
  - `nomeTecnico`
  - `empresa.razaoSocial`
  - `empresa.cnpj`

### 2) Alertas (fonte externa de apoio)

- Endpoint: `https://brunoroma.pythonanywhere.com/registro/<REGISTRO_ANVISA>`.
- Parsing dos números de alerta no formato textual retornado.
- Estrutura de cada alerta:
  - `numero_alerta`
  - `link_pesquisa_manual`
  - `origem_da_descoberta`
  - `nivel_confianca`
- A interface destaca que **não é fonte oficial da ANVISA**.

### 3) Reclamações / sinais públicos relacionados

- Coleta apenas resultados públicos com filtro rígido de relevância.
- Só mantém itens com relação concreta por termos do produto/registro.
- Se não houver evidência forte, a seção fica vazia com mensagem honesta:
  - **“Nenhuma reclamação pública relevante foi encontrada.”**

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
- `EXTERNAL_ALERT_LOOKUP_BASE_URL` (default `https://brunoroma.pythonanywhere.com`)

## Endpoint da aplicação

- `GET /api/consultar?registro=80146502070`

Resposta (resumo):

```json
{
  "registro_anvisa": "80146502070",
  "found": true,
  "product": { "numeroRegistro": "80146502070", "nomeProduto": "..." },
  "alerts": [
    {
      "numero_alerta": "4412",
      "link_pesquisa_manual": "https://www.gov.br/anvisa/pt-br/search?...",
      "origem_da_descoberta": "Fonte externa de apoio: brunoroma.pythonanywhere.com",
      "nivel_confianca": "medio"
    }
  ],
  "complaints_or_signals": []
}
```
