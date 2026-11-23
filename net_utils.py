"""Download de dados públicos da ANM e da ANA.

Os servidores dadosabertos.anm.gov.br e www.snirh.gov.br às vezes não enviam a cadeia
intermediária do certificado, e o Python do Streamlit Cloud recusa a conexão
(CERTIFICATE_VERIFY_FAILED). Nesse caso, e só para esses domínios públicos, refaz a
consulta sem verificar o certificado — é leitura de dados abertos, nada é enviado.
"""
from __future__ import annotations

from urllib.parse import urlparse

import requests
import urllib3

try:  # usa os certificados do sistema operacional quando disponível
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

HEADERS = {"User-Agent": "Mozilla/5.0 (painel-barragens CREA-MS)"}
HOSTS_PUBLICOS = ("anm.gov.br", "snirh.gov.br")


def _publico(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in HOSTS_PUBLICOS)


def baixar(url: str, params: dict | None = None, timeout: int = 120) -> tuple[requests.Response, bool]:
    """Retorna (resposta, usou_fallback_sem_verificacao)."""
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        inseguro = False
    except requests.exceptions.SSLError:
        if not _publico(url):
            raise
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout, verify=False)
        inseguro = True
    r.raise_for_status()
    return r, inseguro
