from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from app.core.config import ALERTS_PAGE_URL, DATA_DIR, REQUEST_TIMEOUT, SSL_VERIFY, USER_AGENT

logger = logging.getLogger(__name__)

ALERT_NUMBER_RE = re.compile(r'\b(\d{3,6})\b')
DATE_RE = re.compile(r'(\d{2}/\d{2}/\d{4})')
REGISTRATION_RE = re.compile(r'\b\d{11}\b')

GOVBR_TECNOVIG_ALERTS_URL = (
    'https://www.gov.br/anvisa/pt-br/assuntos/fiscalizacao-e-monitoramento/'
    'tecnovigilancia/alertas-de-tecnovigilancia-1'
)
LEGACY_ADVANCED_SEARCH_URL = (
    'https://antigo.anvisa.gov.br/alertas/-/buscar'
    '?p_p_id=anvisabuscaavancada_WAR_anvisabuscaavancadaportlet'
)
GOVBR_SEARCH_URL = 'https://www.gov.br/anvisa/pt-br/search'
SISTEC_ALERT_SEARCH_URL = 'http://www.anvisa.gov.br/sistec/alerta/consultaralerta.asp'
COMMUNITY_REGISTRY_LOOKUP_URL = 'https://brunoroma.pythonanywhere.com/registro/{registro}'
LEGACY_ALERTS_LIST_URL = ALERTS_PAGE_URL

STATUS_ALERTS_FOUND = 'alerts_found'
STATUS_NO_ALERTS_FOUND = 'no_alerts_found'
STATUS_BLOCKED_SOURCE = 'blocked_source'
STATUS_PARTIAL_RESULT = 'partial_result'
STATUS_MANUAL_VALIDATION_REQUIRED = 'manual_validation_required'

INDEX_CACHE_FILE = DATA_DIR / 'alerts_index_cache.json'
INDEX_CACHE_TTL_HOURS = 12
MAX_LISTING_PAGES = 5

BROWSER_HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Upgrade-Insecure-Requests': '1',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Referer': ALERTS_PAGE_URL,
}


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    return session


def _parse_date(text: str) -> str | None:
    match = DATE_RE.search(text or '')
    if not match:
        return None
    raw = match.group(1)
    try:
        return datetime.strptime(raw, '%d/%m/%Y').date().isoformat()
    except ValueError:
        return raw


def _extract_alert_number(text: str) -> str | None:
    contextual = re.search(r'alerta\s*n?[ºo]?\s*[:\-]?\s*(\d{3,6})', text or '', re.IGNORECASE)
    if contextual:
        return contextual.group(1)
    generic = ALERT_NUMBER_RE.search(text or '')
    return generic.group(1) if generic else None


def _extract_registrations(text: str) -> set[str]:
    return set(REGISTRATION_RE.findall(text or ''))


def _classify_http_status(status_code: int) -> str:
    return STATUS_BLOCKED_SOURCE if status_code in {401, 403} else STATUS_MANUAL_VALIDATION_REQUIRED


def _classify_request_failure(exc: Exception) -> str:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return _classify_http_status(exc.response.status_code)
    if isinstance(exc, (requests.Timeout, requests.ConnectionError, requests.SSLError)):
        return STATUS_MANUAL_VALIDATION_REQUIRED
    return STATUS_MANUAL_VALIDATION_REQUIRED


def _build_warning(status: str, details: str | None = None) -> str:
    base = {
        STATUS_BLOCKED_SOURCE: 'Fonte bloqueou consulta automática (ex.: 403/anti-bot).',
        STATUS_PARTIAL_RESULT: 'Resultado parcial: números identificados sem confirmação completa do alerta.',
        STATUS_MANUAL_VALIDATION_REQUIRED: 'Validação manual recomendada por limitação da fonte ou parsing.',
        STATUS_NO_ALERTS_FOUND: 'Nenhum alerta localizado nas camadas consultadas.',
    }.get(status, 'Falha na consulta automática de alertas.')
    return f'{base} Detalhes técnicos: {details}' if details else base


