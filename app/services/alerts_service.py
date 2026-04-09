from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.core.config import ALERTS_PAGE_URL
from app.services.http_client import get

ALERT_NUMBER_RE = re.compile(r'(?:alerta\s*n?[ºo]?\s*[:\-]?\s*)(\d+[\w\-/]*)', re.IGNORECASE)
DATE_RE = re.compile(r'(\d{2}/\d{2}/\d{4})')

GOVBR_TECNOVIG_ALERTS_URL = (
    'https://www.gov.br/anvisa/pt-br/assuntos/fiscalizacao-e-monitoramento/'
    'tecnovigilancia/alertas-de-tecnovigilancia-1'
)

STATUS_NO_RESULTS = 'no_results'
STATUS_BLOCKED = 'blocked'
STATUS_UNAVAILABLE = 'unavailable'
STATUS_PARSING_ERROR = 'parsing_error'
STATUS_PARTIAL = 'partial'


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
    match = ALERT_NUMBER_RE.search(text or '')
    return match.group(1) if match else None


def _parse_alerts(html: str, registro: str, terms: list[str] | None = None) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, 'html.parser')
    alerts: list[dict[str, Any]] = []
    seen_links: set[str] = set()

    normalized_terms = [t.lower() for t in (terms or []) if t]
    for link in soup.select('a[href]'):
        href = link.get('href', '').strip()
        title = link.get_text(' ', strip=True)
        if not href or not title:
            continue

        full_link = urljoin(ALERTS_PAGE_URL, href)
        lower_title = title.lower()

        contains_alert_word = 'alerta' in lower_title
        is_relevant = registro in title
        container_text = link.parent.get_text(' ', strip=True) if link.parent else title
        merged_lower = f'{title} {container_text}'.lower()

        if not is_relevant and normalized_terms:
            is_relevant = any(term in merged_lower for term in normalized_terms)

        has_alert_metadata = bool(_extract_alert_number(merged_lower) or _parse_date(merged_lower))
        is_generic_menu_item = title.strip().lower() in {'alertas', 'alerta', 'tecnovigilância', 'tecnovigilancia'}

        if contains_alert_word and not has_alert_metadata and not any(term in merged_lower for term in [registro.lower()] + normalized_terms):
            continue

        if is_generic_menu_item:
            continue

        if not is_relevant or full_link in seen_links:
            continue

        merged_text = f'{title} {container_text}'

        alerts.append({
            'title': title,
            'number': _extract_alert_number(merged_text),
            'date': _parse_date(merged_text),
            'summary': container_text[:400],
            'link': full_link,
        })
        seen_links.add(full_link)

    return alerts


def _classify_request_failure(exc: Exception) -> str:
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response is not None and response.status_code in {401, 403}:
            return STATUS_BLOCKED
        if response is not None and response.status_code in {502, 503, 504}:
            return STATUS_UNAVAILABLE
    if isinstance(exc, (requests.Timeout, requests.ConnectionError, requests.SSLError)):
        return STATUS_UNAVAILABLE
    return STATUS_UNAVAILABLE


def _build_warning(status: str, details: str | None = None) -> str:
    base = {
        STATUS_BLOCKED: 'Consulta automática bloqueada pela fonte (ex.: 403 ou validação anti-bot).',
        STATUS_UNAVAILABLE: 'Fonte de alertas temporariamente indisponível (timeout, rede ou portal fora do ar).',
        STATUS_PARSING_ERROR: 'A consulta retornou conteúdo, mas ocorreu falha no parsing dos alertas.',
        STATUS_PARTIAL: 'Consulta automática parcial: a fonte principal falhou e o fallback só permite navegação manual.',
        STATUS_NO_RESULTS: 'Nenhum alerta encontrado para os termos informados nas fontes consultadas.',
    }.get(status, 'Falha na consulta automática de alertas.')

    if details:
        return f'{base} Detalhes técnicos: {details}'
    return base


