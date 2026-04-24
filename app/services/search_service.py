from __future__ import annotations

import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any

from app.core.config import ANVISA_PRODUCT_API_URL, MATERIALS_TOTAL_TIMEOUT
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

LOGGER = logging.getLogger(__name__)
MATERIALS_TIMEOUT_WARNING = 'A busca falhou por timeout nesta consulta.'


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
        'materials_status': 'no_results',
        'materials_recommended_searches': [],
        'materials_diagnostics': {},
    }


def _fallback_materials_diagnostics(status: str, message: str, step: str, error_type: str) -> dict[str, Any]:
    return {
        'search_status': status,
        'errors': [{'step': step, 'type': error_type, 'message': message}],
        'queries_used': [],
        'sources_checked': [],
        'raw_results_count': 0,
        'accepted_results_count': 0,
        'discarded_results_count': 0,
        'dedupe_removed_count': 0,
        'discard_reasons': {},
        'duration_ms': 0,
        'query_metadata': {},
        'strategies': [],
        'strategy_feedback': {},
        'generated_queries': [],
        'pipeline_logs': [],
        'pipeline_summary': {
            'query_builder': 'not_executed',
            'source_fetcher': 'not_executed',
            'result_parser': 'not_executed',
            'result_classifier': 'not_executed',
            'result_ranker': 'not_executed',
            'result_filter': 'not_executed',
            'result_formatter': 'not_executed',
        },
    }


def search_by_registration(value: str) -> dict[str, Any]:
    registro = validate_registration(value)
    result = _build_base_response(registro)
    started_at = time.perf_counter()
    LOGGER.info('search.start registro=%s', registro)

    alerts_result: dict[str, Any]
    alerts_started = time.perf_counter()
    try:
        alerts_result = find_alerts_by_registration(registro)
        LOGGER.info('search.alerts.success registro=%s duracao_ms=%s', registro, int((time.perf_counter() - alerts_started) * 1000))
    except Exception as exc:
        LOGGER.exception('search.alerts.error registro=%s erro=%s', registro, exc)
        alerts_result = {'status': 'alerts_error', 'count': 0, 'alerts': [], 'warning': str(exc)}

    try:
        product_started = time.perf_counter()
        product = find_product_by_registration(registro)
        LOGGER.info('search.product.success registro=%s duracao_ms=%s', registro, int((time.perf_counter() - product_started) * 1000))
    except ProductAuthenticationError as exc:
        LOGGER.warning('search.product.auth_error registro=%s erro=%s', registro, exc)
        result['message'] = str(exc)
        result['error_code'] = 'product_auth_error'
        return result
    except ProductRateLimitError as exc:
        LOGGER.warning('search.product.rate_limit registro=%s erro=%s', registro, exc)
        result['message'] = str(exc)
        result['error_code'] = 'product_rate_limit'
        return result
    except ProductEmptyResponseError as exc:
        LOGGER.warning('search.product.empty registro=%s erro=%s', registro, exc)
        result['message'] = str(exc)
        result['error_code'] = 'product_empty_response'
        return result
    except ProductLookupError as exc:
        LOGGER.warning('search.product.lookup_error registro=%s erro=%s', registro, exc)
        result['message'] = str(exc)
        result['error_code'] = 'product_lookup_error'
        return result

    if not product:
        LOGGER.info('search.product.not_found registro=%s alerts_count=%s', registro, alerts_result.get('count', 0))
        result.update(
            {
                'found': bool(alerts_result.get('alerts')),
                'message': (
                    'Registro não encontrado na API oficial de produtos para saúde da Anvisa, '
                    'mas alertas relacionados foram encontrados.'
                    if alerts_result.get('alerts')
                    else 'Registro não encontrado na API oficial de produtos para saúde da Anvisa.'
                ),
                'alerts_count': alerts_result.get('count', 0),
                'alerts_status': alerts_result.get('status'),
                'alerts': alerts_result.get('alerts', []),
            }
        )
        return result

    enrichment_result = enrich_product_data(product, alerts=alerts_result.get('alerts', []))
    materials_product_context = dict(product)
    materials_product_context.update(enrichment_result.get('enriched_data', {}))
    materials_result: dict[str, Any] = {
        'items': [],
        'status': 'timeout',
        'warning': MATERIALS_TIMEOUT_WARNING,
        'source': [],
        'recommended_searches': [],
        'diagnostics': {},
    }
    materials_started = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(find_related_materials, registro, materials_product_context)
            materials_result = future.result(timeout=MATERIALS_TOTAL_TIMEOUT + 1)
        LOGGER.info('search.materials.success registro=%s duracao_ms=%s', registro, int((time.perf_counter() - materials_started) * 1000))
    except FutureTimeoutError:
        LOGGER.warning('search.materials.timeout registro=%s timeout_s=%s', registro, MATERIALS_TOTAL_TIMEOUT + 1)
        materials_result = {
            'items': [],
            'status': 'timeout',
            'warning': MATERIALS_TIMEOUT_WARNING,
            'source': [],
            'recommended_searches': [],
            'diagnostics': _fallback_materials_diagnostics(
                'timeout',
                'Tempo limite excedido na execução da busca de materiais.',
                'materials_thread',
                'timeout',
            ),
        }
    except Exception as exc:
        LOGGER.exception('search.materials.error registro=%s erro=%s', registro, exc)
        materials_result = {
            'items': [],
            'status': 'unexpected_error',
            'warning': 'Não foi possível concluir a busca por erro inesperado.',
            'source': [],
            'recommended_searches': [],
            'diagnostics': _fallback_materials_diagnostics(
                'unexpected_error',
                str(exc),
                'materials_thread',
                'unexpected_error',
            ),
        }

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
            'materials_status': materials_result.get('status', 'no_results'),
            'materials_warning': materials_result.get('warning'),
            'materials_recommended_searches': materials_result.get('recommended_searches', []),
            'materials_diagnostics': materials_result.get('diagnostics', {}),
        }
    )
    LOGGER.info('search.done registro=%s found=%s duracao_ms=%s', registro, result.get('found', False), int((time.perf_counter() - started_at) * 1000))
    return result
