"""ApexContext - simule le contexte d'exécution Apex."""

from .org import FakeOrg


class ApexContext:
    """
    Simule le contexte d'exécution Apex.
    Stocke les variables locales et donne accès à l'org.
    """

    def __init__(self, org: FakeOrg):
        self.org = org
        self.variables: dict = {}

    def set(self, name: str, value):
        self.variables[name] = value

    def soql(self, query: str) -> list[dict]:
        return self.org.execute_soql(query, context=self.variables)
