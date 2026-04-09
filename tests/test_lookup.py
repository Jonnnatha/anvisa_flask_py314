from app.services.alert_service import AlertService
from app.services.lookup_service import LookupService
from app.services.product_service import ProductService


class FakeClient:
    def __init__(self, responses):
        self.responses = responses

    def get_json(self, url, params=None):
        key = (url, tuple(sorted((params or {}).items())))
        return self.responses.get(key) or self.responses.get(url)


class Response:
    def __init__(self, ok, data=None, error=None):
        self.ok = ok
        self.data = data
        self.error = error


def test_product_not_found():
    service = ProductService(client=FakeClient({url: Response(False, error="403") for url in ProductService.API_CANDIDATES}))
    result = service.lookup("12345")
    assert result.found is False


def test_alert_fallback_on_failure():
    alert_service = AlertService(client=FakeClient({url: Response(False, error="403") for url in AlertService.API_CANDIDATES}))
    result = alert_service.lookup("12345")
    assert result.automatic_lookup_failed is True
    assert result.alerts == []


def test_lookup_happy_path_with_alert():
    product_payload = {"content": [{"numeroRegistro": "12345", "nomeProduto": "Monitor", "marca": "Acme"}]}
    alert_payload = {"content": [{"registro": "12345", "titulo": "Recall", "numero": "12", "data": "2026-01-01", "link": "https://example.com"}]}

    product_client = FakeClient({ProductService.API_CANDIDATES[0]: Response(True, product_payload)})
    alert_client = FakeClient({AlertService.API_CANDIDATES[0]: Response(True, alert_payload)})

    lookup = LookupService(ProductService(product_client), AlertService(alert_client))
    result = lookup.search("12345")

    assert result.found is True
    assert result.product["nome_produto"] == "Monitor"
    assert len(result.alerts) == 1
