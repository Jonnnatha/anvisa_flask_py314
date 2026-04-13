from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

from app.core.config import REQUEST_TIMEOUT, SSL_VERIFY, USER_AGENT

GOVBR_SEARCH_URL = 'https://www.gov.br/anvisa/pt-br/search'
DUCKDUCKGO_HTML_URL = 'https://duckduckgo.com/html/'

MATERIAL_TYPES: dict[str, tuple[str, ...]] = {
    'manual': (' manual ', ' user manual ', 'operators manual', 'manual do equipamento', 'operation manual'),
    'ifu': ('ifu', 'instructions for use', 'instruções de uso', 'instrucoes de uso'),
    'service_manual': ('service manual', 'manual de serviço', 'manual de servico', 'maintenance manual'),
    'training': ('training', 'treinamento', 'capacitação', 'capacitacao', 'curso técnico'),
    'catalog': ('catalog', 'catálogo técnico', 'catalogo tecnico', 'brochure', 'folheto técnico'),
    'technical_bulletin': ('technical bulletin', 'boletim técnico', 'boletim tecnico', 'service bulletin'),
    'recall': ('recall', 'recolhimento', 'aviso de recolhimento'),
    'safety_notice': ('field safety notice', 'safety notice', 'aviso de segurança', 'aviso de seguranca'),
    'field_corrective_action': ('field corrective action', 'field safety corrective action', 'fsca'),
    'manufacturer_document': ('fabricante', 'manufacturer communication', 'nota técnica do fabricante', 'comunicado do fabricante'),
}

TYPE_PRIORITY = {
    'service_manual': 150,
    'ifu': 145,
    'manual': 138,
    'safety_notice': 138,
    'field_corrective_action': 138,
    'recall': 135,
    'training': 120,
    'technical_bulletin': 120,
    'catalog': 112,
    'manufacturer_document': 100,
}

GENERIC_NOISE = {
    'notícia',
    'noticias',
    'evento',
    'agenda',
    'ouvidoria',
    'transparência',
    'transparencia',
    'carreira',
    'vagas',
    'política de privacidade',
    'termos de uso',
    'institucional',
}

BLOCKED_DOMAINS = {
    'facebook.com',
    'instagram.com',
    'linkedin.com',
    'tiktok.com',
    'youtube.com',
    'wikipedia.org',
    'mercadolivre.com.br',
    'shopee.com.br',
}

BLOCKED_URL_PATTERNS = (
    '/search',
    '/busca',
    '/tag/',
    '/category/',
    '/noticias',
)


@dataclass(frozen=True)
class SearchStrategy:
    name: str
    query: str


def _clean(value: Any) -> str:
    return str(value or '').strip()


def _normalize(value: str) -> str:
    return re.sub(r'\s+', ' ', _clean(value).casefold()).strip()


def _to_ascii(value: str) -> str:
    return ''.join(ch for ch in value.casefold() if ch.isascii())


def _contains_haystack(haystack: str, term: str) -> bool:
    if not term:
        return False
    return term in haystack or _to_ascii(term) in _to_ascii(haystack)


def _safe_domain(href: str) -> bool:
    domain = urlparse(href).netloc.lower()
    return domain.endswith('gov.br') or domain.endswith('anvisa.gov.br')


def _is_blocked_domain(href: str) -> bool:
    domain = urlparse(href).netloc.lower().lstrip('www.')
    return any(domain.endswith(item) for item in BLOCKED_DOMAINS)


def _normalize_tokens(*values: str) -> list[str]:
    tokens: list[str] = []
    for value in values:
        cleaned = _clean(value)
        if not cleaned:
            continue
        for token in re.split(r'\s+', cleaned):
            token = token.strip('.,;:()[]{}').casefold()
            if len(token) < 3:
                continue
            if token.isdigit() and len(token) < 4:
                continue
            tokens.append(token)
    return tokens


def _manufacturer_domain_candidates(product: dict[str, Any]) -> list[str]:
    fabricante = _clean(product.get('fabricante'))
    empresa = _clean((product.get('empresa') or {}).get('razaoSocial'))
    raw = f'{fabricante} {empresa}'.casefold()
    sanitized = re.sub(r'[^a-z0-9 ]+', ' ', raw)
    tokens = [token for token in sanitized.split() if len(token) > 2]
    if not tokens:
        return []
    return [tokens[0], ''.join(tokens[:2]), ''.join(tokens[:3])]


def _product_identity(product: dict[str, Any]) -> dict[str, str]:
    return {
        'registro': _clean(product.get('numeroRegistro') or product.get('numero_registro')),
        'nome_produto': _clean(product.get('nomeProduto') or product.get('nome_produto') or product.get('nome_comercial')),
        'nome_tecnico': _clean(product.get('nomeTecnico') or product.get('nome_tecnico')),
        'marca': _clean(product.get('marca')),
        'modelo': _clean(product.get('modelo')),
        'fabricante': _clean(product.get('fabricante') or (product.get('empresa') or {}).get('razaoSocial')),
        'processo': _clean(product.get('numeroProcesso') or product.get('numero_processo')),
    }


