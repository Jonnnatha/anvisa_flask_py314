from __future__ import annotations

from flask import Blueprint, render_template, request

from app.services.lookup_service import LookupService

main_bp = Blueprint("main", __name__)
lookup_service = LookupService()


@main_bp.get("/")
def index():
    return render_template("index.html")


@main_bp.post("/consultar")
def consultar():
    registro = request.form.get("registro", "").strip()

    if not registro:
        return render_template(
            "index.html",
            error_message="Informe um número de registro ANVISA para consultar.",
        )

    result = lookup_service.search(registro)

    if not result.found:
        return render_template(
            "index.html",
            registro=registro,
            error_message="Registro não encontrado automaticamente. Você pode validar manualmente no portal ANVISA.",
            technical_error=result.product_error,
            manual_product_url=result.manual_product_url,
        )

    info_message = None
    if result.automatic_alert_lookup_failed:
        info_message = (
            "A consulta automática de alertas falhou (ex.: bloqueio 403/SSL/fonte indisponível). "
            "Use o link de consulta manual abaixo."
        )

    return render_template(
        "index.html",
        registro=registro,
        result=result,
        info_message=info_message,
    )
