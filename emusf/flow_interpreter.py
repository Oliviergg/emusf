"""Interpréteur de Salesforce Flows — machine à états sur FlowDefinition."""

from __future__ import annotations

from datetime import date, datetime

from .flow_nodes import (
    FlowDefinition, FlowStart, FlowConnector,
    FlowAssignment, FlowAssignmentItem,
    FlowDecision, FlowDecisionRule, FlowCondition,
    FlowRecordUpdate, FlowRecordLookup, FlowRecordCreate, FlowRecordDelete,
    FlowLoop, FlowFormula, FlowVariable,
)
from .formula_engine import FormulaEngine, resolve_merge_fields


class FlowInterpreter:
    """
    Exécute un FlowDefinition en traversant les éléments via connecteurs.
    Gère les variables, formules, assignations, décisions, DML.
    """

    def __init__(self, org, flow: FlowDefinition):
        self.org = org
        self.flow = flow
        self.variables: dict = {}  # scope des variables du flow
        self.debug_log: list = []  # trace d'exécution
        self._loop_iterators: dict = {}  # état des boucles en cours

    # ------------------------------------------------------------------
    # Point d'entrée principal
    # ------------------------------------------------------------------

    def run(self, record: dict = None, old_record: dict = None,
            input_variables: dict = None):
        """
        Exécute le flow.
        - record: le $Record courant (record-triggered flows)
        - old_record: le $Record__Prior (before update)
        - input_variables: variables d'entrée (autolaunched invocable)
        """
        # Initialiser les variables déclarées
        self._init_variables(input_variables)

        # $Record et $Record__Prior
        if record is not None:
            self.variables["$Record"] = record
        if old_record is not None:
            self.variables["$Record__Prior"] = old_record

        # Évaluer les formules
        self._eval_formulas()

        # Vérifier les conditions d'entrée (start filters)
        if self.flow.start.filters:
            if not self._check_entry_conditions(record):
                self._log("Flow ignoré : conditions d'entrée non remplies")
                return

        # Suivre le graphe depuis le start
        connector = self.flow.start.connector
        self._follow(connector)

    def _follow(self, connector: FlowConnector | None):
        """Suit la chaîne de connecteurs jusqu'à la fin."""
        while connector:
            target = connector.target_reference
            element = self.flow.get_element(target)
            if element is None:
                raise FlowException("Élément '{}' introuvable dans le flow".format(target))
            self._log("→ {}".format(target))
            connector = self._exec_element(element)

    # ------------------------------------------------------------------
    # Dispatch d'exécution
    # ------------------------------------------------------------------

    def _exec_element(self, element):
        """Exécute un élément et retourne le connecteur suivant."""
        if isinstance(element, FlowAssignment):
            return self._exec_assignment(element)
        elif isinstance(element, FlowDecision):
            return self._exec_decision(element)
        elif isinstance(element, FlowRecordUpdate):
            return self._exec_record_update(element)
        elif isinstance(element, FlowRecordLookup):
            return self._exec_record_lookup(element)
        elif isinstance(element, FlowRecordCreate):
            return self._exec_record_create(element)
        elif isinstance(element, FlowRecordDelete):
            return self._exec_record_delete(element)
        elif isinstance(element, FlowLoop):
            return self._exec_loop(element)
        else:
            raise FlowException("Type d'élément non supporté: {}".format(type(element).__name__))

    # ------------------------------------------------------------------
    # Assignations
    # ------------------------------------------------------------------

    def _exec_assignment(self, assignment: FlowAssignment) -> FlowConnector | None:
        """Exécute un bloc d'assignations."""
        for item in assignment.items:
            value = self._resolve_value(item)
            self._assign(item.assign_to_reference, item.operator, value)
        return assignment.connector

    def _assign(self, reference: str, operator: str, value):
        """Affecte une valeur à une référence (variable ou champ $Record)."""
        parts = reference.split(".")
        op = operator.lower() if operator else "assign"

        if len(parts) >= 2 and parts[0].startswith("$"):
            # $Record.Field__c
            obj = self._resolve_reference(parts[0])
            if obj is None:
                raise FlowException("Référence '{}' non résolue".format(parts[0]))
            field = parts[1]
            if op == "assign":
                obj[field] = value
            elif op == "add":
                obj[field] = (obj.get(field) or 0) + (value or 0)
            elif op == "subtract":
                obj[field] = (obj.get(field) or 0) - (value or 0)
            else:
                obj[field] = value
        else:
            # Variable simple
            var_name = reference
            if op == "assign":
                self.variables[var_name] = value
            elif op == "add":
                current = self.variables.get(var_name, 0) or 0
                if isinstance(current, list):
                    # Add to collection
                    current.append(value)
                else:
                    self.variables[var_name] = current + (value or 0)
            elif op == "additem":
                current = self.variables.get(var_name)
                if current is None:
                    current = []
                    self.variables[var_name] = current
                current.append(value)
            elif op == "subtract":
                current = self.variables.get(var_name, 0) or 0
                self.variables[var_name] = current - (value or 0)
            elif op == "removeall":
                self.variables[var_name] = []
            else:
                self.variables[var_name] = value

    # ------------------------------------------------------------------
    # Décisions
    # ------------------------------------------------------------------

    def _exec_decision(self, decision: FlowDecision) -> FlowConnector | None:
        """Évalue les règles de décision dans l'ordre, retourne le premier match."""
        for rule in decision.rules:
            if self._eval_rule(rule):
                self._log("  décision: {} → {}".format(decision.name, rule.name))
                return rule.connector
        self._log("  décision: {} → default".format(decision.name))
        return decision.default_connector

    def _eval_rule(self, rule: FlowDecisionRule) -> bool:
        """Évalue une règle de décision (AND/OR de conditions)."""
        if not rule.conditions:
            return True
        results = [self._eval_condition(c) for c in rule.conditions]
        logic = rule.condition_logic.lower()
        if logic == "or":
            return any(results)
        return all(results)  # "and" par défaut

    def _eval_condition(self, condition: FlowCondition) -> bool:
        """Évalue une condition unitaire."""
        left = self._resolve_reference(condition.left_reference)
        if condition.right_reference:
            right = self._resolve_reference(condition.right_reference)
        else:
            right = self._coerce(condition.right_value, left)

        op = condition.operator.lower() if condition.operator else "equalto"

        if op == "equalto":
            return left == right
        elif op == "notequalto":
            return left != right
        elif op == "isnull":
            return (left is None) == (str(right).lower() == "true" if right is not None else True)
        elif op == "greaterthan":
            return (left or 0) > (right or 0)
        elif op == "lessthan":
            return (left or 0) < (right or 0)
        elif op == "greaterthanorequalto":
            return (left or 0) >= (right or 0)
        elif op == "lessthanorequalto":
            return (left or 0) <= (right or 0)
        elif op == "contains":
            return right in (left or "")
        elif op == "startswith":
            return str(left or "").startswith(str(right or ""))
        elif op == "endswith":
            return str(left or "").endswith(str(right or ""))
        elif op == "ischanged":
            old = self.variables.get("$Record__Prior", {})
            field = condition.left_reference.split(".")[-1] if "." in condition.left_reference else condition.left_reference
            return old.get(field) != left
        else:
            raise FlowException("Opérateur inconnu: {}".format(condition.operator))

    # ------------------------------------------------------------------
    # DML — Record Update / Lookup / Create / Delete
    # ------------------------------------------------------------------

    def _exec_record_update(self, element: FlowRecordUpdate) -> FlowConnector | None:
        """Met à jour des records."""
        if element.input_reference:
            # Mise à jour directe d'une variable SObject
            record = self._resolve_reference(element.input_reference)
            if record is None:
                return element.connector
            records = record if isinstance(record, list) else [record]
            # Appliquer les input_assignments
            for rec in records:
                for item in element.input_assignments:
                    rec[item.assign_to_reference] = self._resolve_value(item)
            sobject = records[0].get("_sobject_type", element.object)
            if sobject:
                self.org.update(sobject, records)
        elif element.object and element.filters:
            # Mise à jour par critères
            where = self._build_where(element.filters)
            rows = self.org.execute_soql(
                "SELECT Id FROM {} WHERE {}".format(element.object, where)
            )
            for row in rows:
                updates = {"Id": row["Id"]}
                for item in element.input_assignments:
                    updates[item.assign_to_reference] = self._resolve_value(item)
                self.org.update(element.object, [updates])
        return element.connector

    def _exec_record_lookup(self, element: FlowRecordLookup) -> FlowConnector | None:
        """Recherche un ou plusieurs records."""
        where = self._build_where(element.filters) if element.filters else "1=1"
        fields = "*"
        soql = "SELECT {} FROM {} WHERE {}".format(fields, element.object, where)
        if element.sort_field:
            soql += " ORDER BY {} {}".format(
                element.sort_field, element.sort_order or "ASC"
            )
        if element.limit:
            soql += " LIMIT {}".format(element.limit)
        elif element.get_first_record_only:
            soql += " LIMIT 1"

        rows = self.org.execute_soql(soql)

        if element.output_reference:
            if element.get_first_record_only:
                self.variables[element.output_reference] = rows[0] if rows else None
            else:
                self.variables[element.output_reference] = rows
        elif element.output_assignments and rows:
            row = rows[0]
            for item in element.output_assignments:
                field = item.element_reference or item.assign_to_reference
                self._assign(item.assign_to_reference, "Assign", row.get(field))

        return element.connector

    def _exec_record_create(self, element: FlowRecordCreate) -> FlowConnector | None:
        """Crée un record."""
        if element.input_reference:
            record = self._resolve_reference(element.input_reference)
            records = record if isinstance(record, list) else [record]
        else:
            record = {}
            for item in element.input_assignments:
                record[item.assign_to_reference] = self._resolve_value(item)
            records = [record]

        result = self.org.insert(element.object, records)
        if element.output_reference and result.record_ids:
            self.variables[element.output_reference] = result.record_ids[0]

        return element.connector

    def _exec_record_delete(self, element: FlowRecordDelete) -> FlowConnector | None:
        """Supprime des records."""
        if element.input_reference:
            record = self._resolve_reference(element.input_reference)
            records = record if isinstance(record, list) else [record]
            ids = [r["Id"] for r in records if "Id" in r]
            sobject = element.object or records[0].get("_sobject_type")
        elif element.object and element.filters:
            where = self._build_where(element.filters)
            rows = self.org.execute_soql(
                "SELECT Id FROM {} WHERE {}".format(element.object, where)
            )
            ids = [r["Id"] for r in rows]
            sobject = element.object
        else:
            return element.connector

        if ids and sobject:
            self.org.delete(sobject, ids)
        return element.connector

    # ------------------------------------------------------------------
    # Boucles
    # ------------------------------------------------------------------

    def _exec_loop(self, loop: FlowLoop) -> FlowConnector | None:
        """Exécute un Loop — itère sur une collection."""
        collection = self._resolve_reference(loop.collection_reference)
        if not collection or not isinstance(collection, list):
            return loop.no_more_values_connector

        items = list(collection)
        if loop.iteration_order and loop.iteration_order.lower() == "desc":
            items = list(reversed(items))

        # Nom de la variable d'itération = nom du loop par convention SF
        iter_var = loop.iterator_variable or loop.name

        for item in items:
            self.variables[iter_var] = item
            # Exécuter le corps de la boucle
            if loop.next_value_connector:
                self._follow(loop.next_value_connector)

        return loop.no_more_values_connector

    # ------------------------------------------------------------------
    # Résolution de valeurs
    # ------------------------------------------------------------------

    def _resolve_value(self, item: FlowAssignmentItem):
        """Résout la valeur d'un FlowAssignmentItem."""
        if item.element_reference:
            return self._resolve_reference(item.element_reference)
        # Tenter de convertir les valeurs numériques
        if item.value is not None:
            try:
                return float(item.value) if "." in item.value else int(item.value)
            except (ValueError, TypeError):
                pass
        return item.value

    def _resolve_reference(self, reference: str):
        """
        Résout une référence Flow:
        - "$Record.Field__c" → self.variables["$Record"]["Field__c"]
        - "$Record__Prior.Field__c" → idem
        - "$Flow.CurrentDateTime" → now
        - "$Flow.CurrentDate" → today
        - "myVariable" → self.variables["myVariable"]
        - "myVariable.Field__c" → self.variables["myVariable"]["Field__c"]
        - "formulaName" → évalue la formule
        """
        if reference is None:
            return None

        parts = reference.split(".")

        # Variables spéciales $Flow
        if parts[0] == "$Flow":
            return self._resolve_flow_global(parts[1] if len(parts) > 1 else None)

        # $Record, $Record__Prior, ou variable utilisateur
        root_name = parts[0]
        obj = self.variables.get(root_name)

        # Vérifier dans les formules
        if obj is None and root_name in self.flow.formulas:
            obj = self._eval_formula(self.flow.formulas[root_name])

        # Vérifier dans les constantes
        if obj is None and root_name in self.flow.constants:
            obj = self.flow.constants[root_name].value

        if len(parts) == 1:
            return obj

        # Navigation par champ : $Record.Name, myVar.Field__c
        if isinstance(obj, dict):
            return obj.get(parts[1])

        return obj

    def _resolve_flow_global(self, field: str):
        """Résout les variables système $Flow.*."""
        if field == "CurrentDateTime":
            return datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        elif field == "CurrentDate":
            return date.today().strftime("%Y-%m-%d")
        elif field == "CurrentStage":
            return None
        elif field == "InterviewGuid":
            return "flow-interview-001"
        elif field == "FaultMessage":
            return self.variables.get("$Flow.FaultMessage")
        elif field == "ActiveStages":
            return []
        return None

    def _eval_formula(self, formula: FlowFormula):
        """Évalue une formule Flow via le moteur de formules unifié."""
        expr = formula.expression.strip()

        # Résoudre les merge fields {!ref} avant d'évaluer
        resolved = resolve_merge_fields(expr, self._resolve_reference)

        engine = FormulaEngine(self._resolve_reference)
        try:
            return engine.evaluate(resolved)
        except Exception:
            # Fallback : retourner la chaîne résolue
            return resolved

    def _eval_formulas(self):
        """Évalue toutes les formules et les stocke dans les variables."""
        for name, formula in self.flow.formulas.items():
            self.variables[name] = self._eval_formula(formula)

    # ------------------------------------------------------------------
    # Conditions d'entrée
    # ------------------------------------------------------------------

    def _check_entry_conditions(self, record: dict) -> bool:
        """Vérifie les conditions d'entrée du flow (start filters)."""
        if not self.flow.start.filters:
            return True
        results = [self._eval_condition(c) for c in self.flow.start.filters]
        logic = (self.flow.start.filter_logic or "and").lower()
        if logic == "or":
            return any(results)
        return all(results)

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    def _init_variables(self, input_variables: dict = None):
        """Initialise les variables déclarées dans le flow."""
        for name, var in self.flow.variables.items():
            if var.data_type == "SObject":
                self.variables[name] = {}
            elif var.data_type in ("Number", "Currency"):
                self.variables[name] = float(var.value) if var.value else 0
            elif var.data_type == "Boolean":
                self.variables[name] = var.value and var.value.lower() == "true"
            elif var.data_type in ("Date", "DateTime"):
                self.variables[name] = var.value
            else:
                self.variables[name] = var.value

        # Écraser avec les input_variables fournies
        if input_variables:
            self.variables.update(input_variables)

    def _build_where(self, filters: list) -> str:
        """Construit une clause WHERE SQL depuis des FlowCondition."""
        clauses = []
        for f in filters:
            left = f.left_reference
            op = f.operator.lower() if f.operator else "equalto"
            if f.right_reference:
                right_val = self._resolve_reference(f.right_reference)
            else:
                right_val = f.right_value

            if op == "equalto":
                clauses.append("{} = '{}'".format(left, right_val))
            elif op == "notequalto":
                clauses.append("{} != '{}'".format(left, right_val))
            elif op == "greaterthan":
                clauses.append("{} > '{}'".format(left, right_val))
            elif op == "lessthan":
                clauses.append("{} < '{}'".format(left, right_val))
            elif op == "isnull":
                if str(right_val).lower() == "true":
                    clauses.append("{} IS NULL".format(left))
                else:
                    clauses.append("{} IS NOT NULL".format(left))
            else:
                clauses.append("{} = '{}'".format(left, right_val))

        return " AND ".join(clauses) if clauses else "1=1"

    def _coerce(self, value, reference_value):
        """Tente de convertir value dans le type de reference_value."""
        if value is None:
            return None
        if isinstance(reference_value, (int, float)):
            try:
                return float(value) if "." in str(value) else int(value)
            except (ValueError, TypeError):
                return value
        if isinstance(reference_value, bool):
            return str(value).lower() == "true"
        return value

    def _log(self, message: str):
        """Ajoute une entrée au debug log."""
        self.debug_log.append(message)


