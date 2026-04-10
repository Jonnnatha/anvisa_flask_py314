from __future__ import annotations

import re
from typing import Any

from app.core.config import ANVISA_PRODUCT_API_URL, EXTERNAL_ALERT_LOOKUP_BASE_URL
from app.services.alerts_service import find_alerts_by_registration
from app.services.product_service import (
    ProductAuthenticationError,
    ProductEmptyResponseError,
    ProductLookupError,
    ProductRateLimitError,
    find_product_by_registration,
)
from app.services.signals_service import find_related_public_signals


def validate_registration(value: str) -> str:
    registro = re.sub(r'\D', '', value or '')
    if len(registro) != 11:
        raise ValueError('O registro ANVISA deve conter exatamente 11 dígitos.')
    return registro


def _build_base_response(registro: str) -> dict[str, Any]:
    return {
        'registro_anvisa': registro,
        'found': False,
        'origens': {
            'produto': 'API oficial ANVISA (POST /consulta/saude)',
            'alertas': f'Fonte externa de apoio ({EXTERNAL_ALERT_LOOKUP_BASE_URL.rstrip("/")})',
            'sinais_publicos': 'Busca pública em gov.br/anvisa com filtro de relevância',
        },
        'product': None,
        'alerts_count': 0,
        'alerts': [],
        'complaints_or_signals': [],
    }


def search_by_registration(value: str) -> dict[str, Any]:
    registro = validate_registration(value)
    result = _build_base_response(registro)

    try:
        product = find_product_by_registration(registro)
    except ProductAuthenticationError as exc:
        result['message'] = str(exc)
        result['error_code'] = 'product_auth_error'
        return result
    except ProductRateLimitError as exc:
        result['message'] = str(exc)
        result['error_code'] = 'product_rate_limit'
        return result
    except ProductEmptyResponseError as exc:
        result['message'] = str(exc)
        result['error_code'] = 'product_empty_response'
        return result
    except ProductLookupError as exc:
        result['message'] = str(exc)
        result['error_code'] = 'product_lookup_error'
        return result

    if not product:
        result['message'] = 'Registro não encontrado na API oficial de produtos para saúde da Anvisa.'
        return result

    alerts_result = find_alerts_by_registration(registro)
    signals_result = find_related_public_signals(registro, product=product)

    result.update(
        {
            'found': True,
            'message': 'Consulta realizada com sucesso.',
            'source_product': ANVISA_PRODUCT_API_URL,
            'product': product,
            'alerts_count': alerts_result.get('count', 0),
            'alerts_status': alerts_result.get('status'),
            'alerts_source': alerts_result.get('source'),
            'alerts_warning': alerts_result.get('warning'),
            'alerts': alerts_result.get('alerts', []),
            'complaints_or_signals': signals_result.get('items', []),
            'signals_warning': signals_result.get('warning'),
            'signals_source': signals_result.get('source'),
        }
    )
    return result
