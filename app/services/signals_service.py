from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

from app.core.config import REQUEST_TIMEOUT, SSL_VERIFY, USER_AGENT

GOVBR_SEARCH_URL = 'https://www.gov.br/anvisa/pt-br/search'


# Busca pública com filtro rígido para evitar links aleatórios.
def find_related_public_signals(registro: str, product: dict[str, Any] | None = None) -> dict[str, Any]:
    terms = {
        registro,
        str((product or {}).get('nomeProduto') or '').strip(),
        str(((product or {}).get('empresa') or {}).get('razaoSocial') or '').strip(),
    }
    terms = {t for t in terms if t}

    query = quote_plus(f'anvisa {registro} recall alerta queixa tecnica')
    search_url = f'{GOVBR_SEARCH_URL}?SearchableText={query}'
    headers = {'User-Agent': USER_AGENT, 'Accept': 'text/html,*/*'}

    try:
        response = requests.get(search_url, timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY, headers=headers)
        response.raise_for_status()
    except requests.RequestException:
        return {
            'items': [],
            'warning': 'Não foi possível consultar sinais públicos neste momento.',
            'source': search_url,
        }

    soup = BeautifulSoup(response.text, 'html.parser')
    items: list[dict[str, str]] = []

    for anchor in soup.select('a'):
        href = (anchor.get('href') or '').strip()
        title = anchor.get_text(' ', strip=True)
        if not href or not title or '/pt-br/search' in href:
            continue

        if href.startswith('/'):
            href = f'https://www.gov.br{href}'

        domain = urlparse(href).netloc.lower()
        if 'gov.br' not in domain:
            continue

        context = (title + ' ' + (anchor.parent.get_text(' ', strip=True) if anchor.parent else '')).lower()
        if not any(term.lower() in context for term in terms):
            continue

        signal_type = 'sinal público'
        if 'recall' in context:
            signal_type = 'recall'
        elif 'ação de campo' in context:
            signal_type = 'ação de campo'
        elif 'queixa' in context:
            signal_type = 'queixa técnica'
        elif 'alerta' in context:
            signal_type = 'alerta'

        items.append(
            {
                'titulo': title,
                'fonte': domain,
                'tipo': signal_type,
                'link': href,
                'resumo': (anchor.parent.get_text(' ', strip=True) if anchor.parent else '')[:280],
                'origem_da_descoberta': 'Busca pública em gov.br/Anvisa com validação por termos do produto',
                'nivel_confianca': 'alto' if registro in context else 'medio',
            }
        )

    unique: list[dict[str, str]] = []
    seen_links: set[str] = set()
    for item in items:
        if item['link'] in seen_links:
            continue
        seen_links.add(item['link'])
        unique.append(item)

    return {
        'items': unique[:8],
        'warning': None,
        'source': search_url,
    }
