from flask import Blueprint, jsonify, render_template, request

from .services.alerts_service import search_alerts, summarize_alerts
from .services.search_service import search_by_registration

web = Blueprint('web', __name__)


@web.get('/')
def index():
    return render_template('index.html')


@web.get('/api/consultar')
def consultar():
    registro = request.args.get('registro', '')
    try:
        data = search_by_registration(registro)
        return jsonify(data), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': f'Falha na consulta: {exc}'}), 502


@web.get('/api/alertas')
def consultar_alertas():
    try:
        data = search_alerts(
            fabricante=request.args.get('fabricante', ''),
            registro=request.args.get('registro', ''),
            nome_comercial=request.args.get('nome_comercial', ''),
            nome_tecnico=request.args.get('nome_tecnico', ''),
            data_inicio=request.args.get('data_inicio', ''),
            data_fim=request.args.get('data_fim', ''),
        )
        return jsonify(data), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': f'Falha na consulta de alertas: {exc}'}), 502


@web.get('/api/relatorios/resumo')
def consultar_resumo_alertas():
    registros_base_raw = request.args.get('registros_base', '')
    registros_base = [item.strip() for item in registros_base_raw.split(',') if item.strip()]
    try:
        data = summarize_alerts(
            periodo=request.args.get('periodo', 'diario'),
            referencia=request.args.get('referencia', ''),
            registros_base=registros_base,
        )
        return jsonify(data), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': f'Falha na geração do resumo: {exc}'}), 502
