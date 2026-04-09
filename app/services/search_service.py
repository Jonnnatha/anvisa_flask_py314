from __future__ import annotations

import re
from typing import Any, Dict

from app.core.config import ALERTS_PAGE_URL, PRODUCTS_PAGE_URL
from app.services.alerts_service import find_alerts_by_registration
from app.services.product_service import find_product_by_registration


def validate_registration(value: str) -> str:
    registro = re.sub(r'\D', '', value or '')
    if len(registro) != 11:
        raise ValueError('O registro ANVISA deve conter exatamente 11 dígitos.')
    return registro


def search_by_registration(value: str) -> Dict[str, Any]:
    registro = validate_registration(value)
    product = find_product_by_registration(registro)

    if not product:
        return {
            'registro_anvisa': registro,
            'found': False,
            'source_product': PRODUCTS_PAGE_URL,
            'source_alerts': ALERTS_PAGE_URL,
            'product': None,
            'alerts_count': 0,
            'alerts': [],
            'message': 'Registro não encontrado na base consultada da Anvisa.',
        }

    alerts = find_alerts_by_registration(registro)
    return {
        'registro_anvisa': registro,
        'found': True,
        'source_product': PRODUCTS_PAGE_URL,
        'source_alerts': ALERTS_PAGE_URL,
        'product': product,
        'alerts_count': len(alerts),
        'alerts': alerts,
        'message': 'Registro encontrado.' if not alerts else 'Registro encontrado e alertas localizados.',
    }
