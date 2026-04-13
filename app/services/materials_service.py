from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus, urlparse

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

# Ordem de prioridade solicitada: manual > ifu > service_manual > training > catalog > recall ...
TYPE_PRIORITY = {
    'manual': 160,
    'ifu': 152,
    'service_manual': 144,
    'training': 136,
    'catalog': 128,
    'recall': 120,
    'safety_notice': 116,
    'field_corrective_action': 114,
    'technical_bulletin': 108,
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

USEFUL_TERMS = (
    'manual',
    'instruções de uso',
    'instrucoes de uso',
    'instructions for use',
    'ifu',
    'service manual',
    'training',
    'recall',
    'safety notice',
    'field corrective action',
    'fsca',
)

LOGGER = logging.getLogger(__name__)
MATERIALS_AUTOSEARCH_WARNING = 'Não foi possível concluir a busca automática de materiais nesta consulta.'


@dataclass(frozen=True)
class SearchStrategy:
    name: str
    query: str
    layer: int


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


def _add_query(strategies: list[SearchStrategy], seen: set[str], name: str, template: str, layer: int) -> None:
    query = ' '.join(template.split()).strip()
    if not query:
        return
    key = query.casefold()
    if key in seen:
        return
    seen.add(key)
    strategies.append(SearchStrategy(name=name, query=query, layer=layer))


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
        for suffix, name in (
            ('manual', 'product_manual'),
            ('IFU', 'product_ifu'),
            ('instruções de uso', 'product_ifu_pt'),
            ('service manual', 'product_service_manual'),
            ('training', 'product_training'),
            ('recall', 'product_recall'),
            ('safety notice', 'product_safety_notice'),
            ('field corrective action', 'product_fca'),
            ('catálogo técnico', 'product_catalog'),
            ('boletim técnico', 'product_technical_bulletin'),
        ):
            _add_query(strategies, seen, name, f'{produto} {suffix}', layer=1)

    # Camada 2: combinações com fabricante/modelo/marca.
    if fabricante and produto:
        _add_query(strategies, seen, 'manufacturer_product_manual', f'{fabricante} {produto} manual', layer=2)

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
                f'{produto} training',
                f'{produto} recall',
            ]
        )
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


