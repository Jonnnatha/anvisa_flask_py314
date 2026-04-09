from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.core.config import ALERTS_PAGE_URL
from app.services.http_client import get

ALERT_NUMBER_RE = re.compile(r'(?:alerta\s*n?[ºo]?\s*[:\-]?\s*)(\d+[\w\-/]*)', re.IGNORECASE)
DATE_RE = re.compile(r'(\d{2}/\d{2}/\d{4})')


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


def _parse_alerts(html: str, registro: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, 'html.parser')
    alerts: list[dict[str, Any]] = []
    seen_links: set[str] = set()

    for link in soup.select('a[href]'):
        href = link.get('href', '').strip()
        title = link.get_text(' ', strip=True)
        if not href or not title:
            continue

        full_link = urljoin(ALERTS_PAGE_URL, href)
        lower_title = title.lower()
        if 'alerta' not in lower_title and registro not in title:
            continue
        if full_link in seen_links:
            continue

        container_text = link.parent.get_text(' ', strip=True) if link.parent else title
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


def find_alerts_by_registration(registro: str) -> dict[str, Any]:
    manual_url = f'{ALERTS_PAGE_URL}?tagsName={registro}'

    try:
        response = get(ALERTS_PAGE_URL, params={'tagsName': registro})
        alerts = _parse_alerts(response.text, registro)
        return {
            'alerts': alerts,
            'warning': None,
            'manual_url': manual_url,
        }
    except Exception as exc:
        return {
            'alerts': [],
            'warning': (
                'Falha na consulta automática de alertas (possível bloqueio 403, SSL ou '
                f'indisponibilidade do portal): {exc}'
            ),
            'manual_url': manual_url,
        }