def _add_query(strategies: list[SearchStrategy], seen: set[str], name: str, template: str) -> None:
    query = ' '.join(template.split()).strip()
    if not query:
        return
    key = query.casefold()
    if key in seen:
        return
    seen.add(key)
    strategies.append(SearchStrategy(name=name, query=query))


def _build_queries(registro: str, product: dict[str, Any]) -> list[SearchStrategy]:
    identity = _product_identity(product)
    produto = identity['nome_produto']
    fabricante = identity['fabricante']
    marca = identity['marca']
    modelo = identity['modelo']
    nome_tecnico = identity['nome_tecnico']
    processo = identity['processo']

    bases = [part for part in (produto, fabricante, marca, modelo, nome_tecnico) if part]
    compact_base = ' '.join(bases)

    strategies: list[SearchStrategy] = []
    seen: set[str] = set()

    if produto:
        _add_query(strategies, seen, 'product_manual', f'{produto} manual')
        _add_query(strategies, seen, 'product_ifu', f'{produto} IFU')
        _add_query(strategies, seen, 'product_ifu_pt', f'{produto} instruções de uso')
        _add_query(strategies, seen, 'product_service_manual', f'{produto} service manual')

    if fabricante and modelo:
        _add_query(strategies, seen, 'manufacturer_model_manual', f'{fabricante} {modelo} manual')
        _add_query(strategies, seen, 'manufacturer_model_ifu', f'{fabricante} {modelo} IFU')
        _add_query(strategies, seen, 'manufacturer_model_service_manual', f'{fabricante} {modelo} service manual')
        _add_query(strategies, seen, 'manufacturer_model_training', f'{fabricante} {modelo} training')
        _add_query(strategies, seen, 'manufacturer_model_catalog', f'{fabricante} {modelo} catálogo técnico')
        _add_query(strategies, seen, 'manufacturer_model_bulletin', f'{fabricante} {modelo} technical bulletin')
        _add_query(strategies, seen, 'manufacturer_model_recall', f'{fabricante} {modelo} recall')
        _add_query(strategies, seen, 'manufacturer_model_notice', f'{fabricante} {modelo} field safety notice')
        _add_query(strategies, seen, 'manufacturer_model_fca', f'{fabricante} {modelo} field corrective action')

    if marca and modelo:
        _add_query(strategies, seen, 'brand_model_ifu', f'{marca} {modelo} IFU')
        _add_query(strategies, seen, 'brand_model_service_manual', f'{marca} {modelo} service manual')

    if registro and produto:
        _add_query(strategies, seen, 'registro_produto', f'{registro} {produto}')
        _add_query(strategies, seen, 'registro_produto_manual', f'{registro} {produto} manual')

    if nome_tecnico and fabricante:
        _add_query(strategies, seen, 'technical_name_manufacturer', f'{nome_tecnico} {fabricante} manual')

    if processo:
        _add_query(strategies, seen, 'processo_product', f'{processo} {produto or fabricante} manual')

    if compact_base:
        _add_query(strategies, seen, 'global_safety', f'{compact_base} safety notice')
        _add_query(strategies, seen, 'global_document', f'{compact_base} fabricante comunicado')

    return strategies[:24]


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
                'resumo': parent_text[:400],
                'contexto': _normalize(f'{title} {parent_text} {href}'),
                'fonte': urlparse(href).netloc.lower(),
            }
        )

    return rows