def _parse_search_page(search_url: str) -> dict[str, Any]:
    headers = {'User-Agent': USER_AGENT, 'Accept': 'text/html,*/*'}
    response = requests.get(search_url, timeout=MATERIALS_REQUEST_TIMEOUT, verify=SSL_VERIFY, headers=headers)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    rows: list[dict[str, str]] = []
    anchors_found = 0

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
        rows.append(
            {
                'titulo': title,
                'link': href,
                'resumo': parent_text[:400],
                'contexto': _normalize(f'{title} {parent_text} {href}'),
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

    if any(noise in context for noise in GENERIC_NOISE):
        row['discard_reason'] = 'generic_noise'
        return None
    if any(pattern in link for pattern in BLOCKED_URL_PATTERNS):
        row['discard_reason'] = 'blocked_url_pattern'
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
    if link.endswith('.pdf'):
        score += 18
    if product_in_title:
        score += 42
    elif product_in_snippet:
        score += 18
    if manufacturer_in_title_or_snippet:
        score += 16
    if model_in_title_or_snippet:
        score += 18
    if _has_useful_term(title, snippet):
        score += 30

    # Consultas da camada 1 têm maior peso e não devem falhar cedo.
    if strategy.layer == 1:
        score += 14
    elif strategy.layer == 2:
        score += 8

    condition_a = product_in_title and _has_useful_term(title, snippet)
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

    if not strong_relation:
        minimal_relation = (
            product_hit
            or model_hit
            or technical_name_hit
            or token_hits >= 2
            or (manufacturer_hit and _has_useful_term(title, snippet))
        )
        if not minimal_relation:
            row['discard_reason'] = 'weak_relation'
            return None
        score += 10

    confidence = 'baixo'
    if score >= 195:
        confidence = 'alto'
    elif score >= 128:
        confidence = 'medio'

    if score < 98:
        row['discard_reason'] = 'low_confidence'
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
    seen_links: set[str] = set()
    seen_titles: set[str] = set()

    for item in sorted(items, key=lambda x: x['score'], reverse=True):
        link_key = _normalize(item['link'])
        if link_key in seen_links:
            continue

        title_key = _normalize(re.sub(r'[^a-zA-Z0-9 ]+', ' ', item['titulo']))
        if title_key and title_key in seen_titles:
            continue

        seen_links.add(link_key)
        if title_key:
            seen_titles.add(title_key)

        item.pop('score', None)
        item.pop('strategy', None)
        deduped.append(item)

    return deduped


def find_related_materials(registro: str, product: dict[str, Any] | None = None) -> dict[str, Any]:
    product = product or {}
    identity = _product_identity(product)
    queries = _build_queries(registro, product)[:MATERIALS_MAX_STRATEGIES]

    recommended_queries = _build_recommended_queries(identity)
    recommended_searches = [
        {'query': query, 'url': f'https://www.google.com/search?q={quote_plus(query)}'}
        for query in recommended_queries
    ]

    if not queries:
        return {
            'items': [],
            'status': 'parse_failure',
            'warning': 'Nenhum termo suficiente foi encontrado para busca de materiais técnicos.',
            'source': [GOVBR_SEARCH_URL],
            'recommended_searches': recommended_searches,
            'diagnostics': {'reason': 'missing_query_terms'},
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
    started_at = time.perf_counter()
    deadline = started_at + MATERIALS_TOTAL_TIMEOUT
    total_rows_processed = 0
    total_rows_collected = 0
    total_filtered_out = 0
    timeout_reached = False
    had_errors = False
    blocked_sources = 0
    parse_failures = 0
    strategy_logs: list[dict[str, Any]] = []
    discard_reasons: dict[str, int] = {}

    for strategy in queries:
        strategy_log: dict[str, Any] = {
            'strategy': strategy.name,
            'query': strategy.query,
            'layer': strategy.layer,
            'sources': [],
            'raw_rows': 0,
            'filtered_out': 0,
            'accepted': 0,
        }
        LOGGER.info('materials.strategy.start registro=%s strategy=%s query="%s"', registro, strategy.name, strategy.query)
        if time.perf_counter() >= deadline:
            timeout_reached = True
            LOGGER.warning('materials.timeout registro=%s etapa=strategy_loop', registro)
            strategy_log['aborted'] = 'deadline_reached'
            strategy_logs.append(strategy_log)
            break
        if len(visited_urls) >= MATERIALS_MAX_SOURCES:
            LOGGER.info('materials.limit_sources registro=%s limite=%s', registro, MATERIALS_MAX_SOURCES)
            strategy_log['aborted'] = 'source_limit_reached'
            strategy_logs.append(strategy_log)
            break

        search_url = f"{GOVBR_SEARCH_URL}?SearchableText={quote_plus(strategy.query)}"
        visited_urls.append(search_url)

        rows: list[dict[str, str]] = []
        try:
            gov_result = _parse_search_page(search_url)
            gov_rows = gov_result['rows']
            rows.extend(gov_rows)
            strategy_log['sources'].append({'source': 'govbr', 'status': 'ok', 'rows': len(gov_rows), 'anchors': gov_result.get('anchors_found', 0)})
            if gov_result.get('anchors_found', 0) > 0 and not gov_rows:
                parse_failures += 1
                strategy_log['sources'][-1]['status'] = 'parse_failure'
                strategy_log['sources'][-1]['detail'] = 'anchors_without_valid_rows'
            LOGGER.info('materials.source.done registro=%s strategy=%s fonte=govbr rows=%s', registro, strategy.name, len(gov_rows))
        except requests.Timeout:
            had_errors = True
            blocked_sources += 1
            strategy_log['sources'].append({'source': 'govbr', 'status': 'timeout', 'rows': 0})
            LOGGER.warning('materials.timeout registro=%s fonte=govbr strategy=%s', registro, strategy.name)
        except requests.RequestException as exc:
            had_errors = True
            blocked_sources += 1
            strategy_log['sources'].append({'source': 'govbr', 'status': 'blocked_source', 'rows': 0, 'error': str(exc)})
            LOGGER.warning('materials.error registro=%s fonte=govbr strategy=%s erro=%s', registro, strategy.name, exc)

        try:
            duck_result = _parse_duckduckgo_page(strategy.query)
            duck_rows = duck_result['rows']
            rows.extend(duck_rows)
            strategy_log['sources'].append({'source': 'duckduckgo', 'status': 'ok', 'rows': len(duck_rows), 'blocks': duck_result.get('blocks_found', 0)})
            if duck_result.get('blocks_found', 0) > 0 and not duck_rows:
                parse_failures += 1
                strategy_log['sources'][-1]['status'] = 'parse_failure'
                strategy_log['sources'][-1]['detail'] = 'blocks_without_valid_rows'
            LOGGER.info('materials.source.done registro=%s strategy=%s fonte=duckduckgo rows=%s', registro, strategy.name, len(duck_rows))
        except requests.Timeout:
            had_errors = True
            blocked_sources += 1
            strategy_log['sources'].append({'source': 'duckduckgo', 'status': 'timeout', 'rows': 0})
            LOGGER.warning('materials.timeout registro=%s fonte=duckduckgo strategy=%s', registro, strategy.name)
        except requests.RequestException as exc:
            had_errors = True
            blocked_sources += 1
            strategy_log['sources'].append({'source': 'duckduckgo', 'status': 'blocked_source', 'rows': 0, 'error': str(exc)})
            LOGGER.warning('materials.error registro=%s fonte=duckduckgo strategy=%s erro=%s', registro, strategy.name, exc)

        strategy_log['raw_rows'] = len(rows)
        total_rows_collected += len(rows)
        LOGGER.info('materials.strategy.collected registro=%s strategy=%s rows=%s', registro, strategy.name, len(rows))

        for row in rows[:MATERIALS_MAX_ROWS_PER_STRATEGY]:
            if time.perf_counter() >= deadline:
                timeout_reached = True
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
                ranked.append(evaluated)
                strategy_log['accepted'] += 1
            else:
                strategy_log['filtered_out'] += 1
                total_filtered_out += 1
                reason = row.get('discard_reason', 'unknown')
                discard_reasons[reason] = discard_reasons.get(reason, 0) + 1
            total_rows_processed += 1

        LOGGER.info(
            'materials.strategy.done registro=%s strategy=%s raw=%s accepted=%s filtered=%s',
            registro,
            strategy.name,
            strategy_log['raw_rows'],
            strategy_log['accepted'],
            strategy_log['filtered_out'],
        )
        strategy_logs.append(strategy_log)

        if total_rows_processed >= MATERIALS_MAX_TOTAL_ROWS:
            break

        current_top = _dedupe_items(list(ranked))[:MATERIALS_EARLY_STOP_RESULTS]
        if len(current_top) >= MATERIALS_EARLY_STOP_RESULTS:
            LOGGER.info('materials.early_stop registro=%s resultados=%s', registro, len(current_top))
            break

    deduped = _dedupe_items(ranked)
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    LOGGER.info(
        'materials.done registro=%s resultados=%s rows_processed=%s rows_collected=%s filtered=%s sources=%s timeout=%s errors=%s parse_failures=%s blocked_sources=%s duracao_ms=%s discard_reasons=%s',
        registro,
        len(deduped),
        total_rows_processed,
        total_rows_collected,
        total_filtered_out,
        len(visited_urls),
        timeout_reached,
        had_errors,
        parse_failures,
        blocked_sources,
        duration_ms,
        discard_reasons,
    )

    status = 'ok'
    warning = None
    if timeout_reached:
        status = 'timeout'
        warning = MATERIALS_AUTOSEARCH_WARNING
    elif blocked_sources and not deduped:
        status = 'blocked_source'
        warning = MATERIALS_AUTOSEARCH_WARNING
    elif parse_failures and not deduped:
        status = 'parse_failure'
        warning = MATERIALS_AUTOSEARCH_WARNING
    elif not deduped and total_filtered_out > 0:
        status = 'filtered_out'
        warning = 'A busca encontrou itens brutos, mas todos foram descartados pelos critérios de relevância.'
    elif not deduped:
        status = 'no_results'
        warning = 'Nenhum material técnico público relevante foi encontrado para este produto.'
    elif len(deduped) < min(3, MATERIALS_EARLY_STOP_RESULTS):
        status = 'partial_results'
        warning = 'A busca retornou poucos materiais estruturados; use também as pesquisas recomendadas.'

    diagnostics = {
        'status': status,
        'rows_processed': total_rows_processed,
        'rows_collected': total_rows_collected,
        'filtered_out': total_filtered_out,
        'discard_reasons': discard_reasons,
        'timeout_reached': timeout_reached,
        'blocked_sources': blocked_sources,
        'parse_failures': parse_failures,
        'strategies': strategy_logs,
    }

    if not deduped:
        return {
            'items': [],
            'status': status,
            'warning': warning,
            'source': visited_urls,
            'recommended_searches': recommended_searches,
            'diagnostics': diagnostics,
        }

    return {
        'items': deduped[:12],
        'status': status,
        'warning': warning,
        'source': visited_urls,
        'recommended_searches': recommended_searches,
        'diagnostics': diagnostics,
    }
