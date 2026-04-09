# Consulta regulatória ANVISA (Python 3.14)

Aplicação web em Flask para consulta de equipamentos/produtos pelo **número de registro ANVISA** e tentativa de busca de alertas de tecnovigilância.

## Stack

- Flask 3.1 (backend leve e estável)
- requests 2.32 (integração HTTP)
- Jinja2/HTML/CSS (frontend server-side)

## Estrutura do projeto

```text
app/
  __init__.py
  config.py
  routes/
    main.py
  services/
    http_client.py
    product_service.py
    alert_service.py
    lookup_service.py
  templates/
    base.html
    index.html
  static/
    style.css
run.py
requirements.txt
tests/
  test_lookup.py
```

## Execução local (VS Code)

```bash
python3.14 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows PowerShell

pip install -r requirements.txt
python run.py
```

Abra: `http://127.0.0.1:5000`

## Entrada do usuário

- Campo único: **registro ANVISA**
- Botão: **Consultar**

## Estratégia de robustez (SSL/403/fonte instável)

- O sistema tenta múltiplos endpoints para produto e alertas.
- Erro SSL: fallback opcional para `verify=False` (controlado por ambiente).
- Se alertas falharem por bloqueio/instabilidade, o sistema **não quebra**:
  - mostra dados do produto (se obtidos),
  - informa falha automática,
  - exibe link para consulta manual oficial.

## Variáveis de ambiente opcionais

- `REQUEST_TIMEOUT_SECONDS` (default: `20`)
- `VERIFY_SSL` (`true`/`false`, default: `true`)
- `ALLOW_INSECURE_SSL_FALLBACK` (`true`/`false`, default: `true`)

## Limitações reais das fontes ANVISA

- Endpoints públicos podem ser bloqueados por WAF/403, exigir headers internos ou mudar sem aviso.
- Algumas bases de alertas não trazem correspondência direta por registro em todos os itens.

Por isso, integrações externas foram isoladas em `app/services/` para facilitar manutenção futura.

## Testes

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```
