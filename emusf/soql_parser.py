"""Parser SOQL — transforme les tokens en AST (descente récursive)."""

from __future__ import annotations

from .soql_lexer import TT, SoqlToken, tokenize
from .soql_ast import (
    SoqlSelect, SoqlField, SoqlAggregate, SoqlSubSelect, SoqlOrderItem,
    SoqlExpr, SoqlAnd, SoqlOr, SoqlNot,
    SoqlComparison, SoqlIn, SoqlNullCheck,
    SoqlValue, SoqlLiteral, SoqlBindVar, SoqlDateLiteral,
)


class SoqlParseError(Exception):
    pass


class SoqlParser:
    """Parser SOQL par descente récursive."""

    def __init__(self, tokens: list[SoqlToken]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> SoqlToken:
        return self.tokens[self.pos]

    def advance(self) -> SoqlToken:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, tt: TT) -> SoqlToken:
        tok = self.advance()
        if tok.type != tt:
            raise SoqlParseError(
                "Attendu {}, trouvé {} ('{}') à pos {}".format(tt.name, tok.type.name, tok.value, tok.pos))
        return tok

    def match(self, *types: TT) -> SoqlToken | None:
        if self.peek().type in types:
            return self.advance()
        return None

    def check(self, *types: TT) -> bool:
        return self.peek().type in types

    # === Requête principale ===

    def parse_query(self) -> SoqlSelect:
        self.expect(TT.SELECT)
        fields, subqueries = self._parse_field_list()
        self.expect(TT.FROM)
        from_object = self._parse_dotted_ident()

        where = None
        if self.match(TT.WHERE):
            where = self._parse_expr()

        group_by = None
        if self.match(TT.GROUP):
            self.expect(TT.BY)
            group_by = self._parse_ident_list()

        having = None
        if self.match(TT.HAVING):
            having = self._parse_expr()

        order_by = None
        if self.match(TT.ORDER):
            self.expect(TT.BY)
            order_by = self._parse_order_list()

        limit = None
        if self.match(TT.LIMIT):
            tok = self.expect(TT.INTEGER)
            limit = int(tok.value)

        return SoqlSelect(
            fields=fields,
            from_object=from_object,
            where=where,
            subqueries=subqueries,
            group_by=group_by,
            having=having,
            order_by=order_by,
            limit=limit,
        )

    # === Champs SELECT ===

    def _parse_field_list(self) -> tuple[list, list]:
        """Retourne (fields, subqueries)."""
        fields = []
        subqueries = []

        f, sub = self._parse_field_or_sub()
        if sub:
            subqueries.append(sub)
        else:
            fields.append(f)

        while self.match(TT.COMMA):
            f, sub = self._parse_field_or_sub()
            if sub:
                subqueries.append(sub)
            else:
                fields.append(f)

        return fields, subqueries

    def _parse_field_or_sub(self) -> tuple:
        """Retourne (SoqlField|SoqlAggregate, None) ou (None, SoqlSubSelect)."""
        # Sous-requête : (SELECT ... FROM ...)
        if self.check(TT.LPAREN):
            self.advance()
            sub_query = self.parse_query()
            self.expect(TT.RPAREN)
            return None, SoqlSubSelect(query=sub_query, relationship=sub_query.from_object)

        # Agrégat : COUNT(), COUNT(Id), SUM(Amount), etc.
        if self.check(TT.COUNT, TT.SUM, TT.MIN, TT.MAX, TT.AVG):
            return self._parse_aggregate(), None

        # * (select all)
        if self.check(TT.STAR):
            self.advance()
            return SoqlField(name="*"), None

        # Champ normal avec éventuel alias : Field ou Relation.Field
        name = self._parse_dotted_ident()
        alias = None
        # Vérifier si un alias suit (identifiant sans virgule/mot-clé avant)
        if self.check(TT.IDENT) and not self._is_clause_keyword():
            alias = self.advance().value
        return SoqlField(name=name, alias=alias), None

    def _parse_aggregate(self) -> SoqlAggregate:
        func_tok = self.advance()  # COUNT, SUM, etc.
        func_name = func_tok.value.upper()
        self.expect(TT.LPAREN)
        field = None
        if not self.check(TT.RPAREN):
            field = self._parse_dotted_ident()
        self.expect(TT.RPAREN)
        alias = None
        if self.check(TT.IDENT) and not self._is_clause_keyword():
            alias = self.advance().value
        return SoqlAggregate(function=func_name, field=field, alias=alias)

    def _parse_dotted_ident(self) -> str:
        """Parse un identifiant potentiellement doté : Account.Name."""
        parts = [self._parse_ident()]
        while self.match(TT.DOT):
            parts.append(self._parse_ident())
        return ".".join(parts)

    def _parse_ident(self) -> str:
        """Parse un identifiant simple. Accepte aussi certains mots-clés utilisés comme noms de champ."""
        tok = self.peek()
        # Certains mots-clés SOQL sont aussi des noms de champs valides
        ident_like = {
            TT.IDENT, TT.COUNT, TT.SUM, TT.MIN, TT.MAX, TT.AVG,
            TT.FIRST, TT.LAST, TT.ASC, TT.DESC, TT.TODAY, TT.YESTERDAY,
            TT.ORDER, TT.GROUP, TT.LIMIT, TT.HAVING, TT.BY,
            TT.IN, TT.LIKE, TT.NOT, TT.NULL, TT.TRUE, TT.FALSE,
        }
        if tok.type in ident_like:
            self.advance()
            return tok.value
        raise SoqlParseError(
            "Identifiant attendu, trouvé {} ('{}') à pos {}".format(tok.type.name, tok.value, tok.pos))

    def _parse_ident_list(self) -> list[str]:
        result = [self._parse_dotted_ident()]
        while self.match(TT.COMMA):
            result.append(self._parse_dotted_ident())
        return result

    def _is_clause_keyword(self) -> bool:
        """Vérifie si le token courant est un mot-clé de clause (FROM, WHERE, etc.)."""
        return self.peek().type in {
            TT.FROM, TT.WHERE, TT.GROUP, TT.HAVING,
            TT.ORDER, TT.LIMIT, TT.EOF, TT.RPAREN, TT.COMMA,
        }

    # === ORDER BY ===

    def _parse_order_list(self) -> list[SoqlOrderItem]:
        items = [self._parse_order_item()]
        while self.match(TT.COMMA):
            items.append(self._parse_order_item())
        return items

    def _parse_order_item(self) -> SoqlOrderItem:
        field = self._parse_dotted_ident()
        direction = "ASC"
        if self.match(TT.ASC):
            direction = "ASC"
        elif self.match(TT.DESC):
            direction = "DESC"
        nulls = None
        if self.match(TT.NULLS):
            if self.match(TT.FIRST):
                nulls = "FIRST"
            elif self.match(TT.LAST):
                nulls = "LAST"
        return SoqlOrderItem(field=field, direction=direction, nulls=nulls)

    # === Expressions WHERE ===

    def _parse_expr(self) -> SoqlExpr:
        """expr = and_expr (OR and_expr)*"""
        left = self._parse_and_expr()
        while self.match(TT.OR):
            right = self._parse_and_expr()
            left = SoqlOr(left=left, right=right)
        return left

    def _parse_and_expr(self) -> SoqlExpr:
        """and_expr = unary (AND unary)*"""
        left = self._parse_unary()
        while self.match(TT.AND):
            right = self._parse_unary()
            left = SoqlAnd(left=left, right=right)
        return left

    def _parse_unary(self) -> SoqlExpr:
        """unary = NOT unary | atom"""
        if self.match(TT.NOT):
            return SoqlNot(operand=self._parse_unary())
        return self._parse_atom()

    def _parse_atom(self) -> SoqlExpr:
        """atom = '(' expr ')' | comparison"""
        if self.match(TT.LPAREN):
            expr = self._parse_expr()
            self.expect(TT.RPAREN)
            return expr
        return self._parse_comparison()

    def _parse_comparison(self) -> SoqlExpr:
        """Parse une comparaison : field op value | field IN (...) | field = NULL | AGG(field) op value."""
        # Agrégat dans HAVING : COUNT(Id) > 1
        if self.check(TT.COUNT, TT.SUM, TT.MIN, TT.MAX, TT.AVG):
            agg = self._parse_aggregate()
            field = "{}({})".format(agg.function, agg.field or "*")
        else:
            field = self._parse_dotted_ident()

        # field NOT IN (...)
        if self.check(TT.NOT):
            self.advance()
            self.expect(TT.IN)
            return self._parse_in(field, negated=True)

        # field IN (...)
        if self.match(TT.IN):
            return self._parse_in(field, negated=False)

        # Opérateur de comparaison
        op_map = {TT.EQ: "=", TT.NEQ: "!=", TT.LT: "<", TT.GT: ">", TT.LTE: "<=", TT.GTE: ">=", TT.LIKE: "LIKE"}
        tok = self.peek()
        if tok.type in op_map:
            op = op_map[tok.type]
            self.advance()

            # NULL check : field = NULL, field != NULL
            if self.check(TT.NULL):
                self.advance()
                return SoqlNullCheck(field=field, is_null=(op == "="))

            value = self._parse_value()
            return SoqlComparison(field=field, op=op, value=value)

        raise SoqlParseError(
            "Opérateur attendu après '{}', trouvé {} ('{}') à pos {}".format(
                field, tok.type.name, tok.value, tok.pos))

    def _parse_in(self, field: str, negated: bool) -> SoqlIn:
        """Parse IN (:bindVar) ou IN ('a', 'b') ou IN (SELECT ...)."""
        # IN :bindVar (sans parenthèses — Apex le permet)
        if self.check(TT.BIND):
            tok = self.advance()
            return SoqlIn(field=field, negated=negated, values=[SoqlBindVar(path=tok.value)])

        self.expect(TT.LPAREN)

        # IN (SELECT ...) — sous-requête
        if self.check(TT.SELECT):
            sub = self.parse_query()
            self.expect(TT.RPAREN)
            return SoqlIn(field=field, negated=negated, values=sub)

        # IN ('a', 'b', :var)
        values = [self._parse_value()]
        while self.match(TT.COMMA):
            values.append(self._parse_value())
        self.expect(TT.RPAREN)
        return SoqlIn(field=field, negated=negated, values=values)

    def _parse_value(self) -> SoqlValue:
        tok = self.peek()

        if tok.type == TT.STRING:
            self.advance()
            return SoqlLiteral(value=tok.value)
        if tok.type == TT.INTEGER:
            self.advance()
            return SoqlLiteral(value=int(tok.value))
        if tok.type == TT.DECIMAL:
            self.advance()
            return SoqlLiteral(value=float(tok.value))
        if tok.type == TT.TRUE:
            self.advance()
            return SoqlLiteral(value=True)
        if tok.type == TT.FALSE:
            self.advance()
            return SoqlLiteral(value=False)
        if tok.type == TT.NULL:
            self.advance()
            return SoqlLiteral(value=None)
        if tok.type == TT.BIND:
            self.advance()
            return SoqlBindVar(path=tok.value)
        if tok.type == TT.TODAY:
            self.advance()
            return SoqlDateLiteral(keyword="TODAY")
        if tok.type == TT.YESTERDAY:
            self.advance()
            return SoqlDateLiteral(keyword="YESTERDAY")

        raise SoqlParseError(
            "Valeur attendue, trouvé {} ('{}') à pos {}".format(tok.type.name, tok.value, tok.pos))


def parse(soql: str) -> SoqlSelect:
    """Parse une requête SOQL et retourne l'AST."""
    # Nettoyer les crochets Apex [SELECT ... ]
    soql = soql.strip().lstrip("[").rstrip("]").strip()
    tokens = tokenize(soql)
    parser = SoqlParser(tokens)
    return parser.parse_query()
