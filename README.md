# Consulta ANVISA - Flask (Python 3.14)

Versão refatorada para Python 3.14 sem FastAPI, pydantic-core, Rust ou pandas.

## Como rodar

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app\app.py
```

Abra em: http://127.0.0.1:5000

## Rotas
- `/` página principal
- `/api/consultar?registro=10349000912` consulta JSON
