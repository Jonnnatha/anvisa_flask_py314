from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.core.config import ALERTS_PAGE_URL, DATA_DIR, REQUEST_TIMEOUT, SSL_VERIFY, USER_AGENT

ALERT_NUMBER_RE = re.compile(r'\b(\d{3,6})\b')
DATE_RE = re.compile(r'(\d{2}/\d{2}/\d{4})')
REGISTRATION_RE = re.compile(r'\b\d{11}\b')

GOVBR_TECNOVIG_ALERTS_URL = (
    'https://www.gov.br/anvisa/pt-br/assuntos/fiscalizacao-e-monitoramento/'
    'tecnovigilancia/alertas-de-tecnovigilancia-1'
)

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
    lowered = (text or '').lower()
    contextual = re.search(r'alerta\s*n?[ºo]?\s*[:\-]?\s*(\d{3,6})', lowered, re.IGNORECASE)
    if contextual:
        return contextual.group(1)
    generic = ALERT_NUMBER_RE.search(lowered)
    return generic.group(1) if generic else None


def _extract_registrations(text: str) -> set[str]:
    return set(REGISTRATION_RE.findall(text or ''))


def _classify_http_status(status_code: int) -> str:
    if status_code in {401, 403}:
        return STATUS_BLOCKED_SOURCE
    return STATUS_MANUAL_VALIDATION_REQUIRED


def _classify_request_failure(exc: Exception) -> str:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return _classify_http_status(exc.response.status_code)
    if isinstance(exc, (requests.Timeout, requests.ConnectionError, requests.SSLError)):
        return STATUS_MANUAL_VALIDATION_REQUIRED
    return STATUS_MANUAL_VALIDATION_REQUIRED


def _build_warning(status: str, details: str | None = None) -> str:
    base = {
        STATUS_BLOCKED_SOURCE: 'Fonte bloqueou consulta automática (ex.: 403/anti-bot).',
        STATUS_PARTIAL_RESULT: 'Resultado parcial: algumas camadas consultadas, mas sem confirmação completa.',
        STATUS_MANUAL_VALIDATION_REQUIRED: 'Validação manual recomendada por limitação da fonte ou parsing.',
        STATUS_NO_ALERTS_FOUND: 'Nenhum alerta localizado nas camadas consultadas.',
    }.get(status, 'Falha na consulta automática de alertas.')

    if details:
        return f'{base} Detalhes técnicos: {details}'
    return base


def _manual_links(registro: str) -> dict[str, str]:
    return {
        'principal': f'{ALERTS_PAGE_URL}?tagsName={registro}',
        'listagem': ALERTS_PAGE_URL,
        'tecnovigilancia': GOVBR_TECNOVIG_ALERTS_URL,
    }


def _normalize_terms(terms: list[str]) -> list[str]:
    clean_terms: list[str] = []
    for term in terms:
        txt = (term or '').strip().lower()
        if len(txt) >= 4:
            clean_terms.append(txt)
    return list(dict.fromkeys(clean_terms))


