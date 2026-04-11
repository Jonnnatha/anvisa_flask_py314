from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

from app.core.config import REQUEST_TIMEOUT, SSL_VERIFY, USER_AGENT

GOVBR_SEARCH_URL = 'https://www.gov.br/anvisa/pt-br/search'

PRIORITY_TERMS: list[tuple[str, str, int]] = [
    ('manual de serviço', 'manual de serviço', 140),
    ('manual de servico', 'manual de serviço', 140),
    ('instruções de uso', 'instruções de uso / IFU', 140),
    ('instrucoes de uso', 'instruções de uso / IFU', 140),
    ('ifu', 'instruções de uso / IFU', 140),
    ('manual', 'manual', 130),
    ('training', 'treinamento', 120),
    ('treinamento', 'treinamento', 120),
    ('catálogo técnico', 'catálogo técnico', 115),
    ('catalogo tecnico', 'catálogo técnico', 115),
    ('boletim técnico', 'boletim técnico', 110),
    ('boletim tecnico', 'boletim técnico', 110),
    ('field safety notice', 'field safety notice', 135),
    ('field corrective action', 'field corrective action', 135),
    ('recall', 'recall', 130),
    ('nota de fabricante', 'nota de fabricante', 95),
]

GENERIC_NOISE = {
    'notícia',
    'noticias',
    'evento',
    'agenda',
    'ouvidoria',
    'transparência',
    'transparencia',
}


def _clean(value: Any) -> str:
    return str(value or '').strip()


def _safe_domain(href: str) -> bool:
    domain = urlparse(href).netloc.lower()
    return domain.endswith('gov.br') or domain.endswith('anvisa.gov.br')


def _normalize_tokens(*values: str) -> list[str]:
    tokens: list[str] = []
    for value in values:
        cleaned = _clean(value)
        if not cleaned:
            continue
        for token in re.split(r'\s+', cleaned):
            token = token.strip('.,;:()[]{}').casefold()
            if len(token) < 3 or token.isdigit():
                continue
            tokens.append(token)
    return tokens


def _build_queries(registro: str, product: dict[str, Any]) -> list[str]:
    company = _clean((product.get('empresa') or {}).get('razaoSocial'))
    nome_produto = _clean(product.get('nomeProduto'))
    nome_tecnico = _clean(product.get('nomeTecnico'))
    marca = _clean(product.get('marca'))
    modelo = _clean(product.get('modelo'))
    fabricante = _clean(product.get('fabricante')) or company

    base_terms = [t for t in [registro, nome_produto, nome_tecnico, marca, modelo, fabricante] if t]
    compact_base = ' '.join(base_terms)

    query_templates = [
        f'{registro} {nome_produto} manual',
        f'{registro} {nome_produto} instruções de uso',
        f'{fabricante} {modelo} manual de serviço',
        f'{marca} {modelo} IFU',
        f'{fabricante} {modelo} training',
        f'{fabricante} {modelo} recall',
        f'{fabricante} {modelo} field safety notice',
        f'{fabricante} {modelo} field corrective action',
        f'{nome_tecnico} {fabricante} instruções de uso',
        f'{compact_base} catálogo técnico',
        f'{compact_base} boletim técnico',
    ]

    result: list[str] = []
    seen: set[str] = set()
    for query in query_templates:
        q = ' '.join(query.split()).strip()
        if not q:
            continue
        key = q.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(q)

    return result[:8]


def _parse_search_page(search_url: str) -> list[dict[str, str]]:
    headers = {'User-Agent': USER_AGENT, 'Accept': 'text/html,*/*'}
    response = requests.get(search_url, timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY, headers=headers)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    rows: list[dict[str, str]] = []

    for anchor in soup.select('a'):
        href = _clean(anchor.get('href'))
        title = anchor.get_text(' ', strip=True)
        if not href or not title:
            continue
        if '/pt-br/search' in href:
            continue

        if href.startswith('/'):
            href = f'https://www.gov.br{href}'

        if not _safe_domain(href):
            continue

        parent_text = anchor.parent.get_text(' ', strip=True) if anchor.parent else ''
        rows.append(
            {
                'titulo': title,
                'link': href,
                'resumo': parent_text[:380],
                'contexto': f'{title} {parent_text}'.casefold(),
                'fonte': urlparse(href).netloc.lower(),
            }
        )

    return rows


def _classify_and_score(
    row: dict[str, str],
    registro: str,
    product_tokens: list[str],
) -> dict[str, Any] | None:
    context = row['contexto']

    if any(noise in context for noise in GENERIC_NOISE):
        return None

    best_label = ''
    score = 0
    for needle, label, points in PRIORITY_TERMS:
        if needle in context:
            if points > score:
                score = points
                best_label = label

    if score == 0:
        return None

    exact_registration = registro in re.sub(r'\D', '', context)

    token_hits = 0
    for token in set(product_tokens):
        if token and token in context:
            token_hits += 1

    score += min(token_hits * 12, 60)

    if exact_registration:
        score += 90

    confidence = 'baixo'
    if score >= 180:
        confidence = 'alto'
    elif score >= 135:
        confidence = 'medio'

    # Regra de qualidade: só retorna com evidência forte.
    # Forte = registro explícito OU ao menos dois tokens relevantes do produto.
    if not exact_registration and token_hits < 2:
        return None

    if confidence == 'baixo':
        return None

    return {
        'titulo': row['titulo'],
        'fonte': row['fonte'],
        'tipo': best_label or 'documentação técnica',
        'link': row['link'],
        'resumo': row['resumo'],
        'nivel_confianca': confidence,
        'score': score,
    }


def find_related_materials(registro: str, product: dict[str, Any] | None = None) -> dict[str, Any]:
    product = product or {}
    queries = _build_queries(registro, product)

    if not queries:
        return {
            'items': [],
            'warning': 'Nenhum termo suficiente foi encontrado para busca de materiais técnicos.',
            'source': [GOVBR_SEARCH_URL],
        }

    product_tokens = _normalize_tokens(
        product.get('nomeProduto'),
        product.get('nomeTecnico'),
        product.get('marca'),
        product.get('modelo'),
        product.get('fabricante'),
        (product.get('empresa') or {}).get('razaoSocial'),
    )

    ranked: list[dict[str, Any]] = []
    visited_urls: list[str] = []

    for query in queries:
        search_url = f"{GOVBR_SEARCH_URL}?SearchableText={quote_plus(query)}"
        visited_urls.append(search_url)

        try:
            rows = _parse_search_page(search_url)
        except requests.RequestException:
            continue

        for row in rows:
            evaluated = _classify_and_score(row, registro=registro, product_tokens=product_tokens)
            if evaluated:
                ranked.append(evaluated)

    deduped: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    for item in sorted(ranked, key=lambda x: x['score'], reverse=True):
        link = item['link']
        if link in seen_links:
            continue
        seen_links.add(link)
        item.pop('score', None)
        deduped.append(item)

    if not deduped:
        return {
            'items': [],
            'warning': 'Nenhum material técnico público relevante foi encontrado para este produto.',
            'source': visited_urls,
        }

    return {
        'items': deduped[:12],
        'warning': None,
        'source': visited_urls,
    }