def _manual_links(registro: str) -> dict[str, str]:
    return {
        'principal': f'{ALERTS_PAGE_URL}?tagsName={registro}',
        'tecnovigilancia': GOVBR_TECNOVIG_ALERTS_URL,
    }


def _query_legacy_alerts_source(registro: str, terms: list[str]) -> tuple[list[dict[str, Any]], str | None, str | None]:
    try:
        response = get(ALERTS_PAGE_URL, params={'tagsName': registro})
    except Exception as exc:
        return [], _classify_request_failure(exc), str(exc)

    try:
        return _parse_alerts(response.text, registro, terms), None, None
    except Exception as exc:
        return [], STATUS_PARSING_ERROR, str(exc)


def _query_govbr_fallback_page() -> tuple[dict[str, Any], str | None, str | None]:
    try:
        response = get(GOVBR_TECNOVIG_ALERTS_URL)
        soup = BeautifulSoup(response.text, 'html.parser')
        useful_links: list[dict[str, str]] = []

        for link in soup.select('a[href]'):
            title = link.get_text(' ', strip=True)
            href = link.get('href', '').strip()
            if not title or not href:
                continue
            lowered = f'{title} {href}'.lower()
            if any(term in lowered for term in ('alerta', 'tecnovigil', 'ação de campo', 'sistec')):
                useful_links.append({'title': title, 'link': href})

        return {'reference_links': useful_links[:8]}, None, None
    except Exception as exc:
        return {}, _classify_request_failure(exc), str(exc)


def find_alerts_by_registration(registro: str, product: dict[str, Any] | None = None) -> dict[str, Any]:
    manufacturer = (product or {}).get('fabricante') or ''
    product_name = (product or {}).get('nome_produto') or ''
    holder = (product or {}).get('detentor_registro') or ''

    search_terms = [registro, manufacturer, product_name, holder]
    search_terms = [term.strip() for term in search_terms if term and term.strip()]

    alerts, primary_error_status, primary_error_details = _query_legacy_alerts_source(registro, search_terms)

    sources = [{
        'name': 'anvisa_legado_tagsName',
        'url': ALERTS_PAGE_URL,
        'status': 'ok' if primary_error_status is None else primary_error_status,
        'details': primary_error_details,
    }]

    manual_links = _manual_links(registro)

    if alerts:
        return {
            'alerts': alerts,
            'status': 'success',
            'warning': None,
            'manual_url': manual_links['principal'],
            'manual_links': manual_links,
            'sources': sources,
        }

    # Fallback oficial no portal gov.br (página atual de tecnovigilância)
    fallback_data, fallback_error_status, fallback_error_details = _query_govbr_fallback_page()
    sources.append({
        'name': 'anvisa_govbr_tecnovigilancia',
        'url': GOVBR_TECNOVIG_ALERTS_URL,
        'status': 'ok' if fallback_error_status is None else fallback_error_status,
        'details': fallback_error_details,
    })

    if primary_error_status and fallback_error_status:
        combined_status = primary_error_status if primary_error_status != STATUS_NO_RESULTS else fallback_error_status
        return {
            'alerts': [],
            'status': combined_status,
            'warning': _build_warning(combined_status, primary_error_details),
            'manual_url': manual_links['tecnovigilancia'],
            'manual_links': manual_links,
            'sources': sources,
        }

    if primary_error_status and fallback_error_status is None:
        return {
            'alerts': [],
            'status': STATUS_PARTIAL,
            'warning': _build_warning(STATUS_PARTIAL, primary_error_details),
            'manual_url': manual_links['tecnovigilancia'],
            'manual_links': manual_links,
            'sources': sources,
            'reference_links': fallback_data.get('reference_links', []),
        }

    return {
        'alerts': [],
        'status': STATUS_NO_RESULTS,
        'warning': None,
        'manual_url': manual_links['principal'],
        'manual_links': manual_links,
        'sources': sources,
    }
