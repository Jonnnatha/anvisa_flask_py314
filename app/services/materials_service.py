from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from app.core.config import (
    MATERIALS_EARLY_STOP_RESULTS,
    MATERIALS_MAX_ROWS_PER_STRATEGY,
    MATERIALS_MAX_SOURCES,
    MATERIALS_MAX_STRATEGIES,
    MATERIALS_MAX_TOTAL_ROWS,
    MATERIALS_REQUEST_TIMEOUT,
    MATERIALS_TOTAL_TIMEOUT,
    SSL_VERIFY,
    USER_AGENT,
)

GOVBR_SEARCH_URL = 'https://www.gov.br/anvisa/pt-br/search'
DUCKDUCKGO_HTML_URL = 'https://duckduckgo.com/html/'
GOOGLE_SEARCH_URL = 'https://www.google.com/search'

MATERIAL_TYPES: dict[str, tuple[str, ...]] = {
    'pdf': ('.pdf', ' pdf ', ' filetype:pdf'),
    'manual': (' manual ', ' user manual ', 'operators manual', 'manual do equipamento', 'operation manual'),
    'ifu': ('ifu', 'instructions for use', 'instruções de uso', 'instrucoes de uso'),
    'service_manual': ('service manual', 'manual de serviço', 'manual de servico', 'maintenance manual'),
    'training': ('training', 'treinamento', 'capacitação', 'capacitacao', 'curso técnico'),
    'complaint': ('reclamação', 'reclamacao', 'complaint', 'consumer complaint', 'queixa técnica', 'queixa tecnica'),
    'forum': ('forum', 'fórum', 'community discussion', 'discussion thread', 'discussão'),
    'catalog': ('catalog', 'catálogo técnico', 'catalogo tecnico', 'brochure', 'folheto técnico'),
    'technical_bulletin': ('technical bulletin', 'boletim técnico', 'boletim tecnico', 'service bulletin'),
    'recall': ('recall', 'recolhimento', 'aviso de recolhimento'),
    'safety_notice': ('field safety notice', 'safety notice', 'aviso de segurança', 'aviso de seguranca'),
    'field_corrective_action': ('field corrective action', 'field safety corrective action', 'fsca'),
    'manufacturer_document': ('fabricante', 'manufacturer communication', 'nota técnica do fabricante', 'comunicado do fabricante'),
    'technical_document': ('technical document', 'documento técnico', 'especificação técnica', 'instruction sheet'),
}

