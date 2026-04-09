from flask import Flask, jsonify, render_template, request

from app.services.search_service import search_by_registration


def create_app() -> Flask:
    app = Flask(__name__, template_folder='templates', static_folder='static')

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/consultar')
    def consultar():
        registro = request.args.get('registro', '')
        try:
            data = search_by_registration(registro)
            status = 200 if data.get('found') else 404
            return jsonify(data), status
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            return jsonify({'error': f'Falha na consulta: {exc}'}), 502

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