class FlowException(Exception):
    """Erreur d'exécution d'un flow."""
    pass


# ------------------------------------------------------------------
# Chargement et enregistrement sur l'org
# ------------------------------------------------------------------

def load_and_register_flow(org, path: str):
    """
    Charge un flow depuis un .flow-meta.xml et l'enregistre sur l'org
    comme trigger (pour les record-triggered flows).
    """
    from .flow_parser import load_flow

    flow = load_flow(path)
    register_flow(org, flow)
    return flow


def register_flow(org, flow: FlowDefinition):
    """
    Enregistre un FlowDefinition sur l'org.
    Les record-triggered flows sont enregistrés comme triggers.
    """
    start = flow.start
    if not start.object or not start.trigger_type:
        return  # Pas un record-triggered flow

    # Mapper le trigger_type SF vers les événements org
    trigger_type = start.trigger_type
    record_trigger_type = (start.record_trigger_type or "").lower()

    events = _map_flow_events(trigger_type, record_trigger_type)

    def make_callback(flow_def, is_before):
        def callback(records, old_records=None):
            old_list = old_records or []
            for i, record in enumerate(records):
                old_rec = old_list[i] if i < len(old_list) else None
                interp = FlowInterpreter(org, flow_def)
                interp.run(record=record, old_record=old_rec)
        return callback

    is_before = "Before" in trigger_type
    cb = make_callback(flow, is_before)

    for event in events:
        org.add_trigger(event, start.object, cb)

    print("FLOW: {} chargé sur {} ({})".format(
        flow.api_name, start.object, ", ".join(events)
    ))


def _map_flow_events(trigger_type: str, record_trigger_type: str) -> list:
    """Mappe les types SF vers les événements org."""
    events = []
    is_before = "Before" in trigger_type

    prefix = "before" if is_before else "after"

    if record_trigger_type in ("create", "createandupdate"):
        events.append("{}_insert".format(prefix))
    if record_trigger_type in ("update", "createandupdate"):
        events.append("{}_update".format(prefix))
    if record_trigger_type == "delete":
        events.append("{}_delete".format(prefix))

    # Si aucun match, inférer depuis trigger_type
    if not events:
        if "Save" in trigger_type:
            events.append("{}_insert".format(prefix))
            events.append("{}_update".format(prefix))

    return events
