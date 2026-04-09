# Consulta regulatória ANVISA (Python 3.14)

Aplicação web simples em Flask para consultar produtos/equipamentos por **número de registro ANVISA** e tentar buscar alertas de tecnovigilância.

## Stack escolhida

- **Flask 3.1** (leve, estável e compatível com Python 3.14)
- **requests** para integrações HTTP
- **Jinja2 + HTML/CSS** para frontend server-side

## Estrutura

```text
app/
  __init__.py
  routes/main.py
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

## Como executar no VS Code (local)

1. Crie e ative um ambiente virtual Python 3.14:

```bash
python3.14 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows PowerShell
```

2. Instale dependências:

```bash
pip install -r requirements.txt
```

3. Execute a aplicação:

```bash
python run.py
```

4. Abra no navegador:

- http://127.0.0.1:5000

## Comportamento e fallback de robustez

- Entrada única: **número de registro ANVISA**.
- O backend tenta mais de um endpoint/caminho para produto e alertas.
- Se houver erro SSL, o client tenta uma segunda chamada com `verify=False` (apenas fallback prático para ambiente local).
- Se a consulta de alertas falhar por 403/SSL/instabilidade externa:
  - os dados do produto continuam sendo exibidos (quando encontrados),
  - a UI mostra aviso amigável,
  - e apresenta link para consulta manual no portal ANVISA.

## Limitações reais das fontes da ANVISA

- Alguns endpoints públicos podem exigir cabeçalhos, chaves internas ou bloquear por WAF (403).
- Estruturas e rotas de APIs públicas podem mudar sem aviso.
- Dados de tecnovigilância podem não ter correspondência direta/estável por registro em todas as bases.

Por isso, a integração de fontes externas foi isolada em `app/services/` para facilitar manutenção futura.

## Testes

```bash
python -m pytest -q
```
