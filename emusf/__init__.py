"""emusf - Émulateur Salesforce (Apex/SOQL/VF/Flow)"""

from .parser import parse_soql, SOQLQuery
from .schema import SchemaRegistry, RelationshipMeta
from .org import FakeOrg
from .context import ApexContext
from .apex_parser import ApexParser
from .interpreter import ApexInterpreter
from .trigger_parser import TriggerParser, load_trigger
from .flow_parser import parse_flow, load_flow
from .flow_interpreter import FlowInterpreter, register_flow, load_and_register_flow

__all__ = [
    "parse_soql",
    "SOQLQuery",
    "SchemaRegistry",
    "RelationshipMeta",
    "FakeOrg",
    "ApexContext",
    "parse_flow",
    "load_flow",
    "FlowInterpreter",
    "register_flow",
    "load_and_register_flow",
]
