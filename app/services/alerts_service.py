import requests
from bs4 import BeautifulSoup

BASE_ALERTS_URL = "https://antigo.anvisa.gov.br/alertas"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://antigo.anvisa.gov.br/",
}

def fetch_alerts_by_registration(registro: str):
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        session.get("https://antigo.anvisa.gov.br/", timeout=30, verify=False)

        response = session.get(
            BASE_ALERTS_URL,
            params={"tagsName": registro},
            timeout=30,
            verify=False
        )

        if response.status_code == 403:
            return {
                "alerts": [],
                "warning": "A consulta automática de alertas foi bloqueada pelo portal da Anvisa.",
                "manual_url": f"{BASE_ALERTS_URL}?tagsName={registro}"
            }

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        alerts = []

        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            href = a["href"]

            if registro in text or "alerta" in text.lower():
                if not href.startswith("http"):
                    href = f"https://antigo.anvisa.gov.br{href}"
                alerts.append({
                    "title": text,
                    "link": href
                })

        return {
            "alerts": alerts,
            "warning": None,
            "manual_url": f"{BASE_ALERTS_URL}?tagsName={registro}"
        }

    except requests.RequestException as e:
        return {
            "alerts": [],
            "warning": f"Falha ao consultar alertas automaticamente: {str(e)}",
            "manual_url": f"{BASE_ALERTS_URL}?tagsName={registro}"
        }