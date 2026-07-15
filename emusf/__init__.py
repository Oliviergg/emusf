"""emusf - Émulateur Salesforce (Apex/SOQL/VF/Flow)"""

from .soql_compiler import compile_soql, CompiledQuery
from .schema import SchemaRegistry, RelationshipMeta
from .dml import DmlResult, DmlException, SOBJECT_PREFIX, generate_sf_id, decode62, encode62, sf_checksum
from .pg_test_org import PgTestOrg
from .pg_data_org import PgDataOrg
from .context import ApexContext
from .apex_parser import ApexParser
from .interpreter import ApexInterpreter
from .trigger_parser import TriggerParser, load_trigger
from .flow_parser import parse_flow, load_flow
from .flow_interpreter import FlowInterpreter, register_flow, load_and_register_flow

__all__ = [
    "compile_soql",
    "CompiledQuery",
    "SchemaRegistry",
    "RelationshipMeta",
    "DmlResult",
    "DmlException",
    "PgTestOrg",
    "PgDataOrg",
    "ApexContext",
    "parse_flow",
    "load_flow",
    "FlowInterpreter",
    "register_flow",
    "load_and_register_flow",
]
