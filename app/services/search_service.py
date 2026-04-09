from __future__ import annotations

import re
from typing import Any

from app.core.config import ALERTS_PAGE_URL, PRODUCTS_PAGE_URL
from app.services.alerts_service import find_alerts_by_registration
from app.services.product_service import find_product_by_registration


def validate_registration(value: str) -> str:
    registro = re.sub(r'\D', '', value or '')
    if len(registro) != 11:
        raise ValueError('O registro ANVISA deve conter exatamente 11 dígitos.')
    return registro


def search_by_registration(value: str) -> dict[str, Any]:
    registro = validate_registration(value)
    product = find_product_by_registration(registro)

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
            'message': 'Registro não encontrado na base consultada da Anvisa.',
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
        'alerts_count': len(alerts),
        'alerts': alerts,
        'alerts_status': alert_result.get('status'),
        'alerts_warning': alert_result.get('warning'),
        'alerts_sources': alert_result.get('sources', []),
        'alerts_reference_links': alert_result.get('reference_links', []),
        'alerts_manual_url': alert_result.get('manual_url'),
        'alerts_manual_links': alert_result.get('manual_links', {}),
        'message': 'Registro encontrado.' if not alerts else 'Registro encontrado e alertas localizados.',
    }
