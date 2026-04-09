from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from app.core.config import PRODUCTS_PAGE_URL, PRODUCT_CACHE_FILE, PRODUCT_CACHE_TTL_HOURS
from app.services.http_client import get

CSV_LINK_RE = re.compile(r'https?://[^\s\"\']+\.csv', re.IGNORECASE)


def _cache_valid(path: Path) -> bool:
    if not path.exists():
        return False
    modified = datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.now() - modified < timedelta(hours=PRODUCT_CACHE_TTL_HOURS)


def _extract_csv_link(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, 'html.parser')
    for a in soup.select('a[href]'):
        href = a.get('href', '').strip()
        if href.lower().endswith('.csv'):
            return href
    m = CSV_LINK_RE.search(html)
    return m.group(0) if m else None


def ensure_products_csv() -> Path:
    if _cache_valid(PRODUCT_CACHE_FILE):
        return PRODUCT_CACHE_FILE

    page = get(PRODUCTS_PAGE_URL)
    csv_url = _extract_csv_link(page.text)
    if not csv_url:
        raise RuntimeError('Não foi possível localizar o link CSV oficial da Anvisa.')

    csv_response = get(csv_url)
    PRODUCT_CACHE_FILE.write_bytes(csv_response.content)
    return PRODUCT_CACHE_FILE


def _normalize(value: str) -> str:
    return re.sub(r'\D', '', value or '')


def _best_key(row: Dict[str, str], candidates: List[str]) -> Optional[str]:
    lowered = {k.lower().strip(): k for k in row.keys()}
    for candidate in candidates:
        for key_lower, original in lowered.items():
            if candidate in key_lower:
                return original
    return None


def _read_rows() -> List[Dict[str, str]]:
    csv_path = ensure_products_csv()
    raw = csv_path.read_bytes()
    for encoding in ('utf-8-sig', 'latin-1', 'cp1252'):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError('Não foi possível decodificar o CSV oficial da Anvisa.')

    reader = csv.DictReader(io.StringIO(text), delimiter=';')
    rows = list(reader)
    if not rows:
        reader = csv.DictReader(io.StringIO(text), delimiter=',')
        rows = list(reader)
    return rows


def find_product_by_registration(registro: str) -> Optional[Dict[str, str]]:
    registro = _normalize(registro)
    rows = _read_rows()
    if not rows:
        return None

    first = rows[0]
    reg_key = _best_key(first, ['registro', 'cadastro'])
    if not reg_key:
        return None

    for row in rows:
        if _normalize(row.get(reg_key, '')) == registro:
            nome_key = _best_key(row, ['nome do produto', 'produto', 'nome'])
            marca_key = _best_key(row, ['marca'])
            modelo_key = _best_key(row, ['modelo'])
            fabricante_key = _best_key(row, ['fabricante'])
            detentor_key = _best_key(row, ['detentor'])
            pais_key = _best_key(row, ['pais'])
            situacao_key = _best_key(row, ['situa'])
            processo_key = _best_key(row, ['processo'])
            risco_key = _best_key(row, ['risco'])

            return {
                'registro_anvisa': registro,
                'nome_produto': row.get(nome_key or '', ''),
                'marca': row.get(marca_key or '', ''),
                'modelo': row.get(modelo_key or '', ''),
                'fabricante': row.get(fabricante_key or '', ''),
                'detentor_registro': row.get(detentor_key or '', ''),
                'pais_fabricacao': row.get(pais_key or '', ''),
                'situacao': row.get(situacao_key or '', ''),
                'processo': row.get(processo_key or '', ''),
                'classificacao_risco': row.get(risco_key or '', ''),
                'raw_fields': row,
            }
    return None