def _parse_listing_alerts(html: str, base_url: str, terms: list[str]) -> tuple[list[dict[str, Any]], str | None]:
    soup = BeautifulSoup(html, 'html.parser')
    alerts: list[dict[str, Any]] = []
    seen: set[str] = set()

    for link in soup.select('a[href]'):
        href = (link.get('href') or '').strip()
        title = link.get_text(' ', strip=True)
        if not href or not title:
            continue

        full_link = urljoin(base_url, href)
        parent_text = link.parent.get_text(' ', strip=True) if link.parent else ''
        merged = f'{title} {parent_text}'.strip()
        merged_lower = merged.lower()

        if full_link in seen:
            continue
        if 'alerta' not in merged_lower and not any(term in merged_lower for term in terms):
            continue
        if len(title.strip()) < 8:
            continue

        alert_id = _extract_alert_number(merged)
        alerts.append({
            'id': alert_id,
            'title': title,
            'date': _parse_date(merged),
            'summary': parent_text[:400],
            'link': full_link,
            'matched_terms': [term for term in terms if term in merged_lower],
        })
        seen.add(full_link)

    next_link = None
    pager = soup.select_one('a[rel="next"], li.next a[href], a.next')
    if pager and pager.get('href'):
        next_link = urljoin(base_url, pager.get('href').strip())

    return alerts, next_link


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
    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'entries': entries,
    }
    INDEX_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def _layer_direct_query(session: requests.Session, registro: str, terms: list[str]) -> tuple[list[dict[str, Any]], str | None, str | None]:
    try:
        response = session.get(
            ALERTS_PAGE_URL,
            params={'tagsName': registro},
            timeout=REQUEST_TIMEOUT,
            verify=SSL_VERIFY,
            allow_redirects=True,
        )
        if response.status_code >= 400:
            return [], _classify_http_status(response.status_code), f'HTTP {response.status_code}'
        alerts, _ = _parse_listing_alerts(response.text, ALERTS_PAGE_URL, terms)
        return alerts, None, None
    except Exception as exc:
        return [], _classify_request_failure(exc), str(exc)


def _layer_listing_scan(session: requests.Session, terms: list[str]) -> tuple[list[dict[str, Any]], str | None, str | None]:
    url = LEGACY_ALERTS_LIST_URL
    collected: list[dict[str, Any]] = []

    try:
        for _ in range(MAX_LISTING_PAGES):
            response = session.get(url, timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY, allow_redirects=True)
            if response.status_code >= 400:
                return collected, _classify_http_status(response.status_code), f'HTTP {response.status_code}'
            items, next_url = _parse_listing_alerts(response.text, url, terms)
            collected.extend(items)
            if not next_url:
                break
            url = next_url
        return collected, None, None
    except Exception as exc:
        return collected, _classify_request_failure(exc), str(exc)


def _layer_textual_search(candidates: list[dict[str, Any]], registro: str, terms: list[str]) -> list[dict[str, Any]]:
    normalized = _normalize_terms([registro] + terms)
    filtered: list[dict[str, Any]] = []

    for alert in candidates:
        blob = ' '.join([
            alert.get('title', ''),
            alert.get('summary', ''),
            alert.get('link', ''),
            ' '.join(alert.get('matched_terms', [])),
        ]).lower()
        if registro in blob:
            filtered.append(alert)
            continue
        if any(term in blob for term in normalized):
            filtered.append(alert)
            continue

    return filtered


def _index_entries_from_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for alert in alerts:
        searchable = ' '.join([alert.get('title', ''), alert.get('summary', '')])
        registrations = sorted(_extract_registrations(searchable))
        entries.append({
            'id': alert.get('id'),
            'title': alert.get('title'),
            'link': alert.get('link'),
            'date': alert.get('date'),
            'registrations': registrations,
            'search_blob': searchable.lower()[:2000],
        })
    return entries


