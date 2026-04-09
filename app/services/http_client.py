import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0 Safari/537.36"
}

def get(url: str, params=None, timeout: int = 30):
    response = requests.get(
        url,
        params=params,
        headers=DEFAULT_HEADERS,
        timeout=timeout,
        verify=False
    )
    response.raise_for_status()
    return response