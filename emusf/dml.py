"""Types DML partagés entre les implémentations d'org."""

# --- Base-62 ID generation (Salesforce-realistic 18-char IDs) ---

CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(CHARSET)  # 62
_DECODE = {c: i for i, c in enumerate(CHARSET)}

CHECKSUM_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"

# Pod/instance identifier (fixe par org, configurable)
DEFAULT_POD = "IV"

# Compteur de départ réaliste (≈ milieu de plage SF)
DEFAULT_START_COUNTER = 5_000_000_000


def encode62(n: int, width: int = 10) -> str:
    """Encode un entier en base-62, paddé à *width* caractères."""
    if n == 0:
        return CHARSET[0] * width
    chars = []
    while n > 0:
        chars.append(CHARSET[n % BASE])
        n //= BASE
    return "".join(reversed(chars)).rjust(width, CHARSET[0])


def decode62(s: str) -> int:
    """Décode une chaîne base-62 en entier."""
    n = 0
    for c in s:
        n = n * BASE + _DECODE[c]
    return n


def sf_checksum(id15: str) -> str:
    """Calcule le suffixe checksum 3-char d'un Id SF 15-char."""
    suffix = ""
    for chunk in range(3):
        flags = 0
        for pos in range(5):
            if id15[chunk * 5 + pos].isupper():
                flags += 1 << pos
        suffix += CHECKSUM_CHARS[flags]
    return suffix


def generate_sf_id(prefix: str, pod: str, counter: int) -> str:
    """Génère un Id SF 18-char réaliste."""
    id15 = prefix + pod + encode62(counter)
    return id15 + sf_checksum(id15)


# Préfixes d'Id par SObject (convention Salesforce)
SOBJECT_PREFIX = {
    "Account": "001",
    "Contact": "003",
    "Opportunity": "006",
    "Case": "500",
    "Lead": "00Q",
    "Task": "00T",
    "Event": "00U",
    "User": "005",
    "Profile": "00e",
    "Product2": "01t",
    "Pricebook2": "01s",
    "PricebookEntry": "01u",
    "Order": "801",
    "OrderItem": "802",
    "Campaign": "701",
    "CampaignMember": "00v",
    "ContentDocument": "069",
    "ContentVersion": "068",
    "Attachment": "00P",
    "Note": "002",
    "EmailMessage": "02s",
    "Group": "00G",
    "RecordType": "012",
    "CustomObject__c": "a00",
}


class DmlResult:
    """Résultat d'une opération DML."""

    def __init__(self, success: bool, record_ids: list, errors: list = None):
        self.success = success
        self.record_ids = record_ids
        self.errors = errors or []

    def __repr__(self):
        if self.success:
            return "DmlResult(success=True, ids={})".format(self.record_ids)
        return "DmlResult(success=False, errors={})".format(self.errors)