def _search_in_index(registro: str, terms: list[str], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_terms = _normalize_terms([registro] + terms)
    results: list[dict[str, Any]] = []

    for entry in entries:
        regs = entry.get('registrations', [])
        blob = entry.get('search_blob', '')
        if registro in regs or any(term in blob for term in normalized_terms):
            results.append({
                'id': entry.get('id'),
                'title': entry.get('title'),
                'date': entry.get('date'),
                'summary': None,
                'link': entry.get('link'),
                'matched_terms': [term for term in normalized_terms if term in blob],
            })

    return results


def _dedupe_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for alert in alerts:
        key = str(alert.get('id') or alert.get('link') or alert.get('title'))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(alert)
    return unique


def _format_alerts_payload(alerts: list[dict[str, Any]], source: str, confidence: str) -> dict[str, Any]:
    deduped = _dedupe_alerts(alerts)
    alert_ids = [str(item['id']) for item in deduped if item.get('id')]
    return {
        'count': len(deduped),
        'alert_ids': alert_ids,
        'alerts': deduped,
        'source': source,
        'confidence': confidence,
    }


def find_alerts_by_registration(registro: str, product: dict[str, Any] | None = None) -> dict[str, Any]:
    manufacturer = (product or {}).get('fabricante') or ''
    product_name = (product or {}).get('nome_produto') or ''
    holder = (product or {}).get('detentor_registro') or ''

    search_terms = [registro, manufacturer, product_name, holder]
    search_terms = [term.strip() for term in search_terms if term and term.strip()]
    manual_links = _manual_links(registro)

    session = _build_session()
    sources: list[dict[str, Any]] = []

    direct_alerts, direct_status, direct_details = _layer_direct_query(session, registro, search_terms)
    sources.append({
        'name': 'anvisa_legado_tagsName',
        'url': ALERTS_PAGE_URL,
        'status': 'ok' if direct_status is None else direct_status,
        'details': direct_details,
    })

    if direct_alerts:
        payload = _format_alerts_payload(direct_alerts, 'direct_query', 'high')
        return {
            **payload,
            'status': STATUS_ALERTS_FOUND,
            'warning': None,
            'manual_url': manual_links['principal'],
            'manual_links': manual_links,
            'sources': sources,
        }

    listing_alerts, listing_status, listing_details = _layer_listing_scan(session, search_terms)
    sources.append({
        'name': 'anvisa_legado_listagem',
        'url': LEGACY_ALERTS_LIST_URL,
        'status': 'ok' if listing_status is None else listing_status,
        'details': listing_details,
    })

    indexed_entries = _load_cached_index()
    index_source = 'cache'
    if indexed_entries is None:
        built_entries = _index_entries_from_alerts(listing_alerts)
        if built_entries:
            _save_cached_index(built_entries)
        indexed_entries = {'entries': built_entries}
        index_source = 'fresh_scan'

    textual_alerts = _layer_textual_search(listing_alerts, registro, search_terms)
    cached_alerts = _search_in_index(registro, search_terms, indexed_entries.get('entries', []))
    merged_alerts = _dedupe_alerts(textual_alerts + cached_alerts)

    if merged_alerts:
        confidence = 'high' if any(a.get('id') for a in merged_alerts) else 'medium'
        source = 'listing_textual_scan' if textual_alerts else f'index_{index_source}'
        payload = _format_alerts_payload(merged_alerts, source, confidence)
        status = STATUS_ALERTS_FOUND if listing_status is None else STATUS_PARTIAL_RESULT
        return {
            **payload,
            'status': status,
            'warning': _build_warning(status, listing_details) if status == STATUS_PARTIAL_RESULT else None,
            'manual_url': manual_links['listagem'],
            'manual_links': manual_links,
            'sources': sources,
        }

    if direct_status == STATUS_BLOCKED_SOURCE and listing_status == STATUS_BLOCKED_SOURCE:
        return {
            'count': 0,
            'alert_ids': [],
            'alerts': [],
            'source': 'blocked_sources',
            'confidence': 'low',
            'status': STATUS_BLOCKED_SOURCE,
            'warning': _build_warning(STATUS_BLOCKED_SOURCE, direct_details or listing_details),
            'manual_url': manual_links['tecnovigilancia'],
            'manual_links': manual_links,
            'sources': sources,
        }

    if direct_status or listing_status:
        return {
            'count': 0,
            'alert_ids': [],
            'alerts': [],
            'source': 'layered_search',
            'confidence': 'low',
            'status': STATUS_MANUAL_VALIDATION_REQUIRED,
            'warning': _build_warning(STATUS_MANUAL_VALIDATION_REQUIRED, direct_details or listing_details),
            'manual_url': manual_links['tecnovigilancia'],
            'manual_links': manual_links,
            'sources': sources,
        }

    return {
        'count': 0,
        'alert_ids': [],
        'alerts': [],
        'source': 'layered_search',
        'confidence': 'medium',
        'status': STATUS_NO_ALERTS_FOUND,
        'warning': None,
        'manual_url': manual_links['principal'],
        'manual_links': manual_links,
        'sources': sources,
    }
