"""Exceptions de contrôle de flux et fonctions utilitaires de l'interpréteur."""

from __future__ import annotations


class ReturnException(Exception):
    """Signal interne pour return."""

    def __init__(self, value=None):
        self.value = value


class ApexException(Exception):
    """Exception Apex (throw new ...)."""
    pass


class AssertException(ApexException):
    """Échec d'assertion (System.assert*, Assert.*) — distinguée pour que les
    runners de test classent le test en FAIL plutôt qu'en ERROR."""
    pass


class ApexToken(dict):
    """Dict hashable pour les tokens Apex immuables (SObjectType, SObjectField,
    Describe*Result…) — utilisables comme clés de Map ou éléments de Set."""

    def __hash__(self):
        return hash((self.get("_type"), self.get("name"), self.get("_sobject")))

    def __eq__(self, other):
        return isinstance(other, dict) and dict.__eq__(self, other)

    def __ne__(self, other):
        return not self.__eq__(other)


def _ci_key(d, name):
    """Clé exacte, sinon insensible à la casse (Apex l'est partout).
    Retourne la clé réelle du dict, ou None si absente."""
    if name in d:
        return name
    nl = name.lower()
    for k in d:
        if isinstance(k, str) and k.lower() == nl:
            return k
    return None


def format_error(exc) -> str:
    """Message d'erreur runtime préfixé de sa localisation Apex si connue :
    'XPLPrepareService:73 — <message>'. L'interpréteur attache _emusf_location
    (nom de classe, ligne) à l'exception au plus près du statement fautif."""
    loc = getattr(exc, "_emusf_location", None)
    if loc:
        cls, line = loc
        where = "{}:{}".format(cls, line) if cls else "ligne {}".format(line)
        if line is not None:
            return "{} — {}".format(where, exc)
    return str(exc)


class BreakException(Exception):
    pass


class ContinueException(Exception):
    pass


def _common_prefix_len(a, b):
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    return i if i < max(len(a), len(b)) else -1


def _common_prefix(a, b):
    n = _common_prefix_len(a, b)
    return a[:n] if n >= 0 else a


def _unescape_html(s):
    import html
    return html.unescape(s)


from decimal import Decimal as _Decimal

_NUM_RE = __import__("re").compile(r"-?\d+(\.\d+)?$")


def _json_clean(value):
    """Prépare une valeur Apex pour JSON.serialize :
    - retire les clés internes de l'émulateur (_type, _class, _chain, _sobject_type)
    - convertit les nombres stockés en TEXT ('0.7', '2025') en vrais nombres
      (les tables auto-créées stockent tout en TEXT, mais les API attendent des
      nombres pour temperature, max_tokens, etc.)
    """
    internal = {"_type", "_class", "_chain", "_sobject_type", "_context_type"}
    if isinstance(value, dict):
        return {k: _json_clean(v) for k, v in value.items()
                if not (isinstance(k, str) and k.startswith("_")) and k not in internal}
    if isinstance(value, (list, tuple, set)):
        return [_json_clean(v) for v in value]
    if isinstance(value, str) and _NUM_RE.match(value):
        # Ne pas convertir les Id/refs (préfixes alphanumériques) : _NUM_RE
        # n'accepte que des nombres purs
        return float(value) if "." in value else int(value)
    if isinstance(value, _Decimal):
        # Decimal (colonnes numériques PG) → nombre JSON, pas une chaîne
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _apex_str(value) -> str:
    """String.valueOf(value) façon Apex.

    Pour une instance de classe, Salesforce renvoie 'NomClasse:[champ=val, ...]'
    (le préfixe 'NomClasse:' est utilisé par des frameworks comme QueueableJob
    via String.valueOf(this).split(':')[0] pour retrouver le type)."""
    if isinstance(value, dict):
        cls = value.get("_class")
        name = value.get("_type")
        if cls is not None and name:
            fields = {k: v for k, v in value.items() if not k.startswith("_")}
            body = ", ".join("{}={}".format(k, _apex_str(v)) for k, v in fields.items())
            return "{}:[{}]".format(name, body)
        if value.get("_type") == "Blob":
            data = value.get("_data", b"")
            return data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


def _field_of(record, field):
    """Accès champ insensible à la casse sur un SObject (dict)."""
    if not isinstance(record, dict):
        return None
    if field in record:
        return record[field]
    fl = field.lower()
    for k, v in record.items():
        if k.lower() == fl:
            return v
    return None


def _is_soql_literal(s) -> bool:
    """True si la chaîne est un littéral SOQL/SOSL inline '[SELECT ...]'."""
    if not isinstance(s, str):
        return False
    t = s.strip()
    return t.startswith("[") and t.endswith("]") and \
        t[1:].lstrip()[:6].upper() in ("SELECT", "FIND")


def _blob_bytes(val) -> bytes:
    """Normalise un Blob Apex en bytes : accepte le wrapper
    {'_type': 'Blob', '_data': ...}, des bytes bruts ou une chaîne."""
    if isinstance(val, dict) and val.get("_type") == "Blob":
        val = val.get("_data", b"")
    if isinstance(val, (bytes, bytearray)):
        return bytes(val)
    if isinstance(val, str):
        return val.encode("utf-8")
    return b""

