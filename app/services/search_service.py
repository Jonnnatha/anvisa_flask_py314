from __future__ import annotations

import re
from typing import Any

from app.core.config import ANVISA_PRODUCT_API_URL
from app.services.alerts_service import find_alerts_by_registration
from app.services.materials_service import find_related_materials
from app.services.product_enrichment_service import enrich_product_data
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


def _build_base_response(registro: str) -> dict[str, Any]:
    return {
        'registro_anvisa': registro,
        'found': False,
        'product': None,
        'official_data': {},
        'enriched_data': {},
        'product_data': {},
        'alerts_count': 0,
        'alerts': [],
        'materials_or_signals': [],
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
    enrichment_result = enrich_product_data(product, alerts=alerts_result.get('alerts', []))
    materials_product_context = dict(product)
    materials_product_context.update(enrichment_result.get('enriched_data', {}))
    materials_result = find_related_materials(registro, product=materials_product_context)
    enrichment_result = enrich_product_data(
        product,
        alerts=alerts_result.get('alerts', []),
        indexed_documents=materials_result.get('items', []),
    )

    result.update(
        {
            'found': True,
            'message': 'Consulta realizada com sucesso.',
            'source_product': ANVISA_PRODUCT_API_URL,
            'product': product,
            'official_data': enrichment_result.get('official_data', product),
            'enriched_data': enrichment_result.get('enriched_data', {}),
            'product_data': enrichment_result.get('consolidated_product_data', {}),
            'alerts_count': alerts_result.get('count', 0),
            'alerts_status': alerts_result.get('status'),
            'alerts': alerts_result.get('alerts', []),
            'materials_or_signals': materials_result.get('items', []),
            'materials_source': materials_result.get('source'),
            'materials_warning': materials_result.get('warning'),
        }
    )
    return result