# Ordem de prioridade solicitada: manual > ifu > service_manual > training > catalog > recall ...
TYPE_PRIORITY = {
    'pdf': 166,
    'manual': 160,
    'ifu': 152,
    'service_manual': 144,
    'training': 136,
    'complaint': 132,
    'forum': 124,
    'catalog': 128,
    'recall': 120,
    'safety_notice': 116,
    'field_corrective_action': 114,
    'technical_bulletin': 108,
    'manufacturer_document': 100,
    'technical_document': 96,
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

GENERIC_URL_PATTERNS = (
    '/assuntos',
    '/noticias',
    '/home',
    '/portal',
    '/govbr',
    '/institucional',
    '/categoria',
    '/category',
    '/menu',
)

GENERIC_TITLE_PATTERNS = (
    'assuntos',
    'página inicial',
    'pagina inicial',
    'início',
    'inicio',
    'institucional',
    'notícias',
    'noticias',
    'portal',
)

USEFUL_URL_HINTS = (
    '.pdf',
    'manual',
    'ifu',
    'instruction',
    'service',
    'training',
    'recall',
    'safety',
    'document',
    'uploads',
    'arquivo',
    'download',
    'complaint',
    'forum',
)

QUERY_NOISE_TOKENS = {
    'site',
    'gov',
    'anvisa',
    'manual',
    'ifu',
    'pdf',
    'service',
    'training',
    'recall',
    'forum',
    'reclamação',
    'reclamacao',
    'safety',
    'notice',
    'field',
    'corrective',
    'action',
    'instruções',
    'instrucoes',
    'uso',
}

USEFUL_TERMS = (
    'pdf',
    'manual',
    'instruções de uso',
    'instrucoes de uso',
    'instructions for use',
    'ifu',
    'service manual',
    'training',
    'forum',
    'fórum',
    'reclamação',
    'reclamacao',
    'complaint',
    'recall',
    'safety notice',
    'field corrective action',
    'fsca',
)

MANDATORY_QUERY_SUFFIXES: tuple[tuple[str, str], ...] = (
    ('manual', 'product_manual'),
    ('IFU', 'product_ifu'),
    ('instruções de uso', 'product_ifu_pt'),
    ('service manual', 'product_service_manual'),
    ('training', 'product_training'),
    ('recall', 'product_recall'),
    ('forum', 'product_forum'),
    ('reclamação', 'product_complaint'),
    ('pdf', 'product_pdf'),
)

LOGGER = logging.getLogger(__name__)
MATERIALS_AUTOSEARCH_WARNING = 'Não foi possível concluir a busca automática de materiais nesta consulta.'


MATERIALS_STATUS_MESSAGES = {
    'results_found': '',
    'partial_results': 'A busca encontrou materiais, mas algumas etapas falharam. Revise os diagnósticos abaixo.',
    'search_blocked': 'A fonte de pesquisa bloqueou a consulta automática.',
    'timeout': 'A busca falhou por timeout nesta consulta.',
    'parse_failure': 'O parser não conseguiu interpretar os resultados retornados.',
    'filtered_out': 'A busca encontrou resultados, mas todos foram descartados pelo filtro.',
    'unexpected_error': 'Não foi possível concluir a busca por erro inesperado.',
    'no_results': 'Nenhum material técnico público relevante foi encontrado para este produto.',
}


@dataclass(frozen=True)
class SearchStrategy:
    name: str
    query: str
    layer: int
    intent: str = 'general'


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


def _add_query(
    strategies: list[SearchStrategy],
    seen: set[str],
    name: str,
    template: str,
    layer: int,
    intent: str = 'general',
) -> None:
    query = ' '.join(template.split()).strip()
    if not query:
        return
    key = query.casefold()
    if key in seen:
        return
    seen.add(key)
    strategies.append(SearchStrategy(name=name, query=query, layer=layer, intent=intent))


def _build_queries(registro: str, product: dict[str, Any]) -> list[SearchStrategy]:
    identity = _product_identity(product)
    produto = identity['nome_produto']
    fabricante = identity['fabricante']
    marca = identity['marca']
    modelo = identity['modelo']
    nome_tecnico = identity['nome_tecnico']
    processo = identity['processo']

    if not produto and marca and modelo:
        produto = f'{marca} {modelo}'

    strategies: list[SearchStrategy] = []
    seen: set[str] = set()

    # Camada 1: ancoragem forte no nome do produto.
    if produto:
        for suffix, name in MANDATORY_QUERY_SUFFIXES:
            _add_query(strategies, seen, name, f'{produto} {suffix}', layer=1)
        for suffix, name in (
            ('safety notice', 'product_safety_notice'),
            ('field corrective action', 'product_fca'),
            ('catálogo técnico', 'product_catalog'),
            ('boletim técnico', 'product_technical_bulletin'),
        ):
            _add_query(strategies, seen, name, f'{produto} {suffix}', layer=1)

    # Camada 2: combinações com fabricante/modelo/marca.
    if fabricante and produto:
        _add_query(strategies, seen, 'manufacturer_product_manual', f'{fabricante} {produto} manual', layer=2)
        _add_query(strategies, seen, 'manufacturer_product_ifu', f'{fabricante} {produto} IFU', layer=2)

    if fabricante and modelo:
        for suffix, name in (
            ('manual', 'manufacturer_model_manual'),
            ('IFU', 'manufacturer_model_ifu'),
            ('service manual', 'manufacturer_model_service_manual'),
            ('training', 'manufacturer_model_training'),
            ('catálogo técnico', 'manufacturer_model_catalog'),
            ('technical bulletin', 'manufacturer_model_bulletin'),
            ('recall', 'manufacturer_model_recall'),
            ('field safety notice', 'manufacturer_model_notice'),
            ('field corrective action', 'manufacturer_model_fca'),
        ):
            _add_query(strategies, seen, name, f'{fabricante} {modelo} {suffix}', layer=2)

    if marca and modelo:
        _add_query(strategies, seen, 'brand_model_ifu', f'{marca} {modelo} IFU', layer=2)
        _add_query(strategies, seen, 'brand_model_service_manual', f'{marca} {modelo} service manual', layer=2)

    # Camada 3: pivôs regulatórios/técnicos (registro, nome técnico, processo).
    if registro and produto:
        _add_query(strategies, seen, 'registro_produto', f'{registro} {produto}', layer=3)
        _add_query(strategies, seen, 'registro_produto_manual', f'{registro} {produto} manual', layer=3)

    if nome_tecnico and fabricante:
        _add_query(strategies, seen, 'technical_name_manufacturer', f'{nome_tecnico} {fabricante} manual', layer=3)

    if processo:
        _add_query(strategies, seen, 'processo_product', f'{processo} {produto or fabricante} manual', layer=3)

    if produto:
        # Busca ancorada na ANVISA, simulando comportamento de pesquisa manual.
        _add_query(strategies, seen, 'anvisa_product_manual', f'site:gov.br/anvisa "{produto}" manual', layer=3)
        _add_query(strategies, seen, 'anvisa_product_ifu', f'site:gov.br/anvisa "{produto}" instruções de uso', layer=3)

    return strategies[:30]


def _build_adaptive_queries(
    registro: str,
    product: dict[str, Any],
    max_strategies: int,
) -> tuple[list[SearchStrategy], dict[str, Any]]:
    base = _build_queries(registro, product)
    identity = _product_identity(product)
    strategies: list[SearchStrategy] = []
    seen: set[str] = set()

    anchors = [
        identity.get('nome_produto', ''),
        identity.get('fabricante', ''),
        identity.get('modelo', ''),
        identity.get('marca', ''),
        identity.get('nome_tecnico', ''),
    ]
    anchor_strength = sum(1 for anchor in anchors if _clean(anchor))

    for item in base:
        _add_query(strategies, seen, item.name, item.query, item.layer, item.intent)

    produto = identity.get('nome_produto', '')
    fabricante = identity.get('fabricante', '')
    modelo = identity.get('modelo', '')
    marca = identity.get('marca', '')
    processo = identity.get('processo', '')
    nome_tecnico = identity.get('nome_tecnico', '')

    if produto:
        _add_query(strategies, seen, 'adaptive_anchor_manual_pdf', f'"{produto}" manual pdf', 1, 'manual')
        _add_query(strategies, seen, 'adaptive_anchor_ifu_pdf', f'"{produto}" IFU pdf', 1, 'ifu')
        _add_query(strategies, seen, 'adaptive_anchor_service', f'"{produto}" "service manual"', 2, 'service_manual')
        _add_query(strategies, seen, 'adaptive_anchor_training', f'"{produto}" training technical', 2, 'training')
        _add_query(strategies, seen, 'adaptive_anchor_recall', f'"{produto}" recall safety notice', 2, 'recall')

    if fabricante and produto:
        _add_query(strategies, seen, 'adaptive_manufacturer_document', f'"{fabricante}" "{produto}" documentation', 2, 'manufacturer_document')
        _add_query(strategies, seen, 'adaptive_manufacturer_support', f'"{fabricante}" "{produto}" support manual', 2, 'manual')

    if fabricante and modelo:
        _add_query(strategies, seen, 'adaptive_manufacturer_model_manual', f'"{fabricante}" "{modelo}" manual pdf', 2, 'manual')
        _add_query(strategies, seen, 'adaptive_manufacturer_model_service', f'"{fabricante}" "{modelo}" service manual', 2, 'service_manual')

    if marca and modelo:
        _add_query(strategies, seen, 'adaptive_brand_model_ifu', f'"{marca}" "{modelo}" IFU', 2, 'ifu')

    if processo:
        _add_query(strategies, seen, 'adaptive_processo', f'"{processo}" "{produto or fabricante}"', 3, 'technical_document')

    if nome_tecnico and fabricante:
        _add_query(strategies, seen, 'adaptive_nome_tecnico', f'"{nome_tecnico}" "{fabricante}" catalog', 3, 'catalog')

    if anchor_strength <= 2 and produto:
        _add_query(strategies, seen, 'adaptive_broad_manual', f'{produto} technical document', 3, 'technical_document')
        _add_query(strategies, seen, 'adaptive_broad_forum', f'{produto} forum complaint', 3, 'forum')

    query_metadata = {
        'anchor_strength': anchor_strength,
        'anchors': {
            'nome_produto': bool(produto),
            'fabricante': bool(fabricante),
            'modelo': bool(modelo),
            'marca': bool(marca),
            'nome_tecnico': bool(nome_tecnico),
            'numero_processo': bool(processo),
        },
    }

    return strategies[:max_strategies], query_metadata


def _build_recommended_queries(identity: dict[str, str]) -> list[str]:
    produto = identity.get('nome_produto', '')
    fabricante = identity.get('fabricante', '')
    modelo = identity.get('modelo', '')
    suggestions: list[str] = []

    if produto:
        suggestions.extend(
            [
                f'{produto} manual',
                f'{produto} IFU',
                f'{produto} instruções de uso',
                f'{produto} service manual',
                f'{produto} training',
                f'{produto} recall',
                f'{produto} forum',
                f'{produto} reclamação',
                f'{produto} pdf',
            ]
        )
    if fabricante and produto:
        suggestions.append(f'{fabricante} {produto} IFU')
    if fabricante and produto:
        suggestions.append(f'{fabricante} {produto} manual')
    if fabricante and modelo:
        suggestions.append(f'{fabricante} {modelo} manual')

    seen: set[str] = set()
    deduped: list[str] = []
    for suggestion in suggestions:
        query = ' '.join(suggestion.split()).strip()
        if not query:
            continue
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(query)
    return deduped[:8]


def _query_anchor_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    for token in re.split(r'[^a-zA-Z0-9]+', _to_ascii(query)):
        clean = token.strip().casefold()
        if len(clean) < 4:
            continue
        if clean in QUERY_NOISE_TOKENS:
            continue
        tokens.append(clean)
    return list(dict.fromkeys(tokens))


def _parse_search_page(search_url: str, query: str) -> dict[str, Any]:
    headers = {'User-Agent': USER_AGENT, 'Accept': 'text/html,*/*'}
    response = requests.get(search_url, timeout=MATERIALS_REQUEST_TIMEOUT, verify=SSL_VERIFY, headers=headers)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    rows: list[dict[str, str]] = []
    anchors_found = 0
    anchor_tokens = _query_anchor_tokens(query)

    for anchor in soup.select('a'):
        anchors_found += 1
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
        normalized_blob = _normalize(f'{title} {parent_text} {href}')
        has_query_anchor = any(_contains_haystack(normalized_blob, token) for token in anchor_tokens) if anchor_tokens else False
        has_technical_signal = _has_useful_term(title, parent_text, href)
        if anchor_tokens and not has_query_anchor and not has_technical_signal:
            continue
        if any(pattern in href.casefold() for pattern in ('/pt-br/search', '/assuntos', '/menu')):
            continue

        rows.append(
            {
                'titulo': title,
                'link': href,
                'resumo': parent_text[:400],
                'contexto': normalized_blob,
                'fonte': urlparse(href).netloc.lower(),
            }
        )

    return {'rows': rows, 'anchors_found': anchors_found}


def _parse_duckduckgo_page(query: str) -> dict[str, Any]:
    headers = {'User-Agent': USER_AGENT, 'Accept': 'text/html,*/*'}
    response = requests.get(
        DUCKDUCKGO_HTML_URL,
        params={'q': query},
        timeout=MATERIALS_REQUEST_TIMEOUT,
        verify=SSL_VERIFY,
        headers=headers,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    rows: list[dict[str, str]] = []
    blocks_found = 0

    for block in soup.select('.result'):
        blocks_found += 1
        anchor = block.select_one('.result__a')
        if not anchor:
            continue
        href = _clean(anchor.get('href'))
        title = anchor.get_text(' ', strip=True)
        snippet = _clean(block.get_text(' ', strip=True))
        if href.startswith('//duckduckgo.com/l/?'):
            parsed_duck = urlparse(f'https:{href}')
            resolved = parse_qs(parsed_duck.query).get('uddg', [''])[0]
            href = _clean(unquote(resolved))
        elif href.startswith('https://duckduckgo.com/l/?'):
            parsed_duck = urlparse(href)
            resolved = parse_qs(parsed_duck.query).get('uddg', [''])[0]
            href = _clean(unquote(resolved))
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
    return {'rows': rows, 'blocks_found': blocks_found}


def _parse_google_page(query: str) -> dict[str, Any]:
    headers = {'User-Agent': USER_AGENT, 'Accept': 'text/html,*/*', 'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8'}
    response = requests.get(
        GOOGLE_SEARCH_URL,
        params={'q': query, 'num': 10, 'hl': 'pt-BR'},
        timeout=MATERIALS_REQUEST_TIMEOUT,
        verify=SSL_VERIFY,
        headers=headers,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    rows: list[dict[str, str]] = []
    blocks_found = 0

    for block in soup.select('div.g'):
        blocks_found += 1
        anchor = block.select_one('a[href]')
        title_node = block.select_one('h3')
        snippet_node = block.select_one('div.VwiC3b, span.aCOpRe, div[data-sncf]')
        if not anchor or not title_node:
            continue
        href = _clean(anchor.get('href'))
        title = _clean(title_node.get_text(' ', strip=True))
        snippet = _clean(snippet_node.get_text(' ', strip=True)) if snippet_node else ''
        if not href or not title:
            continue
        if href.startswith('/url?'):
            parsed_google = urlparse(href)
            extracted = parse_qs(parsed_google.query).get('q', [''])[0]
            href = _clean(extracted)
        if href.startswith('/search'):
            continue
        if href.startswith('/'):
            href = f'https://www.google.com{href}'
        if _is_blocked_domain(href):
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

    return {'rows': rows, 'blocks_found': blocks_found}


def _classify_type(context: str) -> str:
    haystack = f' {context} '
    best = 'possible_material'
    best_score = 0
    for material_type, needles in MATERIAL_TYPES.items():
        for needle in needles:
            if _contains_haystack(haystack, needle):
                score = TYPE_PRIORITY.get(material_type, 85)
                if score > best_score:
                    best_score = score
                    best = material_type
    return best


def _domain_relevance_score(domain: str, manufacturer_domains: list[str]) -> int:
    normalized = _clean(domain).lower()
    if not normalized:
        return 0
    if normalized.endswith('anvisa.gov.br') or normalized.endswith('gov.br'):
        return 90
    if any(candidate and candidate in normalized for candidate in manufacturer_domains):
        return 76
    if any(token in normalized for token in ('docs', 'manual', 'support', 'technical', 'product')):
        return 52
    if normalized.endswith('.gov') or normalized.endswith('.edu'):
        return 45
    return 22


def _has_useful_term(*texts: str) -> bool:
    haystack = ' '.join(_normalize(text) for text in texts if text)
    return any(_contains_haystack(haystack, term) for term in USEFUL_TERMS)


def _url_signal(link: str) -> dict[str, Any]:
    normalized = _clean(link).casefold()
    parsed = urlparse(normalized)
    path = parsed.path or ''
    query = parsed.query or ''
    path_query = f'{path}?{query}'

    useful_hits = sum(1 for hint in USEFUL_URL_HINTS if hint in path_query)
    generic_hits = sum(1 for hint in GENERIC_URL_PATTERNS if hint in path_query)
    path_segments = [segment for segment in path.split('/') if segment]
    root_like = len(path_segments) <= 1
    looks_document = any(ext in path for ext in ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'))
    looks_navigation = root_like or generic_hits > 0

    return {
        'useful_hits': useful_hits,
        'generic_hits': generic_hits,
        'root_like': root_like,
        'looks_document': looks_document,
        'looks_navigation': looks_navigation,
    }


def _score_relevance(
    row: dict[str, str],
    registro: str,
    identity: dict[str, str],
    product_tokens: list[str],
    manufacturer_domains: list[str],
    strategy: SearchStrategy,
) -> dict[str, Any] | None:
    context = row['contexto']
    title = _normalize(row.get('titulo', ''))
    snippet = _normalize(row.get('resumo', ''))
    link = row['link'].casefold()
    url_signal = _url_signal(link)
    is_pdf = link.endswith('.pdf') or '.pdf?' in link or '/pdf/' in link

    material_type = _classify_type(context)
    if is_pdf and material_type == 'possible_material':
        material_type = 'pdf'
    score = TYPE_PRIORITY.get(material_type, 82)
    if any(noise in context for noise in GENERIC_NOISE):
        score -= 16
    if any(pattern in link for pattern in BLOCKED_URL_PATTERNS):
        score -= 18
    if url_signal['generic_hits']:
        score -= min(26, 8 * int(url_signal['generic_hits']))
    if url_signal['root_like'] and not is_pdf:
        score -= 12
    if url_signal['useful_hits']:
        score += min(20, 6 * int(url_signal['useful_hits']))
    if url_signal['looks_document']:
        score += 14

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

    normalized_product_name = _normalize(identity.get('nome_produto', ''))
    normalized_manufacturer = _normalize(identity.get('fabricante', ''))
    normalized_model = _normalize(identity.get('modelo', ''))
    normalized_brand = _normalize(identity.get('marca', ''))
    normalized_technical_name = _normalize(identity.get('nome_tecnico', ''))

    product_hit = _contains_haystack(context, normalized_product_name)
    manufacturer_hit = _contains_haystack(context, normalized_manufacturer)
    model_hit = _contains_haystack(context, normalized_model)
    brand_hit = _contains_haystack(context, normalized_brand)
    technical_name_hit = _contains_haystack(context, normalized_technical_name)
    product_in_title = _contains_haystack(title, normalized_product_name)
    product_in_snippet = _contains_haystack(snippet, normalized_product_name)
    manufacturer_in_title_or_snippet = _contains_haystack(f'{title} {snippet}', normalized_manufacturer)
    model_in_title_or_snippet = _contains_haystack(f'{title} {snippet}', normalized_model)
    useful_term_in_text = _has_useful_term(title, snippet)
    useful_term_in_url = bool(url_signal['useful_hits']) or is_pdf
    generic_title = any(pattern in title for pattern in GENERIC_TITLE_PATTERNS)
    title_or_snippet_has_anchor = bool(
        product_in_title or product_in_snippet or manufacturer_in_title_or_snippet or model_in_title_or_snippet
    )

    if product_hit:
        score += 36
    if manufacturer_hit:
        score += 24
    if model_hit:
        score += 28
    if brand_hit:
        score += 16
    if technical_name_hit:
        score += 14

    domain = row.get('fonte', '')
    domain_score = _domain_relevance_score(domain, manufacturer_domains)
    score += domain_score
    if is_pdf:
        score += 18
    if product_in_title:
        score += 42
    elif product_in_snippet:
        score += 18
    if manufacturer_in_title_or_snippet:
        score += 16
    if model_in_title_or_snippet:
        score += 18
    if useful_term_in_text:
        score += 30

    # Consultas da camada 1 têm maior peso e não devem falhar cedo.
    if strategy.layer == 1:
        score += 14
    elif strategy.layer == 2:
        score += 8
    if strategy.intent and strategy.intent in material_type:
        score += 12

    condition_a = product_in_title and useful_term_in_text
    condition_b = manufacturer_in_title_or_snippet and (
        product_in_title or product_in_snippet or model_in_title_or_snippet
    )
    condition_c = domain_score >= 52 and (
        product_hit
        or technical_name_hit
        or (model_hit and (manufacturer_hit or brand_hit))
        or token_hits >= 3
    )
    strong_relation = exact_registration or condition_a or condition_b or condition_c

    generic_navigation_page = bool(
        (url_signal['looks_navigation'] or generic_title)
        and not is_pdf
        and not useful_term_in_url
        and not useful_term_in_text
    )
    if generic_navigation_page and not title_or_snippet_has_anchor:
        row['discard_reason'] = 'generic_navigation_page'
        return None

    if generic_title and not title_or_snippet_has_anchor and not useful_term_in_url:
        row['discard_reason'] = 'generic_title_without_anchor'
        return None

    technical_signal_present = bool(
        useful_term_in_text
        or useful_term_in_url
        or material_type != 'possible_material'
        or (title_or_snippet_has_anchor and not url_signal['looks_navigation'])
    )
    if not technical_signal_present:
        row['discard_reason'] = 'missing_technical_signal'
        return None

    if not strong_relation:
        minimal_relation = (
            product_hit
            or model_hit
            or technical_name_hit
            or token_hits >= 2
            or (manufacturer_hit and useful_term_in_text)
            or (product_in_title and useful_term_in_text)
            or (manufacturer_in_title_or_snippet and product_in_snippet)
            or (useful_term_in_text and (manufacturer_hit or model_hit))
            or (title_or_snippet_has_anchor and useful_term_in_url)
        )
        if not minimal_relation:
            row['discard_reason'] = 'weak_relation'
            if (useful_term_in_text or useful_term_in_url) and (token_hits >= 1 or manufacturer_hit or model_hit):
                score += 6
            else:
                return None
        score += 10

    plausible_candidate = bool(
        product_in_title
        or product_in_snippet
        or (
            useful_term_in_text
            and (product_hit or manufacturer_hit or model_hit or token_hits >= 2)
        )
        or (domain_score >= 52 and (product_hit or model_hit or manufacturer_hit))
        or (title_or_snippet_has_anchor and useful_term_in_url)
    )

    if not strong_relation and plausible_candidate:
        score += 12

    confidence = 'baixo'
    if score >= 188:
        confidence = 'alto'
    elif score >= 118:
        confidence = 'medio'

    if score < 50 and not plausible_candidate:
        row['discard_reason'] = 'low_confidence'
        return None

    item_type = material_type
    if score < 92 or (not strong_relation and plausible_candidate):
        item_type = 'possible_material'
        if confidence == 'alto':
            confidence = 'medio'

    return {
        'titulo': row['titulo'],
        'tipo': item_type,
        'is_pdf': is_pdf,
        'fonte': row['fonte'],
        'link': row['link'],
        'resumo': row['resumo'],
        'nivel_confianca': confidence,
        'strategy': strategy.name,
        'score': score,
        'strong_relation': strong_relation,
        'strategy_layer': strategy.layer,
    }


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    seen_title_domain: set[str] = set()

    for item in sorted(items, key=lambda x: x.get('score', 0), reverse=True):
        parsed = urlparse(item['link'])
        clean_path = re.sub(r'/+', '/', parsed.path.rstrip('/'))
        link_key = _normalize(f'{parsed.scheme}://{parsed.netloc}{clean_path}')
        if link_key in seen_links:
            continue

        title_key = _normalize(re.sub(r'[^a-zA-Z0-9 ]+', ' ', item['titulo']))
        title_domain_key = f"{item.get('fonte', '')}|{title_key}"
        if title_key and title_domain_key in seen_title_domain:
            continue

        seen_links.add(link_key)
        if title_key:
            seen_title_domain.add(title_domain_key)

        item.pop('score', None)
        item.pop('strategy', None)
        item.pop('strong_relation', None)
        deduped.append(item)

    return deduped


def _fallback_from_rows(rows: list[dict[str, str]], identity: dict[str, str]) -> list[dict[str, Any]]:
    fallback_items: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    product_name = _normalize(identity.get('nome_produto', ''))
    manufacturer = _normalize(identity.get('fabricante', ''))
    for row in rows:
        title = row.get('titulo', '')
        snippet = row.get('resumo', '')
        link = row.get('link', '')
        if not link:
            continue
        if link in seen_links:
            continue
        normalized_text = _normalize(f'{title} {snippet}')
        url_signal = _url_signal(link)
        plausible = bool(
            _contains_haystack(normalized_text, product_name)
            or (
                _contains_haystack(normalized_text, manufacturer)
                and _contains_haystack(normalized_text, product_name)
            )
            or (_has_useful_term(title, snippet, link) and url_signal['generic_hits'] == 0)
        )
        if not plausible:
            continue
        if url_signal['looks_navigation'] and not url_signal['looks_document']:
            continue
        seen_links.add(link)
        material_type = _classify_type(_normalize(f'{title} {snippet} {link}'))
        is_pdf = link.lower().endswith('.pdf') or '.pdf?' in link.lower() or '/pdf/' in link.lower()
        if is_pdf and material_type == 'possible_material':
            material_type = 'pdf'
        fallback_items.append(
            {
                'titulo': title or 'Resultado público',
                'tipo': material_type,
                'is_pdf': is_pdf,
                'fonte': row.get('fonte') or urlparse(link).netloc.lower(),
                'link': link,
                'resumo': snippet,
                'nivel_confianca': 'baixo',
                'score': 50,
            }
        )
    return fallback_items


def _strategy_rank_bonus(feedback: dict[str, dict[str, Any]], strategy: SearchStrategy) -> int:
    bucket = feedback.get(strategy.intent, {})
    accepted = int(bucket.get('accepted', 0))
    queries = int(bucket.get('queries', 0))
    if not queries:
        return 0
    hit_rate = accepted / queries
    if hit_rate >= 1.5:
        return 12
    if hit_rate >= 1:
        return 8
    return 0


def find_related_materials(registro: str, product: dict[str, Any] | None = None) -> dict[str, Any]:
    product = product or {}
    identity = _product_identity(product)
    started_at = time.perf_counter()

    recommended_queries = _build_recommended_queries(identity)
    recommended_searches = [
        {'query': query, 'url': f'https://www.google.com/search?q={quote_plus(query)}'}
        for query in recommended_queries
    ]

    try:
        queries, query_metadata = _build_adaptive_queries(registro, product, MATERIALS_MAX_STRATEGIES)
    except Exception as exc:
        LOGGER.exception('materials.query_build.error registro=%s erro=%s', registro, exc)
        diagnostics = {
            'search_status': 'unexpected_error',
            'errors': [{'step': 'build_query', 'type': 'erro_ao_montar_query', 'message': str(exc)}],
            'queries_used': [],
            'sources_checked': [],
            'raw_results_count': 0,
            'accepted_results_count': 0,
            'discarded_results_count': 0,
            'discard_reasons': {},
            'duration_ms': int((time.perf_counter() - started_at) * 1000),
            'query_metadata': {},
            'strategies': [],
        }
        return {
            'items': [],
            'status': 'unexpected_error',
            'warning': MATERIALS_STATUS_MESSAGES['unexpected_error'],
            'source': [],
            'recommended_searches': recommended_searches,
            'diagnostics': diagnostics,
        }

    if not queries:
        diagnostics = {
            'search_status': 'no_results',
            'errors': [{'step': 'build_query', 'type': 'erro_ao_montar_query', 'message': 'missing_query_terms'}],
            'queries_used': [],
            'sources_checked': [],
            'raw_results_count': 0,
            'accepted_results_count': 0,
            'discarded_results_count': 0,
            'discard_reasons': {},
            'duration_ms': int((time.perf_counter() - started_at) * 1000),
            'query_metadata': query_metadata,
            'strategies': [],
        }
        return {
            'items': [],
            'status': 'no_results',
            'warning': 'Nenhum termo suficiente foi encontrado para busca de materiais técnicos.',
            'source': [GOVBR_SEARCH_URL],
            'recommended_searches': recommended_searches,
            'diagnostics': diagnostics,
        }

    product_tokens = _normalize_tokens(
        identity['nome_produto'],
        identity['nome_tecnico'],
        identity['marca'],
        identity['modelo'],
        identity['fabricante'],
        identity['processo'],
    )[:28]
    manufacturer_domains = _manufacturer_domain_candidates(product)

    ranked: list[dict[str, Any]] = []
    visited_urls: list[str] = []
    checked_sources: set[str] = set()
    deadline = started_at + MATERIALS_TOTAL_TIMEOUT
    total_rows_processed = 0
    total_rows_collected = 0
    total_filtered_out = 0
    parse_failures = 0
    blocked_sources = 0
    timeout_events = 0
    strategy_logs: list[dict[str, Any]] = []
    discard_reasons: dict[str, int] = {}
    fallback_rows: list[dict[str, str]] = []
    strategy_feedback: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    unexpected_failure = False
    dedupe_removed_count = 0

    def register_error(step: str, error_type: str, message: str, strategy_name: str, source_name: str | None = None) -> None:
        errors.append(
            {
                'step': step,
                'type': error_type,
                'source': source_name,
                'strategy': strategy_name,
                'message': message,
            }
        )

    source_runners = (
        ('govbr', lambda q: _parse_search_page(f"{GOVBR_SEARCH_URL}?SearchableText={quote_plus(q)}", q), 8),
        ('google_search', _parse_google_page, 10),
        ('duckduckgo_search', _parse_duckduckgo_page, 10),
    )

    for strategy in queries:
        strategy_log: dict[str, Any] = {
            'strategy': strategy.name,
            'query': strategy.query,
            'layer': strategy.layer,
            'intent': strategy.intent,
            'sources': [],
            'raw_rows': 0,
            'filtered_out': 0,
            'accepted': 0,
        }
        LOGGER.info('materials.query.built registro=%s strategy=%s query="%s"', registro, strategy.name, strategy.query)
        if time.perf_counter() >= deadline:
            timeout_events += 1
            strategy_log['aborted'] = 'deadline_reached'
            register_error('search_loop', 'timeout', 'Tempo total da busca excedido durante loop de estratégias.', strategy.name)
            strategy_logs.append(strategy_log)
            LOGGER.warning('materials.timeout registro=%s etapa=strategy_loop strategy=%s', registro, strategy.name)
            break
        if len(visited_urls) >= MATERIALS_MAX_SOURCES:
            strategy_log['aborted'] = 'source_limit_reached'
            strategy_logs.append(strategy_log)
            LOGGER.info('materials.limit_sources registro=%s limite=%s', registro, MATERIALS_MAX_SOURCES)
            break

        rows: list[dict[str, str]] = []

        for source_name, runner, row_cap in source_runners:
            source_started = time.perf_counter()
            checked_sources.add(source_name)
            try:
                result = runner(strategy.query)
                source_rows = result.get('rows', [])
                rows.extend(source_rows[:row_cap])
                source_log = {
                    'source': source_name,
                    'status': 'ok',
                    'rows': len(source_rows),
                    'duration_ms': int((time.perf_counter() - source_started) * 1000),
                }
                if source_name == 'govbr':
                    source_log['anchors'] = result.get('anchors_found', 0)
                    visited_urls.append(f"{GOVBR_SEARCH_URL}?SearchableText={quote_plus(strategy.query)}")
                    if source_log['anchors'] > 0 and not source_rows:
                        parse_failures += 1
                        source_log['status'] = 'parse_failure'
                        source_log['detail'] = 'anchors_without_valid_rows'
                        register_error('parse_source', 'parser_not_found_results', 'Parser encontrou âncoras, mas sem linhas válidas.', strategy.name, source_name)
                else:
                    source_log['blocks'] = result.get('blocks_found', 0)
                    if source_name == 'google_search':
                        visited_urls.append(f'{GOOGLE_SEARCH_URL}?q={quote_plus(strategy.query)}')
                    elif source_name == 'duckduckgo_search':
                        visited_urls.append(f'{DUCKDUCKGO_HTML_URL}?q={quote_plus(strategy.query)}')
                    if source_log['blocks'] > 0 and not source_rows:
                        parse_failures += 1
                        source_log['status'] = 'parse_failure'
                        source_log['detail'] = 'blocks_without_valid_rows'
                        register_error('parse_source', 'parser_not_found_results', 'Parser encontrou blocos, mas sem linhas válidas.', strategy.name, source_name)
                strategy_log['sources'].append(source_log)
                LOGGER.info(
                    'materials.source.done registro=%s strategy=%s fonte=%s rows=%s duracao_ms=%s',
                    registro,
                    strategy.name,
                    source_name,
                    len(source_rows),
                    source_log['duration_ms'],
                )
            except requests.Timeout:
                timeout_events += 1
                register_error('query_source', 'timeout', f'Timeout ao consultar {source_name}.', strategy.name, source_name)
                strategy_log['sources'].append(
                    {'source': source_name, 'status': 'timeout', 'rows': 0, 'duration_ms': int((time.perf_counter() - source_started) * 1000)}
                )
                LOGGER.warning('materials.timeout registro=%s fonte=%s strategy=%s', registro, source_name, strategy.name)
            except requests.RequestException as exc:
                blocked_sources += 1
                register_error('query_source', 'source_blocked', f'Falha ao consultar {source_name}: {exc}', strategy.name, source_name)
                strategy_log['sources'].append(
                    {
                        'source': source_name,
                        'status': 'blocked_source',
                        'rows': 0,
                        'error': str(exc),
                        'duration_ms': int((time.perf_counter() - source_started) * 1000),
                    }
                )
                LOGGER.warning('materials.error registro=%s fonte=%s strategy=%s erro=%s', registro, source_name, strategy.name, exc)
            except Exception as exc:
                unexpected_failure = True
                register_error('query_source', 'unexpected_error', f'Erro inesperado ao consultar {source_name}: {exc}', strategy.name, source_name)
                strategy_log['sources'].append(
                    {
                        'source': source_name,
                        'status': 'unexpected_error',
                        'rows': 0,
                        'error': str(exc),
                        'duration_ms': int((time.perf_counter() - source_started) * 1000),
                    }
                )
                LOGGER.exception('materials.unexpected registro=%s fonte=%s strategy=%s erro=%s', registro, source_name, strategy.name, exc)

        strategy_log['raw_rows'] = len(rows)
        total_rows_collected += len(rows)
        fallback_rows.extend(rows)
        LOGGER.info('materials.strategy.collected registro=%s strategy=%s rows=%s', registro, strategy.name, len(rows))

        for row in rows[:MATERIALS_MAX_ROWS_PER_STRATEGY]:
            if time.perf_counter() >= deadline:
                timeout_events += 1
                register_error('score_rows', 'timeout', 'Tempo total da busca excedido durante avaliação de resultados.', strategy.name)
                LOGGER.warning('materials.timeout registro=%s etapa=row_loop strategy=%s', registro, strategy.name)
                break
            if total_rows_processed >= MATERIALS_MAX_TOTAL_ROWS:
                LOGGER.info('materials.limit_rows registro=%s limite=%s', registro, MATERIALS_MAX_TOTAL_ROWS)
                break
            evaluated = _score_relevance(
                row,
                registro=registro,
                identity=identity,
                product_tokens=product_tokens,
                manufacturer_domains=manufacturer_domains,
                strategy=strategy,
            )
            if evaluated:
                evaluated['score'] += _strategy_rank_bonus(strategy_feedback, strategy)
                ranked.append(evaluated)
                strategy_log['accepted'] += 1
            else:
                strategy_log['filtered_out'] += 1
                total_filtered_out += 1
                reason = row.get('discard_reason', 'unknown')
                discard_reasons[reason] = discard_reasons.get(reason, 0) + 1
            total_rows_processed += 1

        bucket = strategy_feedback.setdefault(strategy.intent, {'accepted': 0, 'queries': 0})
        bucket['accepted'] = int(bucket.get('accepted', 0)) + int(strategy_log['accepted'])
        bucket['queries'] = int(bucket.get('queries', 0)) + 1
        strategy_logs.append(strategy_log)

        if total_rows_processed >= MATERIALS_MAX_TOTAL_ROWS:
            break
        current_top = _dedupe_items(list(ranked))[:MATERIALS_EARLY_STOP_RESULTS]
        high_quality_hits = [
            item for item in current_top if item.get('tipo') != 'possible_material' and item.get('nivel_confianca') in {'medio', 'alto'}
        ]
        if len(high_quality_hits) >= MATERIALS_EARLY_STOP_RESULTS:
            LOGGER.info('materials.early_stop registro=%s resultados=%s', registro, len(current_top))
            break

    pre_dedupe_count = len(ranked)
    deduped = _dedupe_items(ranked)
    dedupe_removed_count = max(0, pre_dedupe_count - len(deduped))
    if not deduped and fallback_rows:
        fallback_items = _dedupe_items(_fallback_from_rows(fallback_rows, identity))
        if fallback_items:
            deduped = fallback_items
    elif len(deduped) < 3 and fallback_rows:
        merged = _dedupe_items([*deduped, *_fallback_from_rows(fallback_rows, identity)])
        dedupe_removed_count += max(0, len(deduped) - len(merged))
        deduped = merged[: max(3, len(deduped))]

    if pre_dedupe_count > 0 and not deduped:
        register_error('deduplication', 'deduplication_removed_all', 'Deduplicação removeu todos os resultados.', 'global')

    if total_rows_collected > 0 and total_filtered_out >= total_rows_processed and not deduped:
        register_error('filtering', 'results_filtered_out', 'Resultados foram encontrados, mas descartados pelo filtro/score.', 'global')

    status = 'results_found'
    if unexpected_failure and not deduped:
        status = 'unexpected_error'
    elif timeout_events and not deduped:
        status = 'timeout'
    elif blocked_sources and not deduped:
        status = 'search_blocked'
    elif parse_failures and not deduped:
        status = 'parse_failure'
    elif total_rows_collected > 0 and not deduped:
        status = 'filtered_out'
    elif not total_rows_collected and not deduped:
        status = 'no_results'
    elif deduped and (timeout_events or blocked_sources or parse_failures or unexpected_failure):
        status = 'partial_results'

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    diagnostics = {
        'search_status': status,
        'errors': errors,
        'queries_used': [item.query for item in queries],
        'sources_checked': sorted(checked_sources),
        'raw_results_count': total_rows_collected,
        'accepted_results_count': len(deduped),
        'discarded_results_count': total_filtered_out + dedupe_removed_count,
        'dedupe_removed_count': dedupe_removed_count,
        'discard_reasons': discard_reasons,
        'duration_ms': duration_ms,
        'strategies': strategy_logs,
        'strategy_feedback': strategy_feedback,
        'query_metadata': query_metadata,
        'generated_queries': [item.query for item in queries[:10]],
    }

    LOGGER.info(
        'materials.done registro=%s status=%s raw=%s accepted=%s discarded=%s timeout_events=%s blocked=%s parse_failures=%s duracao_ms=%s errors=%s',
        registro,
        status,
        total_rows_collected,
        len(deduped),
        diagnostics['discarded_results_count'],
        timeout_events,
        blocked_sources,
        parse_failures,
        duration_ms,
        len(errors),
    )

    return {
        'items': deduped[:8],
        'status': status,
        'warning': MATERIALS_STATUS_MESSAGES.get(status) or MATERIALS_AUTOSEARCH_WARNING,
        'source': visited_urls,
        'recommended_searches': recommended_searches,
        'diagnostics': diagnostics,
    }
