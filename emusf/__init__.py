"""emusf - Émulateur Salesforce (Apex/SOQL)"""

from .parser import parse_soql, SOQLQuery
from .schema import SchemaRegistry, RelationshipMeta
from .org import FakeOrg
from .context import ApexContext
from .apex_parser import ApexParser
from .interpreter import ApexInterpreter
from .trigger_parser import TriggerParser, load_trigger

__all__ = [
    "parse_soql",
    "SOQLQuery",
    "SchemaRegistry",
    "RelationshipMeta",
    "FakeOrg",
    "ApexContext",
]
