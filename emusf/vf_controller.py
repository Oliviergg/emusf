"""Controller Visualforce : StandardController, extensions, custom controllers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .interpreter import ApexInterpreter
from .vf_parser import VfNode


class StandardController:
    """Simule ApexPages.StandardController."""

    def __init__(self, sobject_name: str, record_id: str | None, org):
        self.sobject_name = sobject_name
        self.record_id = record_id
        self.org = org

    def getRecord(self) -> dict:
        return {
            "Id": self.record_id,
            "id": self.record_id,
            "_sobject_type": self.sobject_name,
        }

    def as_dict(self) -> dict:
        """Représentation dict pour injection dans l'interpréteur."""
        rec = self.getRecord()
        rec["_type"] = "ApexPages.StandardController"
        return rec


class VfPageContext:
    """Contexte d'exécution d'une page Visualforce.

    Orchestre le standard controller, l'extension, et expose
    les données nécessaires au renderer et au résolveur d'expressions.
    """

    def __init__(self, page_node: VfNode, record_id: str | None,
                 org, classes_dir: str):
        self.page_node = page_node
        self.record_id = record_id
        self.org = org
        self.classes_dir = classes_dir

        self.record: dict | None = None          # record du standard controller
        self.instance_vars: dict = {}             # état d'instance de l'extension/controller
        self.messages: list[dict] = []            # ApexPages messages
        self.interpreter: ApexInterpreter | None = None
        self.class_name: str | None = None        # nom de la classe extension/controller

        self._init_controller()

    def _init_controller(self):
        attrs = self.page_node.attributes

        sobject_name = attrs.get("standardcontroller")
        ext_name = attrs.get("extensions")
        custom_ctrl = attrs.get("controller")

        # Créer l'interpréteur
        self.interpreter = ApexInterpreter(self.org)
        # Injecter la liste de messages pour ApexPages.addMessage
        self.interpreter.variables["__apex_messages__"] = self.messages

        # Standard controller
        if sobject_name:
            std_ctrl = StandardController(sobject_name, self.record_id, self.org)
            self.record = std_ctrl.getRecord()

            # Charger et instancier l'extension
            if ext_name:
                # Prendre la première extension (certaines pages en ont plusieurs)
                ext_name = ext_name.split(",")[0].strip()
                self._load_and_instantiate(ext_name, [std_ctrl.as_dict()])

        # Custom controller (pas de standard controller)
        elif custom_ctrl:
            self._load_and_instantiate(custom_ctrl, [])

        # Exécuter l'action de page si définie (action="{!method}")
        page_action = attrs.get("action", "")
        if page_action.startswith("{!") and page_action.endswith("}"):
            method_name = page_action[2:-1].strip()
            self.call_action(method_name)

    def _load_and_instantiate(self, class_name: str, constructor_args: list):
        """Charge un .cls et exécute le constructeur."""
        self.class_name = class_name
        cls_path = os.path.join(self.classes_dir, class_name + ".cls")
        if not os.path.exists(cls_path):
            return

        self.interpreter.load_class(cls_path)
        try:
            self.instance_vars = self.interpreter.create_instance(
                class_name, constructor_args
            )
        except Exception as e:
            # Le constructeur peut échouer (SOQL non supporté, etc.)
            # On continue avec les variables partielles
            self.instance_vars = {k: v for k, v in self.interpreter.variables.items()
                                  if "." not in k}
            self.messages.append({"severity": "WARNING",
                                  "summary": "Constructor partial: {}".format(e)})
        # Récupérer les messages générés pendant le constructeur
        self._collect_messages()

    def call_action(self, method_name: str) -> dict | None:
        """Appelle une méthode d'action sur le controller.

        Retourne un dict PageReference si redirect, sinon None.
        """
        if not self.class_name or not self.interpreter:
            return None
        class_def = self.interpreter.classes.get(self.class_name)
        if not class_def or method_name not in class_def.methods:
            return None

        result = self.interpreter.call_instance_method(
            self.class_name, method_name, self.instance_vars
        )
        self._collect_messages()

        if isinstance(result, dict) and result.get("_type") == "PageReference":
            return result
        return None

    def _collect_messages(self):
        """Récupère les messages ApexPages depuis l'interpréteur."""
        msgs = self.interpreter.variables.get("__apex_messages__", [])
        # Les messages sont déjà dans self.messages (même liste par référence)
        # mais on synchronise au cas où
        if msgs is not self.messages:
            self.messages.extend(msgs)
            msgs.clear()
