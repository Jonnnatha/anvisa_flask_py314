from flask import Blueprint, jsonify, render_template, request

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
