"""Gestion des callouts HTTP Apex — Named Credentials et appels réels."""

import yaml
import requests


def load_named_credentials(path: str) -> dict:
    """Charge les Named Credentials depuis un fichier YAML.

    Format attendu:
        MyCredential:
          url: http://localhost:5555
          headers:
            Authorization: Bearer xxx
            Content-Type: application/json
    """
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data


def resolve_endpoint(endpoint: str, credentials: dict) -> tuple[str, dict]:
    """Résout un endpoint avec Named Credentials.

    Salesforce utilise le format: callout:NomCredential/path
    Retourne (url_complète, headers_supplémentaires).
    """
    extra_headers = {}
    if endpoint.startswith("callout:"):
        rest = endpoint[len("callout:"):]
        # Séparer nom de credential et path
        if "/" in rest:
            cred_name, path = rest.split("/", 1)
            path = "/" + path
        else:
            cred_name = rest
            path = ""
        cred = credentials.get(cred_name)
        if cred is None:
            raise Exception(
                "Named Credential '{}' introuvable. "
                "Credentials disponibles: {}".format(
                    cred_name, list(credentials.keys())
                )
            )
        base_url = cred.get("url", "").rstrip("/")
        endpoint = base_url + path
        extra_headers = dict(cred.get("headers", {}))
    return endpoint, extra_headers


def execute_callout(req: dict, credentials: dict) -> dict:
    """Exécute un appel HTTP réel à partir d'un HttpRequest Apex.

    req: dict avec _type=HttpRequest, _endpoint, _method, _body, _headers, _timeout
    credentials: dict des Named Credentials chargées depuis YAML

    Retourne un dict HttpResponse Apex.
    """
    endpoint = req.get("_endpoint", "")
    method = (req.get("_method", "GET") or "GET").upper()
    body = req.get("_body", "")
    req_headers = dict(req.get("_headers", {}) or {})
    timeout = req.get("_timeout")

    # Résoudre Named Credential
    endpoint, cred_headers = resolve_endpoint(endpoint, credentials)

    # Merger headers: credential headers en base, request headers en override
    headers = {**cred_headers, **req_headers}

    # Timeout en secondes (Apex le donne en ms)
    timeout_s = (timeout / 1000.0) if timeout else 30

    # Appel HTTP réel
    resp = requests.request(
        method=method,
        url=endpoint,
        headers=headers,
        data=body if body else None,
        timeout=timeout_s,
    )

    # Construire la réponse Apex
    resp_headers = dict(resp.headers)
    return {
        "_type": "HttpResponse",
        "_statusCode": resp.status_code,
        "_body": resp.text,
        "_headers": resp_headers,
    }
