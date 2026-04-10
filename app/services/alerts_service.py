from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus, urljoin

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
LEGACY_ADVANCED_SEARCH_URL = (
    'https://antigo.anvisa.gov.br/alertas/-/buscar'
    '?p_p_id=anvisabuscaavancada_WAR_anvisabuscaavancadaportlet'
)
GOVBR_SEARCH_URL = 'https://www.gov.br/anvisa/pt-br/search'
SISTEC_ALERT_SEARCH_URL = 'http://www.anvisa.gov.br/sistec/alerta/consultaralerta.asp'

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
    search_query = quote_plus(f'alerta tecnovigilancia {registro}')
    return {
        'principal': f'{ALERTS_PAGE_URL}?tagsName={registro}',
        'listagem': ALERTS_PAGE_URL,
        'tecnovigilancia': GOVBR_TECNOVIG_ALERTS_URL,
        'busca_portal': (
            f'{LEGACY_ADVANCED_SEARCH_URL}&keywords={registro}&dataInicial=&dataFinal=&categoryIds=34506'
        ),
        'busca_govbr': f'{GOVBR_SEARCH_URL}?SearchableText={search_query}',
        'sistec_historico': SISTEC_ALERT_SEARCH_URL,
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
        normalized_link = full_link.lower()
        parent_text = link.parent.get_text(' ', strip=True) if link.parent else ''
        merged = f'{title} {parent_text}'.strip()
        merged_lower = merged.lower()

        if full_link in seen:
            continue
        if 'alerta' not in merged_lower and not any(term in merged_lower for term in terms):
            continue
        if len(title.strip()) < 8:
            continue
        if normalized_link.rstrip('/') in {
            ALERTS_PAGE_URL.rstrip('/'),
            LEGACY_ALERTS_LIST_URL.rstrip('/'),
        }:
            continue
        if normalized_link.startswith(f"{ALERTS_PAGE_URL.lower()}#"):
            continue

        alert_id = _extract_alert_number(merged)
        alerts.append({
            'numero_alerta': alert_id,
            'id': alert_id,
            'title': title,
            'titulo': title,
            'date': _parse_date(merged),
            'data': _parse_date(merged),
            'summary': parent_text[:400],
            'link': full_link,
            'link_oficial': full_link,
            'link_pesquisa_manual': None,
            'origem_da_descoberta': 'listagem',
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


def _extract_alert_candidates_from_text(
    html: str,
    search_terms: list[str],
    source_url: str,
    origin: str,
) -> list[dict[str, Any]]:
    """
    Fallback resiliente para páginas onde a busca é limitada/indireta.
    Extrai pares "alerta + número" do texto bruto e monta links úteis.
    """
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(' ', strip=True)
    text_lower = text.lower()
    normalized_terms = _normalize_terms(search_terms)

    if normalized_terms and not any(term in text_lower for term in normalized_terms):
        # Mesmo sem match textual explícito, seguimos tentando extrair identificadores
        # para não perder alertas parcialmente identificados.
        pass

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    pattern = re.compile(r'alerta(?:\s*sanit[aá]rio)?\s*n?[ºo]?\s*[:\-]?\s*(\d{2,6})', re.IGNORECASE)
    for match in pattern.finditer(text):
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        around = text[max(0, match.start() - 140): match.end() + 160].strip()
        candidates.append({
            'numero_alerta': number,
            'id': number,
            'title': f'Alerta {number} (identificação parcial)',
            'titulo': None,
            'date': _parse_date(around),
            'data': _parse_date(around),
            'summary': around[:400],
            'link': None,
            'link_oficial': None,
            'link_pesquisa_manual': f'{GOVBR_SEARCH_URL}?SearchableText={quote_plus(f"alerta {number} anvisa")}',
            'origem_da_descoberta': origin,
            'matched_terms': [term for term in normalized_terms if term in around.lower()],
        })

    if not candidates:
        return []
    return candidates


def _layer_legacy_advanced_search(
    session: requests.Session,
    registro: str,
    terms: list[str],
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    try:
        response = session.get(
            LEGACY_ADVANCED_SEARCH_URL,
            params={
                'keywords': registro,
                'dataInicial': '',
                'dataFinal': '',
                'categoryIds': '34506',
            },
            timeout=REQUEST_TIMEOUT,
            verify=SSL_VERIFY,
            allow_redirects=True,
        )
        if response.status_code >= 400:
            return [], _classify_http_status(response.status_code), f'HTTP {response.status_code}'
        alerts, _ = _parse_listing_alerts(response.text, response.url, terms)
        if alerts:
            for alert in alerts:
                alert['origem_da_descoberta'] = 'legacy_advanced_search'
            return alerts, None, None
        partial = _extract_alert_candidates_from_text(
            response.text,
            [registro] + terms,
            response.url,
            'legacy_advanced_search_partial',
        )
        return partial, None, None
    except Exception as exc:
        return [], _classify_request_failure(exc), str(exc)


def _layer_govbr_search_fallback(
    session: requests.Session,
    registro: str,
    terms: list[str],
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    try:
        response = session.get(
            GOVBR_SEARCH_URL,
            params={'SearchableText': f'alerta tecnovigilancia {registro}'},
            timeout=REQUEST_TIMEOUT,
            verify=SSL_VERIFY,
            allow_redirects=True,
        )
        if response.status_code >= 400:
            return [], _classify_http_status(response.status_code), f'HTTP {response.status_code}'
        partial = _extract_alert_candidates_from_text(
            response.text,
            [registro] + terms,
            response.url,
            'govbr_search_partial',
        )
        return partial, None, None
    except Exception as exc:
        return [], _classify_request_failure(exc), str(exc)


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
                'numero_alerta': entry.get('id'),
                'id': entry.get('id'),
                'title': entry.get('title'),
                'titulo': entry.get('title'),
                'date': entry.get('date'),
                'data': entry.get('date'),
                'summary': None,
                'link': entry.get('link'),
                'link_oficial': entry.get('link'),
                'link_pesquisa_manual': None,
                'origem_da_descoberta': 'index_cache_lookup',
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

    alt_alerts, alt_status, alt_details = _layer_legacy_advanced_search(session, registro, search_terms)
    sources.append({
        'name': 'anvisa_legado_busca_avancada',
        'url': LEGACY_ADVANCED_SEARCH_URL,
        'status': 'ok' if alt_status is None else alt_status,
        'details': alt_details,
    })

    govbr_partial_alerts, govbr_status, govbr_details = _layer_govbr_search_fallback(session, registro, search_terms)
    sources.append({
        'name': 'govbr_search_fallback',
        'url': GOVBR_SEARCH_URL,
        'status': 'ok' if govbr_status is None else govbr_status,
        'details': govbr_details,
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
    merged_alerts = _dedupe_alerts(textual_alerts + cached_alerts + alt_alerts + govbr_partial_alerts)

    if merged_alerts:
        has_official_links = any(a.get('link') or a.get('link_oficial') for a in merged_alerts)
        has_alert_number = any(a.get('numero_alerta') or a.get('id') for a in merged_alerts)
        confidence = 'high' if has_official_links and has_alert_number else 'medium'
        source = 'listing_textual_scan' if textual_alerts else f'index_{index_source}'
        if alt_alerts:
            source = 'legacy_advanced_fallback'
        if govbr_partial_alerts and not (textual_alerts or alt_alerts):
            source = 'govbr_search_partial'
        payload = _format_alerts_payload(merged_alerts, source, confidence)
        status = STATUS_ALERTS_FOUND if has_official_links else STATUS_PARTIAL_RESULT
        return {
            **payload,
            'status': status,
            'warning': _build_warning(status, listing_details or alt_details or govbr_details)
            if status == STATUS_PARTIAL_RESULT
            else None,
            'manual_url': manual_links['listagem'],
            'manual_links': manual_links,
            'sources': sources,
        }

    blocked_statuses = [direct_status, listing_status, alt_status]
    if all(status == STATUS_BLOCKED_SOURCE for status in blocked_statuses if status is not None):
        return {
            'count': 0,
            'alert_ids': [],
            'alerts': [],
            'source': 'blocked_sources',
            'confidence': 'low',
            'status': STATUS_BLOCKED_SOURCE,
            'warning': _build_warning(
                STATUS_BLOCKED_SOURCE,
                direct_details or listing_details or alt_details or govbr_details,
            ),
            'manual_url': manual_links['tecnovigilancia'],
            'manual_links': manual_links,
            'sources': sources,
        }

    if direct_status or listing_status or alt_status or govbr_status:
        return {
            'count': 0,
            'alert_ids': [],
            'alerts': [],
            'source': 'layered_search',
            'confidence': 'low',
            'status': STATUS_MANUAL_VALIDATION_REQUIRED,
            'warning': _build_warning(
                STATUS_MANUAL_VALIDATION_REQUIRED,
                direct_details or listing_details or alt_details or govbr_details,
            ),
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
