"""Compat shim for `python app/app.py` in local dev."""

from pathlib import Path
import sys

if __package__ in (None, ''):
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