def _manual_links(registro: str) -> dict[str, str]:
    search_query = quote_plus(f'alerta tecnovigilancia {registro}')
    return {
        'principal': f'{ALERTS_PAGE_URL}?tagsName={registro}',
        'listagem': ALERTS_PAGE_URL,
        'tecnovigilancia': GOVBR_TECNOVIG_ALERTS_URL,
        'busca_portal': f'{LEGACY_ADVANCED_SEARCH_URL}&keywords={registro}&dataInicial=&dataFinal=&categoryIds=34506',
        'busca_govbr': f'{GOVBR_SEARCH_URL}?SearchableText={search_query}',
        'sistec_historico': SISTEC_ALERT_SEARCH_URL,
        'espelho_comunitario': COMMUNITY_REGISTRY_LOOKUP_URL.format(registro=registro),
    }


def _normalize_terms(terms: list[str]) -> list[str]:
    return list(dict.fromkeys((t or '').strip().lower() for t in terms if len((t or '').strip()) >= 4))


def _enrich_alert(alert: dict[str, Any], default_origin: str, confidence: str, registro: str) -> dict[str, Any]:
    number = str(alert.get('numero_alerta') or alert.get('id') or '').strip() or None
    manual = alert.get('link_pesquisa_manual') or (
        f'{GOVBR_SEARCH_URL}?SearchableText={quote_plus(f"alerta {number} anvisa {registro}")}' if number else None
    )
    return {
        'numero_alerta': number,
        'id': number or alert.get('id'),
        'title': alert.get('title') or alert.get('titulo') or (f'Alerta {number}' if number else 'Alerta'),
        'titulo': alert.get('title') or alert.get('titulo'),
        'date': alert.get('date') or alert.get('data'),
        'data': alert.get('date') or alert.get('data'),
        'summary': alert.get('summary'),
        'link': alert.get('link') or alert.get('link_oficial'),
        'link_oficial': alert.get('link_oficial') or alert.get('link'),
        'link_pesquisa_manual': manual,
        'origem_da_descoberta': alert.get('origem_da_descoberta') or default_origin,
        'nivel_confianca': alert.get('nivel_confianca') or confidence,
        'matched_terms': alert.get('matched_terms', []),
    }


def _parse_listing_alerts(html: str, base_url: str, terms: list[str], origin: str) -> tuple[list[dict[str, Any]], str | None]:
    soup = BeautifulSoup(html, 'html.parser')
    alerts: list[dict[str, Any]] = []
    seen: set[str] = set()

    for link in soup.select('a[href]'):
        href = (link.get('href') or '').strip()
        title = link.get_text(' ', strip=True)
        if not href or not title:
            continue
        full_link = urljoin(base_url, href)
        merged = f'{title} {(link.parent.get_text(" ", strip=True) if link.parent else "")}'.strip()
        merged_lower = merged.lower()
        if full_link in seen:
            continue
        if terms and not any(term in merged_lower for term in terms):
            continue
        if len(title.strip()) < 8:
            continue
        alerts.append(_enrich_alert({
            'numero_alerta': _extract_alert_number(merged),
            'title': title,
            'date': _parse_date(merged),
            'summary': merged[:400],
            'link_oficial': full_link,
            'origem_da_descoberta': origin,
            'matched_terms': [term for term in terms if term in merged_lower],
        }, origin, 'high', ''))
        seen.add(full_link)

    pager = soup.select_one('a[rel="next"], li.next a[href], a.next')
    next_link = urljoin(base_url, pager.get('href').strip()) if pager and pager.get('href') else None
    return alerts, next_link


