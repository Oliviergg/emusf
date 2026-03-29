"""AST nodes pour les Salesforce Flows (.flow-meta.xml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# --- Connecteurs ---

@dataclass
class FlowConnector:
    """Lien vers l'élément suivant."""
    target_reference: str


# --- Variables & Ressources ---

@dataclass
class FlowVariable:
    """Variable déclarée dans le flow."""
    name: str
    data_type: str  # "String", "Number", "Date", "DateTime", "Boolean", "SObject", "Currency"
    value: Optional[str] = None  # valeur par défaut (littérale)
    is_input: bool = False
    is_output: bool = False
    object_type: Optional[str] = None  # pour data_type == "SObject"


@dataclass
class FlowFormula:
    """Formule calculée (ressource)."""
    name: str
    data_type: str
    expression: str  # ex: "NOW()", "TODAY()", "{!var1} + 1"


@dataclass
class FlowConstant:
    """Constante déclarée dans le flow."""
    name: str
    data_type: str
    value: str


@dataclass
class FlowTextTemplate:
    """Template texte (merge fields)."""
    name: str
    text: str


# --- Éléments d'exécution ---

@dataclass
class FlowAssignmentItem:
    """Un seul item d'assignation (champ = valeur)."""
    assign_to_reference: str  # ex: "$Record.Date__c" ou "myVar"
    operator: str  # "Assign", "Add", "Subtract"
    value: Optional[str] = None  # littéral
    element_reference: Optional[str] = None  # référence à une variable/formule


@dataclass
class FlowAssignment:
    """Élément Assignment — affecte des valeurs."""
    name: str
    label: str
    items: list  # list[FlowAssignmentItem]
    connector: Optional[FlowConnector] = None


@dataclass
class FlowCondition:
    """Une condition dans une règle de décision."""
    left_reference: str  # ex: "$Record.Status__c"
    operator: str  # "EqualTo", "NotEqualTo", "IsNull", "GreaterThan", etc.
    right_value: Optional[str] = None  # littéral
    right_reference: Optional[str] = None  # référence


@dataclass
class FlowDecisionRule:
    """Une branche (outcome) d'une décision."""
    name: str
    label: str
    condition_logic: str  # "and", "or", "1 AND 2"
    conditions: list  # list[FlowCondition]
    connector: Optional[FlowConnector] = None


@dataclass
class FlowDecision:
    """Élément Decision — branchement conditionnel."""
    name: str
    label: str
    rules: list  # list[FlowDecisionRule]
    default_connector: Optional[FlowConnector] = None


@dataclass
class FlowRecordUpdate:
    """Élément Record Update — met à jour des records via DML."""
    name: str
    label: str
    object: Optional[str] = None  # SObject type (si lookup)
    input_reference: Optional[str] = None  # référence à une variable SObject ou collection
    filters: list = field(default_factory=list)  # critères de filtre
    input_assignments: list = field(default_factory=list)  # list[FlowAssignmentItem]
    connector: Optional[FlowConnector] = None


@dataclass
class FlowRecordLookup:
    """Élément Record Lookup — requête SOQL."""
    name: str
    label: str
    object: str  # SObject type
    filters: list  # list[FlowCondition]
    output_reference: Optional[str] = None  # variable à remplir
    output_assignments: list = field(default_factory=list)  # list[FlowAssignmentItem]
    sort_field: Optional[str] = None
    sort_order: Optional[str] = None  # "Asc", "Desc"
    limit: Optional[int] = None
    get_first_record_only: bool = True
    connector: Optional[FlowConnector] = None


@dataclass
class FlowRecordCreate:
    """Élément Record Create — insert DML."""
    name: str
    label: str
    object: str
    input_assignments: list = field(default_factory=list)  # list[FlowAssignmentItem]
    input_reference: Optional[str] = None
    store_output_automatically: bool = False
    output_reference: Optional[str] = None  # variable pour stocker l'Id
    connector: Optional[FlowConnector] = None


@dataclass
class FlowRecordDelete:
    """Élément Record Delete — delete DML."""
    name: str
    label: str
    object: Optional[str] = None
    input_reference: Optional[str] = None
    filters: list = field(default_factory=list)
    connector: Optional[FlowConnector] = None


@dataclass
class FlowLoop:
    """Élément Loop — itère sur une collection."""
    name: str
    label: str
    collection_reference: str
    iteration_order: str = "Asc"  # "Asc" ou "Desc"
    next_value_connector: Optional[FlowConnector] = None  # corps de la boucle
    no_more_values_connector: Optional[FlowConnector] = None  # sortie
    iterator_variable: Optional[str] = None  # nom de la variable d'itération


@dataclass
class FlowStart:
    """Élément Start — point d'entrée du flow."""
    connector: Optional[FlowConnector] = None
    object: Optional[str] = None  # SObject type (record-triggered)
    record_trigger_type: Optional[str] = None  # "Create", "Update", "CreateAndUpdate", "Delete"
    trigger_type: Optional[str] = None  # "RecordBeforeSave", "RecordAfterSave"
    filters: list = field(default_factory=list)  # conditions d'entrée (FlowCondition)
    filter_logic: Optional[str] = None  # "and", "or", custom


# --- Définition complète du flow ---

@dataclass
class FlowDefinition:
    """Représente un flow complet parsé depuis .flow-meta.xml."""
    label: str
    api_name: str  # nom du fichier sans extension
    process_type: str  # "AutoLaunchedFlow", "Flow" (screen), "Workflow"
    start: FlowStart = field(default_factory=FlowStart)
    variables: dict = field(default_factory=dict)  # {name: FlowVariable}
    formulas: dict = field(default_factory=dict)  # {name: FlowFormula}
    constants: dict = field(default_factory=dict)  # {name: FlowConstant}
    text_templates: dict = field(default_factory=dict)  # {name: FlowTextTemplate}
    assignments: dict = field(default_factory=dict)  # {name: FlowAssignment}
    decisions: dict = field(default_factory=dict)  # {name: FlowDecision}
    record_updates: dict = field(default_factory=dict)  # {name: FlowRecordUpdate}
    record_lookups: dict = field(default_factory=dict)  # {name: FlowRecordLookup}
    record_creates: dict = field(default_factory=dict)  # {name: FlowRecordCreate}
    record_deletes: dict = field(default_factory=dict)  # {name: FlowRecordDelete}
    loops: dict = field(default_factory=dict)  # {name: FlowLoop}

    def get_element(self, name: str):
        """Retrouve un élément par son nom (API name) dans tous les types."""
        for store in (self.assignments, self.decisions, self.record_updates,
                      self.record_lookups, self.record_creates, self.record_deletes,
                      self.loops):
            if name in store:
                return store[name]
        return None
