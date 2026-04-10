from __future__ import annotations

import re
from typing import Any

from app.core.config import ALERTS_PAGE_URL, PRODUCTS_PAGE_URL
from app.services.alerts_service import find_alerts_by_registration
from app.services.product_service import (
    ProductAuthenticationError,
    ProductEmptyResponseError,
    ProductLookupError,
    ProductRateLimitError,
    find_product_by_registration,
)


def validate_registration(value: str) -> str:
    registro = re.sub(r'\D', '', value or '')
    if len(registro) != 11:
        raise ValueError('O registro ANVISA deve conter exatamente 11 dígitos.')
    return registro


def _product_error_response(registro: str, message: str, status: str) -> dict[str, Any]:
    return {
        'registro_anvisa': registro,
        'found': False,
        'source_product': PRODUCTS_PAGE_URL,
        'source_alerts': ALERTS_PAGE_URL,
        'source_alerts_fallback': 'https://www.gov.br/anvisa/pt-br/assuntos/fiscalizacao-e-monitoramento/tecnovigilancia/alertas-de-tecnovigilancia-1',
        'product': None,
        'alerts_count': 0,
        'alerts': [],
        'alerts_warning': 'Consulta de alertas não executada: produto indisponível.',
        'alerts_manual_url': f'{ALERTS_PAGE_URL}?tagsName={registro}',
        'complaints_or_signals': [],
        'search_status': {'overall': status, 'web_search_used': False},
        'sources_checked': [],
        'warnings': [message],
        'message': message,
    }


def search_by_registration(value: str) -> dict[str, Any]:
    registro = validate_registration(value)

    try:
        product = find_product_by_registration(registro)
    except ProductAuthenticationError as exc:
        return _product_error_response(registro, str(exc), 'product_auth_error')
    except ProductRateLimitError as exc:
        return _product_error_response(registro, str(exc), 'product_rate_limit')
    except ProductEmptyResponseError as exc:
        return _product_error_response(registro, str(exc), 'product_empty_response')
    except ProductLookupError as exc:
        return _product_error_response(registro, str(exc), 'product_lookup_error')

    if not product:
        return {
            'registro_anvisa': registro,
            'found': False,
            'source_product': PRODUCTS_PAGE_URL,
            'source_alerts': ALERTS_PAGE_URL,
            'source_alerts_fallback': 'https://www.gov.br/anvisa/pt-br/assuntos/fiscalizacao-e-monitoramento/tecnovigilancia/alertas-de-tecnovigilancia-1',
            'product': None,
            'alerts_count': 0,
            'alerts': [],
            'alerts_warning': None,
            'alerts_manual_url': f'{ALERTS_PAGE_URL}?tagsName={registro}',
            'complaints_or_signals': [],
            'search_status': {'overall': 'product_not_found', 'web_search_used': False},
            'sources_checked': [],
            'warnings': [],
            'message': 'Registro não encontrado na API oficial de produtos para saúde da Anvisa.',
        }

    alert_result = find_alerts_by_registration(registro, product=product)
    alerts = alert_result.get('alerts', [])

    return {
        'registro_anvisa': registro,
        'found': True,
        'source_product': PRODUCTS_PAGE_URL,
        'source_alerts': ALERTS_PAGE_URL,
        'source_alerts_fallback': 'https://www.gov.br/anvisa/pt-br/assuntos/fiscalizacao-e-monitoramento/tecnovigilancia/alertas-de-tecnovigilancia-1',
        'product': product,
        'alerts_count': alert_result.get('count', len(alerts)),
        'alerts': alerts,
        'alerts_result': {
            'count': alert_result.get('count', len(alerts)),
            'alert_ids': alert_result.get('alert_ids', []),
            'source': alert_result.get('source'),
            'confidence': alert_result.get('confidence'),
        },
        'alerts_status': alert_result.get('status'),
        'alerts_warning': alert_result.get('warning'),
        'alerts_sources': alert_result.get('sources', []),
        'alerts_strategy_log': alert_result.get('sources', []),
        'sources_checked': alert_result.get('sources_checked', alert_result.get('sources', [])),
        'alerts_reference_links': alert_result.get('reference_links', []),
        'alerts_manual_url': alert_result.get('manual_url'),
        'alerts_manual_links': alert_result.get('manual_links', {}),
        'complaints_or_signals': alert_result.get('complaints_or_signals', []),
        'search_status': alert_result.get('search_status', {'overall': alert_result.get('status')}),
        'warnings': alert_result.get('warnings', []),
        'message': 'Registro encontrado via API oficial da Anvisa.' if not alerts else 'Registro encontrado via API oficial da Anvisa e alertas localizados.',
    }
