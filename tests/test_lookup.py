import unittest

from app.services.alert_service import AlertService
from app.services.lookup_service import LookupService
from app.services.product_service import ProductService


class FakeResponse:
    def __init__(self, ok: bool, data=None, error: str | None = None, url: str | None = None):
        self.ok = ok
        self.data = data
        self.error = error
        self.url = url


class FakeClient:
    def __init__(self, mapping):
        self.mapping = mapping

    def get_json(self, url, params=None):
        return self.mapping.get(url, FakeResponse(False, error="404"))


class ServicesTestCase(unittest.TestCase):
    def test_product_not_found(self):
        client = FakeClient({url: FakeResponse(False, error="403") for url in ProductService.API_CANDIDATES})
        service = ProductService(client=client)

        result = service.lookup("12345")

        self.assertFalse(result.found)
        self.assertIn("403", result.error)

    def test_alert_fallback_when_all_endpoints_fail(self):
        client = FakeClient({url: FakeResponse(False, error="403") for url in AlertService.API_CANDIDATES})
        service = AlertService(client=client)

        result = service.lookup("12345")

        self.assertTrue(result.automatic_lookup_failed)
        self.assertEqual([], result.alerts)

    def test_lookup_happy_path(self):
        product_payload = {"content": [{"numeroRegistro": "12345", "nomeProduto": "Monitor", "marca": "Acme"}]}
        alert_payload = {"content": [{"registro": "12345", "titulo": "Recall", "numero": "12", "data": "2026-01-01"}]}

        product_service = ProductService(
            client=FakeClient({ProductService.API_CANDIDATES[0]: FakeResponse(True, data=product_payload, url="http://fake")})
        )
        alert_service = AlertService(
            client=FakeClient({AlertService.API_CANDIDATES[0]: FakeResponse(True, data=alert_payload, url="http://fake")})
        )
        lookup = LookupService(product_service=product_service, alert_service=alert_service)

        result = lookup.search("12345")

        self.assertTrue(result.found)
        self.assertEqual("Monitor", result.product["nome_produto"])
        self.assertEqual(1, len(result.alerts))


if __name__ == "__main__":
    unittest.main()