def _parse_duckduckgo_page(query: str) -> list[dict[str, str]]:
    headers = {'User-Agent': USER_AGENT, 'Accept': 'text/html,*/*'}
    response = requests.get(
        DUCKDUCKGO_HTML_URL,
        params={'q': query},
        timeout=REQUEST_TIMEOUT,
        verify=SSL_VERIFY,
        headers=headers,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    rows: list[dict[str, str]] = []

    for block in soup.select('.result'):
        anchor = block.select_one('.result__a')
        if not anchor:
            continue
        href = _clean(anchor.get('href'))
        title = anchor.get_text(' ', strip=True)
        snippet = _clean(block.get_text(' ', strip=True))
        if not href or not title or _is_blocked_domain(href):
            continue
        rows.append(
            {
                'titulo': title,
                'link': href,
                'resumo': snippet[:400],
                'contexto': _normalize(f'{title} {snippet} {href}'),
                'fonte': urlparse(href).netloc.lower(),
            }
        )
    return rows


def _classify_type(context: str) -> str:
    haystack = f' {context} '
    best = 'public_signal'
    best_score = 0
    for material_type, needles in MATERIAL_TYPES.items():
        for needle in needles:
            if _contains_haystack(haystack, needle):
                score = TYPE_PRIORITY.get(material_type, 85)
                if score > best_score:
                    best_score = score
                    best = material_type
    return best


def _score_relevance(
    row: dict[str, str],
    registro: str,
    identity: dict[str, str],
    product_tokens: list[str],
    manufacturer_domains: list[str],
    strategy: SearchStrategy,
) -> dict[str, Any] | None:
    context = row['contexto']
    link = row['link'].casefold()

    if any(noise in context for noise in GENERIC_NOISE):
        return None
    if any(pattern in link for pattern in BLOCKED_URL_PATTERNS):
        return None

    material_type = _classify_type(context)
    score = TYPE_PRIORITY.get(material_type, 82)

    digits_context = re.sub(r'\D', '', context)
    registro_digits = re.sub(r'\D', '', registro)
    exact_registration = bool(registro_digits and registro_digits in digits_context)
    if exact_registration:
        score += 95

    token_hits = 0
    for token in set(product_tokens):
        if token and _contains_haystack(context, token):
            token_hits += 1
    score += min(token_hits * 11, 77)

    # identidade forte = nome + (fabricante/modelo/marca)
    product_hit = _contains_haystack(context, identity.get('nome_produto', '').casefold())
    manufacturer_hit = _contains_haystack(context, identity.get('fabricante', '').casefold())
    model_hit = _contains_haystack(context, identity.get('modelo', '').casefold())
    brand_hit = _contains_haystack(context, identity.get('marca', '').casefold())
    technical_name_hit = _contains_haystack(context, identity.get('nome_tecnico', '').casefold())

    if product_hit:
        score += 34
    if manufacturer_hit:
        score += 24
    if model_hit:
        score += 28
    if brand_hit:
        score += 16
    if technical_name_hit:
        score += 14

    domain = row.get('fonte', '')
    if any(candidate and candidate in domain for candidate in manufacturer_domains):
        score += 30
    if link.endswith('.pdf'):
        score += 18

    if any(keyword in strategy.name for keyword in ('service_manual', 'ifu', 'recall', 'notice', 'fca')):
        score += 8

    strong_relation = exact_registration or (
        (product_hit or technical_name_hit)
        and (manufacturer_hit or model_hit or brand_hit)
        and token_hits >= 2
    ) or (
        manufacturer_hit and model_hit and token_hits >= 3
    )

    if not strong_relation:
        return None

    confidence = 'baixo'
    if score >= 190:
        confidence = 'alto'
    elif score >= 145:
        confidence = 'medio'

    if confidence == 'baixo':
        return None

    return {
        'titulo': row['titulo'],
        'tipo': material_type,
        'fonte': row['fonte'],
        'link': row['link'],
        'resumo': row['resumo'],
        'nivel_confianca': confidence,
        'strategy': strategy.name,
        'score': score,
    }


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for item in sorted(items, key=lambda x: x['score'], reverse=True):
        key = _normalize(item['link'])
        if key in seen_keys:
            continue

        title_key = _normalize(re.sub(r'[^a-zA-Z0-9 ]+', ' ', item['titulo']))
        near_dup = any(title_key and title_key in existing for existing in seen_keys)
        if near_dup:
            continue

        seen_keys.add(key)
        if title_key:
            seen_keys.add(title_key)

        item.pop('score', None)
        item.pop('strategy', None)
        deduped.append(item)

    return deduped


def find_related_materials(registro: str, product: dict[str, Any] | None = None) -> dict[str, Any]:
    product = product or {}
    identity = _product_identity(product)
    queries = _build_queries(registro, product)

    if not queries:
        return {
            'items': [],
            'warning': 'Nenhum termo suficiente foi encontrado para busca de materiais técnicos.',
            'source': [GOVBR_SEARCH_URL],
        }

    product_tokens = _normalize_tokens(
        identity['nome_produto'],
        identity['nome_tecnico'],
        identity['marca'],
        identity['modelo'],
        identity['fabricante'],
        identity['processo'],
    )[:24]
    manufacturer_domains = _manufacturer_domain_candidates(product)

    ranked: list[dict[str, Any]] = []
    visited_urls: list[str] = []

    for strategy in queries:
        search_url = f"{GOVBR_SEARCH_URL}?SearchableText={quote_plus(strategy.query)}"
        visited_urls.append(search_url)

        rows: list[dict[str, str]] = []
        try:
            rows.extend(_parse_search_page(search_url))
        except requests.RequestException:
            pass

        try:
            rows.extend(_parse_duckduckgo_page(strategy.query))
        except requests.RequestException:
            pass

        for row in rows:
            evaluated = _score_relevance(
                row,
                registro=registro,
                identity=identity,
                product_tokens=product_tokens,
                manufacturer_domains=manufacturer_domains,
                strategy=strategy,
            )
            if evaluated:
                ranked.append(evaluated)

    deduped = _dedupe_items(ranked)

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