def _extract_alert_candidates_from_text(payload: str, origin: str, registro: str, terms: list[str] | None = None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    normalized_terms = _normalize_terms(terms or [])
    for match in re.finditer(r'alerta(?:\s*sanit[aá]rio)?\s*n?[ºo]?\s*[:\-]?\s*(\d{2,6})', payload or '', re.IGNORECASE):
        number = match.group(1)
        if number in seen:
            continue
        around = (payload or '')[max(0, match.start() - 180): match.end() + 180]
        around_lower = around.lower()
        if registro not in around_lower and normalized_terms and not any(term in around_lower for term in normalized_terms):
            continue
        seen.add(number)
        candidates.append(_enrich_alert({
            'numero_alerta': number,
            'summary': around[:400],
            'origem_da_descoberta': origin,
        }, origin, 'medium', registro))
    return candidates


def _extract_alert_numbers_from_payload(payload: str) -> list[str]:
    body = payload or ''
    # Prioriza formato observado no endpoint de referência: "Alerta(s): [4412 4361 ...]".
    # Isso evita captar anos/contagens e reduz falso-positivo no fallback externo.
    bracket_match = re.search(r'alerta\(s\)\s*:\s*\[([^\]]+)\]', body, re.IGNORECASE)
    if bracket_match:
        pool = bracket_match.group(1)
    else:
        context_match = re.search(r'alerta[^\n:]*:\s*(.+)$', body, re.IGNORECASE)
        pool = context_match.group(1) if context_match else body

    seen: set[str] = set()
    result: list[str] = []
    for number in re.findall(r'\b\d{3,6}\b', pool):
        if number in seen:
            continue
        seen.add(number)
        result.append(number)
    return result


def _load_cached_index() -> dict[str, Any] | None:
    if not INDEX_CACHE_FILE.exists():
        return None
    try:
        payload = json.loads(INDEX_CACHE_FILE.read_text(encoding='utf-8'))
        generated_at = datetime.fromisoformat(payload.get('generated_at'))
        if datetime.now(timezone.utc) - generated_at > timedelta(hours=INDEX_CACHE_TTL_HOURS):
            return None
        return payload
    except Exception:
        return None


def _save_cached_index(entries: list[dict[str, Any]]) -> None:
    INDEX_CACHE_FILE.write_text(
        json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(), 'entries': entries}, ensure_ascii=False),
        encoding='utf-8',
    )


def _index_entries_from_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for alert in alerts:
        searchable = ' '.join([alert.get('title', ''), alert.get('summary', '')])
        entries.append({
            'id': alert.get('id'),
            'title': alert.get('title'),
            'link': alert.get('link_oficial') or alert.get('link'),
            'date': alert.get('date'),
            'registrations': sorted(_extract_registrations(searchable)),
            'search_blob': searchable.lower()[:2000],
        })
    return entries


