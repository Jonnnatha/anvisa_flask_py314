from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

from app.core.config import REQUEST_TIMEOUT, SSL_VERIFY, USER_AGENT

GOVBR_SEARCH_URL = 'https://www.gov.br/anvisa/pt-br/search'
KEYWORDS = [
    'manual',
    'instruções de uso',
    'instrucoes de uso',
    'manual de serviço',
    'manual de servico',
    'treinamento',
    'boletim técnico',
    'boletim tecnico',
    'nota de segurança',
    'nota de seguranca',
    'recall',
    'ação de campo',
    'acao de campo',
    'field safety notice',
    'field corrective action',
]


def _classify(context: str) -> str:
    mapping = [
        ('field corrective action', 'field corrective action'),
        ('field safety notice', 'field safety notice'),
        ('ação de campo', 'ação de campo'),
        ('acao de campo', 'ação de campo'),
        ('recall', 'recall'),
        ('nota de segurança', 'nota de segurança'),
        ('nota de seguranca', 'nota de segurança'),
        ('manual de serviço', 'manual de serviço'),
        ('manual de servico', 'manual de serviço'),
        ('instruções de uso', 'instruções de uso'),
        ('instrucoes de uso', 'instruções de uso'),
        ('manual', 'manual'),
        ('treinamento', 'treinamento'),
        ('boletim técnico', 'boletim técnico'),
        ('boletim tecnico', 'boletim técnico'),
    ]
    for needle, label in mapping:
        if needle in context:
            return label
    return 'material técnico'


def find_related_materials(registro: str, product: dict[str, Any] | None = None) -> dict[str, Any]:
    product = product or {}
    empresa = (product.get('empresa') or {}).get('razaoSocial') or ''
    nome_produto = product.get('nomeProduto') or ''
    nome_tecnico = product.get('nomeTecnico') or ''

    terms = [registro, nome_produto, nome_tecnico, empresa]
    terms = [str(term).strip() for term in terms if str(term).strip()]

    query = quote_plus(f"anvisa {' '.join(terms)} manual recall ação de campo")
    search_url = f'{GOVBR_SEARCH_URL}?SearchableText={query}'

    headers = {'User-Agent': USER_AGENT, 'Accept': 'text/html,*/*'}

    try:
        response = requests.get(search_url, timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY, headers=headers)
        response.raise_for_status()
    except requests.RequestException:
        return {
            'items': [],
            'warning': 'Não foi possível consultar materiais públicos no momento.',
            'source': search_url,
        }

    soup = BeautifulSoup(response.text, 'html.parser')
    candidates: list[dict[str, str]] = []

    for anchor in soup.select('a'):
        href = (anchor.get('href') or '').strip()
        title = anchor.get_text(' ', strip=True)
        if not href or not title or '/pt-br/search' in href:
            continue

        if href.startswith('/'):
            href = f'https://www.gov.br{href}'

        domain = urlparse(href).netloc.lower()
        if 'gov.br' not in domain and 'anvisa.gov.br' not in domain:
            continue

        parent_text = anchor.parent.get_text(' ', strip=True) if anchor.parent else ''
        context = f'{title} {parent_text}'.casefold()

        if not any(keyword in context for keyword in KEYWORDS):
            continue

        if registro not in context and not any(term.casefold() in context for term in terms[1:]):
            continue

        candidates.append(
            {
                'titulo': title,
                'fonte': domain,
                'tipo': _classify(context),
                'link': href,
                'resumo': parent_text[:320],
                'nivel_confianca': 'alto' if registro in context else 'medio',
            }
        )

    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in candidates:
        if item['link'] in seen:
            continue
        seen.add(item['link'])
        unique.append(item)

    if not unique:
        return {
            'items': [],
            'warning': 'Nenhuma evidência pública forte foi encontrada para materiais técnicos desse produto.',
            'source': search_url,
        }

    return {
        'items': unique[:10],
        'warning': None,
        'source': search_url,
    }
