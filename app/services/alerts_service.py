from __future__ import annotations

import re
from typing import Any

import requests

from app.core.config import EXTERNAL_ALERT_LOOKUP_BASE_URL, REQUEST_TIMEOUT, SSL_VERIFY, USER_AGENT

ALERT_NUMBER_RE = re.compile(r'\b\d{3,6}\b')


def _parse_alert_numbers(text: str) -> list[str]:
    if not text:
        return []

    match = re.search(r'Alerta\(s\)\s*:\s*\[([^\]]*)\]', text, flags=re.IGNORECASE)
    if match:
        numbers = ALERT_NUMBER_RE.findall(match.group(1))
    else:
        numbers = ALERT_NUMBER_RE.findall(text)

    unique: list[str] = []
    for number in numbers:
        if number not in unique:
            unique.append(number)
    return unique


def _build_manual_link(numero_alerta: str) -> str:
    return (
        'https://www.gov.br/anvisa/pt-br/search'
        f'?SearchableText=alerta%20{numero_alerta}%20anvisa'
    )


def find_alerts_by_registration(registro: str) -> dict[str, Any]:
    base_url = EXTERNAL_ALERT_LOOKUP_BASE_URL.rstrip('/')
    lookup_url = f'{base_url}/registro/{registro}'

    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'text/plain,text/html,application/json;q=0.9,*/*;q=0.8',
    }

    try:
        response = requests.get(lookup_url, timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY, headers=headers)
        response.raise_for_status()
    except requests.RequestException as exc:
        return {
            'status': 'external_source_error',
            'source': lookup_url,
            'count': 0,
            'alerts': [],
            'warning': f'Falha ao consultar fonte externa de apoio para alertas: {exc}',
        }

    numbers = _parse_alert_numbers(response.text)
    alerts = [
        {
            'numero_alerta': number,
            'link_pesquisa_manual': _build_manual_link(number),
            'origem_da_descoberta': 'Fonte externa de apoio: brunoroma.pythonanywhere.com',
            'nivel_confianca': 'medio',
        }
        for number in numbers
    ]

    return {
        'status': 'alerts_found' if alerts else 'no_alerts_found',
        'source': lookup_url,
        'count': len(alerts),
        'alerts': alerts,
        'warning': None,
    }