def _search_in_index(registro: str, terms: list[str], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = _normalize_terms([registro] + terms)
    results: list[dict[str, Any]] = []
    for entry in entries:
        blob = entry.get('search_blob', '')
        regs = entry.get('registrations', [])
        if registro in regs or any(term in blob for term in normalized):
            results.append(_enrich_alert({
                'numero_alerta': entry.get('id'),
                'title': entry.get('title'),
                'date': entry.get('date'),
                'link_oficial': entry.get('link'),
                'origem_da_descoberta': 'official_sources_index_cache',
            }, 'official_sources_index_cache', 'medium', registro))
    return results


def _dedupe_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for alert in alerts:
        key = str(alert.get('numero_alerta') or alert.get('id') or alert.get('link_oficial') or alert.get('title'))
        if key in seen:
            continue
        seen.add(key)
        unique.append(alert)
    return unique


def _record_attempt(attempts: list[dict[str, Any]], layer: str, name: str, url: str, status: str, details: str | None, count: int = 0) -> None:
    attempts.append({'layer': layer, 'name': name, 'url': url, 'status': status, 'details': details, 'alerts_count': count})
    logger.info('alerts_strategy layer=%s source=%s status=%s alerts=%s details=%s', layer, name, status, count, details)


def _final_payload(alerts: list[dict[str, Any]], source: str, confidence: str) -> dict[str, Any]:
    deduped = _dedupe_alerts(alerts)
    ids = [str(a.get('numero_alerta') or a.get('id')) for a in deduped if a.get('numero_alerta') or a.get('id')]
    return {'count': len(deduped), 'alert_ids': ids, 'alerts': deduped, 'source': source, 'confidence': confidence}


def find_alerts_by_registration(registro: str, product: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Estratégia em camadas para evitar resposta inútil em caso de 403.
    Ordem: official_sources -> alternative_search -> partial_identifier -> external_fallback.
    """
    search_terms = [registro, (product or {}).get('fabricante') or '', (product or {}).get('nome_produto') or '', (product or {}).get('detentor_registro') or '']
    search_terms = [t.strip() for t in search_terms if t and t.strip()]
    manual_links = _manual_links(registro)
    session = _build_session()

    all_alerts: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    partial_pool: list[dict[str, Any]] = []
    error_details: list[str] = []

    # 1) official_sources
    official_statuses: list[str] = []
    try:
        r = session.get(ALERTS_PAGE_URL, params={'tagsName': registro}, timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY, allow_redirects=True)
        if r.status_code >= 400:
            st = _classify_http_status(r.status_code)
            official_statuses.append(st)
            _record_attempt(attempts, 'official_sources', 'anvisa_legado_tagsName', ALERTS_PAGE_URL, st, f'HTTP {r.status_code}')
            error_details.append(f'tagsName HTTP {r.status_code}')
            partial_pool.extend(_extract_alert_candidates_from_text(r.text, 'official_tags_text_probe', registro, search_terms))
        else:
            items, _ = _parse_listing_alerts(r.text, ALERTS_PAGE_URL, _normalize_terms(search_terms), 'official_tags_listing')
            all_alerts.extend([_enrich_alert(a, 'official_tags_listing', 'high', registro) for a in items])
            partial_pool.extend(_extract_alert_candidates_from_text(r.text, 'official_tags_text_probe', registro, search_terms))
            _record_attempt(attempts, 'official_sources', 'anvisa_legado_tagsName', ALERTS_PAGE_URL, 'ok', None, len(items))
    except Exception as exc:
        st = _classify_request_failure(exc)
        official_statuses.append(st)
        _record_attempt(attempts, 'official_sources', 'anvisa_legado_tagsName', ALERTS_PAGE_URL, st, str(exc))
        error_details.append(str(exc))

    listing_alerts: list[dict[str, Any]] = []
    try:
        url = LEGACY_ALERTS_LIST_URL
        for _ in range(MAX_LISTING_PAGES):
            r = session.get(url, timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY, allow_redirects=True)
            if r.status_code >= 400:
                st = _classify_http_status(r.status_code)
                official_statuses.append(st)
                _record_attempt(attempts, 'official_sources', 'anvisa_legado_listagem', url, st, f'HTTP {r.status_code}', len(listing_alerts))
                error_details.append(f'listagem HTTP {r.status_code}')
                break
            items, next_url = _parse_listing_alerts(r.text, url, _normalize_terms(search_terms), 'official_listagem_scan')
            listing_alerts.extend(items)
            partial_pool.extend(_extract_alert_candidates_from_text(r.text, 'official_listagem_text_probe', registro, search_terms))
            if not next_url:
                _record_attempt(attempts, 'official_sources', 'anvisa_legado_listagem', url, 'ok', None, len(listing_alerts))
                break
            url = next_url
        all_alerts.extend([_enrich_alert(a, 'official_listagem_scan', 'high', registro) for a in listing_alerts])
    except Exception as exc:
        st = _classify_request_failure(exc)
        official_statuses.append(st)
        _record_attempt(attempts, 'official_sources', 'anvisa_legado_listagem', LEGACY_ALERTS_LIST_URL, st, str(exc), len(listing_alerts))
        error_details.append(str(exc))

    # 2) alternative_search (variações Anvisa / gov.br)
    for name, url, params in [
        ('anvisa_legado_busca_avancada', LEGACY_ADVANCED_SEARCH_URL, {'keywords': registro, 'dataInicial': '', 'dataFinal': '', 'categoryIds': '34506'}),
        ('govbr_search', GOVBR_SEARCH_URL, {'SearchableText': f'alerta tecnovigilancia {registro}'}),
    ]:
        try:
            r = session.get(url, params=params, timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY, allow_redirects=True)
            if r.status_code >= 400:
                st = _classify_http_status(r.status_code)
                _record_attempt(attempts, 'alternative_search', name, url, st, f'HTTP {r.status_code}')
                error_details.append(f'{name} HTTP {r.status_code}')
                partial_pool.extend(_extract_alert_candidates_from_text(r.text, f'{name}_text_probe', registro, search_terms))
                continue
            items, _ = _parse_listing_alerts(r.text, r.url, _normalize_terms(search_terms), f'{name}_listing')
            partial = _extract_alert_candidates_from_text(r.text, f'{name}_text_probe', registro, search_terms)
            all_alerts.extend([_enrich_alert(a, f'{name}_listing', 'high', registro) for a in items])
            partial_pool.extend(partial)
            _record_attempt(attempts, 'alternative_search', name, url, 'ok', None, len(items) + len(partial))
        except Exception as exc:
            st = _classify_request_failure(exc)
            _record_attempt(attempts, 'alternative_search', name, url, st, str(exc))
            error_details.append(str(exc))

    # cache/index on official data already fetched
    cache = _load_cached_index()
    if cache is None:
        entries = _index_entries_from_alerts(listing_alerts)
        if entries:
            _save_cached_index(entries)
        cache = {'entries': entries}
        _record_attempt(attempts, 'alternative_search', 'official_index_cache_refresh', str(INDEX_CACHE_FILE), 'ok', None, len(entries))
    indexed = _search_in_index(registro, search_terms, cache.get('entries', []))
    if indexed:
        all_alerts.extend(indexed)
    _record_attempt(attempts, 'alternative_search', 'official_index_cache_lookup', str(INDEX_CACHE_FILE), 'ok', None, len(indexed))

    # 3) partial_identifier (força números mesmo sem título/link oficial)
    partial_numbers = {str(a.get('numero_alerta')) for a in partial_pool if a.get('numero_alerta')}
    numbered_from_full = {str(a.get('numero_alerta')) for a in all_alerts if a.get('numero_alerta')}
    missing_numbers = [n for n in partial_numbers if n and n not in numbered_from_full]
    partial_from_numbers = [_enrich_alert({'numero_alerta': n, 'origem_da_descoberta': 'partial_identifier_numbers_only'}, 'partial_identifier_numbers_only', 'medium', registro) for n in sorted(missing_numbers)]
    _record_attempt(attempts, 'partial_identifier', 'textual_number_extraction', 'in-memory', 'ok', None, len(partial_from_numbers))

    # 4) external_fallback (contingência opcional para utilidade prática)
    external_alerts: list[dict[str, Any]] = []
    try:
        external_url = COMMUNITY_REGISTRY_LOOKUP_URL.format(registro=registro)
        r = session.get(external_url, timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY, allow_redirects=True)
        if r.status_code >= 400:
            st = _classify_http_status(r.status_code)
            _record_attempt(attempts, 'external_fallback', 'community_registry_lookup', external_url, st, f'HTTP {r.status_code}')
            error_details.append(f'community HTTP {r.status_code}')
        else:
            nums = _extract_alert_numbers_from_payload(r.text)
            for num in nums:
                external_alerts.append(_enrich_alert({'numero_alerta': num, 'origem_da_descoberta': 'external_fallback_community'}, 'external_fallback_community', 'medium', registro))
            _record_attempt(attempts, 'external_fallback', 'community_registry_lookup', external_url, 'ok', None, len(external_alerts))
    except Exception as exc:
        st = _classify_request_failure(exc)
        _record_attempt(attempts, 'external_fallback', 'community_registry_lookup', COMMUNITY_REGISTRY_LOOKUP_URL.format(registro=registro), st, str(exc))
        error_details.append(str(exc))

    merged = _dedupe_alerts(all_alerts + partial_from_numbers + external_alerts)
    if merged:
        has_official = any(a.get('link_oficial') for a in merged)
        status = STATUS_ALERTS_FOUND if has_official else STATUS_PARTIAL_RESULT
        confidence = 'high' if has_official else 'medium'
        payload = _final_payload(merged, 'layered_alert_discovery', confidence)
        return {
            **payload,
            'status': status,
            'warning': _build_warning(status, '; '.join(error_details[:3])) if status == STATUS_PARTIAL_RESULT else None,
            'manual_url': manual_links['principal'],
            'manual_links': manual_links,
            'sources': attempts,
        }

    if official_statuses and all(s == STATUS_BLOCKED_SOURCE for s in official_statuses):
        status = STATUS_BLOCKED_SOURCE
    elif error_details:
        status = STATUS_MANUAL_VALIDATION_REQUIRED
    else:
        status = STATUS_NO_ALERTS_FOUND

    return {
        **_final_payload([], 'layered_alert_discovery', 'low' if status != STATUS_NO_ALERTS_FOUND else 'medium'),
        'status': status,
        'warning': _build_warning(status, '; '.join(error_details[:3])) if status != STATUS_NO_ALERTS_FOUND else None,
        'manual_url': manual_links['tecnovigilancia'],
        'manual_links': manual_links,
        'sources': attempts,
    }
