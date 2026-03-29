"""Tests pour le pipeline SOQL : lexer → parser → compiler."""

from emusf.soql_lexer import tokenize, TT
from emusf.soql_parser import parse
from emusf.soql_compiler import compile_soql
from emusf.soql_ast import (
    SoqlSelect, SoqlField, SoqlAggregate, SoqlSubSelect,
    SoqlComparison, SoqlAnd, SoqlOr, SoqlNullCheck, SoqlIn, SoqlNot,
    SoqlLiteral, SoqlBindVar, SoqlDateLiteral,
)


# === Lexer ===


def test_lexer_simple():
    tokens = tokenize("SELECT Id, Name FROM Account")
    types = [t.type for t in tokens]
    assert types == [TT.SELECT, TT.IDENT, TT.COMMA, TT.IDENT, TT.FROM, TT.IDENT, TT.EOF]


def test_lexer_string():
    tokens = tokenize("WHERE Name = 'Acme Corp'")
    assert tokens[3].type == TT.STRING
    assert tokens[3].value == "Acme Corp"


def test_lexer_escaped_string():
    tokens = tokenize("WHERE Name = 'It''s OK'")
    assert tokens[3].value == "It's OK"


def test_lexer_bind_variable():
    tokens = tokenize("WHERE Id = :accountId")
    assert tokens[3].type == TT.BIND
    assert tokens[3].value == "accountId"


def test_lexer_bind_dotted():
    tokens = tokenize("WHERE Id = :acc.Id")
    assert tokens[3].type == TT.BIND
    assert tokens[3].value == "acc.Id"


def test_lexer_operators():
    tokens = tokenize("WHERE x != 1 AND y <= 2 AND z >= 3")
    ops = [t for t in tokens if t.type in (TT.NEQ, TT.LTE, TT.GTE)]
    assert len(ops) == 3


def test_lexer_with_system_mode():
    tokens = tokenize("SELECT Id FROM Account WITH SYSTEM_MODE LIMIT 1")
    types = [t.type for t in tokens]
    # WITH SYSTEM_MODE doit être absent
    assert TT.IDENT not in types or all(t.value != "WITH" for t in tokens if t.type == TT.IDENT)
    assert TT.LIMIT in types


def test_lexer_count():
    tokens = tokenize("SELECT COUNT() FROM Account")
    types = [t.type for t in tokens]
    assert TT.COUNT in types


def test_lexer_number():
    tokens = tokenize("WHERE Amount > 100.50")
    num = [t for t in tokens if t.type == TT.DECIMAL]
    assert len(num) == 1
    assert num[0].value == "100.50"


# === Parser ===


def test_parse_simple():
    ast = parse("SELECT Id, Name FROM Account")
    assert ast.from_object == "Account"
    assert len(ast.fields) == 2
    assert ast.fields[0].name == "Id"
    assert ast.fields[1].name == "Name"


def test_parse_where_eq():
    ast = parse("SELECT Id FROM Account WHERE Name = 'Acme'")
    assert isinstance(ast.where, SoqlComparison)
    assert ast.where.field == "Name"
    assert ast.where.op == "="
    assert isinstance(ast.where.value, SoqlLiteral)
    assert ast.where.value.value == "Acme"


def test_parse_where_bind():
    ast = parse("SELECT Id FROM Account WHERE Id = :accountId")
    assert isinstance(ast.where, SoqlComparison)
    assert isinstance(ast.where.value, SoqlBindVar)
    assert ast.where.value.path == "accountId"


def test_parse_where_and():
    ast = parse("SELECT Id FROM Account WHERE Name = 'A' AND Active__c = true")
    assert isinstance(ast.where, SoqlAnd)


def test_parse_where_or():
    ast = parse("SELECT Id FROM Account WHERE Name = 'A' OR Name = 'B'")
    assert isinstance(ast.where, SoqlOr)


def test_parse_where_null():
    ast = parse("SELECT Id FROM Account WHERE Name = null")
    assert isinstance(ast.where, SoqlNullCheck)
    assert ast.where.is_null is True


def test_parse_where_not_null():
    ast = parse("SELECT Id FROM Account WHERE Name != null")
    assert isinstance(ast.where, SoqlNullCheck)
    assert ast.where.is_null is False


def test_parse_in_list():
    ast = parse("SELECT Id FROM Account WHERE Name IN ('A', 'B', 'C')")
    assert isinstance(ast.where, SoqlIn)
    assert not ast.where.negated
    assert len(ast.where.values) == 3


def test_parse_not_in_subquery():
    ast = parse("SELECT Id FROM Account WHERE Id NOT IN (SELECT AccountId FROM Contact)")
    assert isinstance(ast.where, SoqlIn)
    assert ast.where.negated
    assert isinstance(ast.where.values, SoqlSelect)


def test_parse_in_bind():
    ast = parse("SELECT Id FROM Account WHERE Id IN :accountIds")
    assert isinstance(ast.where, SoqlIn)
    assert len(ast.where.values) == 1
    assert isinstance(ast.where.values[0], SoqlBindVar)


def test_parse_count():
    ast = parse("SELECT COUNT() FROM Account")
    assert len(ast.fields) == 1
    assert isinstance(ast.fields[0], SoqlAggregate)
    assert ast.fields[0].function == "COUNT"
    assert ast.fields[0].field is None


def test_parse_count_field():
    ast = parse("SELECT COUNT(Id) cnt FROM Account")
    agg = ast.fields[0]
    assert isinstance(agg, SoqlAggregate)
    assert agg.function == "COUNT"
    assert agg.field == "Id"
    assert agg.alias == "cnt"


def test_parse_sum():
    ast = parse("SELECT SUM(Amount) total FROM Opportunity")
    agg = ast.fields[0]
    assert agg.function == "SUM"
    assert agg.field == "Amount"
    assert agg.alias == "total"


def test_parse_group_by():
    ast = parse("SELECT AccountId, COUNT(Id) cnt FROM Contact GROUP BY AccountId")
    assert ast.group_by == ["AccountId"]


def test_parse_having():
    ast = parse("SELECT AccountId, COUNT(Id) cnt FROM Contact GROUP BY AccountId HAVING COUNT(Id) > 1")
    assert ast.having is not None


def test_parse_order_by():
    ast = parse("SELECT Id FROM Account ORDER BY Name ASC, CreatedDate DESC NULLS LAST")
    assert len(ast.order_by) == 2
    assert ast.order_by[0].field == "Name"
    assert ast.order_by[0].direction == "ASC"
    assert ast.order_by[1].direction == "DESC"
    assert ast.order_by[1].nulls == "LAST"


def test_parse_limit():
    ast = parse("SELECT Id FROM Account LIMIT 10")
    assert ast.limit == 10


def test_parse_subquery():
    ast = parse("SELECT Id, (SELECT Id, LastName FROM Contacts) FROM Account")
    assert len(ast.fields) == 1
    assert ast.fields[0].name == "Id"
    assert len(ast.subqueries) == 1
    assert ast.subqueries[0].relationship == "Contacts"


def test_parse_relationship_field():
    ast = parse("SELECT Account.Name FROM Contact")
    assert ast.fields[0].name == "Account.Name"


def test_parse_like():
    ast = parse("SELECT Id FROM Account WHERE Name LIKE 'Acme%'")
    assert isinstance(ast.where, SoqlComparison)
    assert ast.where.op == "LIKE"


def test_parse_today():
    ast = parse("SELECT Id FROM Account WHERE CreatedDate = TODAY")
    assert isinstance(ast.where, SoqlComparison)
    assert isinstance(ast.where.value, SoqlDateLiteral)
    assert ast.where.value.keyword == "TODAY"


def test_parse_brackets():
    """SOQL en crochets Apex."""
    ast = parse("[SELECT Id FROM Account WHERE Name = 'Test']")
    assert ast.from_object == "Account"


def test_parse_with_system_mode():
    ast = parse("SELECT Id FROM Account WITH SYSTEM_MODE LIMIT 1")
    assert ast.from_object == "Account"
    assert ast.limit == 1


def test_parse_multiline():
    soql = """
        SELECT
            Id,
            Name,
            Active__c
        FROM
            Account
        WHERE
            Name = 'Test'
        ORDER BY Name
        LIMIT 5
    """
    ast = parse(soql)
    assert len(ast.fields) == 3
    assert ast.limit == 5


def test_parse_complex_where():
    ast = parse("SELECT Id FROM Account WHERE (Name = 'A' OR Name = 'B') AND Active__c = true")
    assert isinstance(ast.where, SoqlAnd)
    assert isinstance(ast.where.left, SoqlOr)


# === Compiler ===


def test_compile_simple():
    cq = compile_soql("SELECT Id, Name FROM Account", schema="test")
    assert cq.sql == "SELECT id, name FROM test.account"
    assert cq.params == []
    assert cq.sobject == "Account"
    assert cq.fields == ["Id", "Name"]


def test_compile_where_literal():
    cq = compile_soql("SELECT Id FROM Account WHERE Name = 'Acme'", schema="test")
    assert "WHERE name = %s" in cq.sql
    assert cq.params == ["Acme"]


def test_compile_where_bind():
    cq = compile_soql("SELECT Id FROM Account WHERE Id = :aid", {"aid": "001XX"}, schema="test")
    assert "WHERE id = %s" in cq.sql
    assert cq.params == ["001XX"]


def test_compile_bind_dotted_class_const():
    ctx = {"MyClass.STATUS": "Active"}
    cq = compile_soql("SELECT Id FROM Account WHERE Status__c = :MyClass.STATUS", ctx, schema="test")
    assert cq.params == ["Active"]


def test_compile_bind_obj_field():
    ctx = {"acc": {"Id": "001XX", "Name": "Test"}}
    cq = compile_soql("SELECT Id FROM Contact WHERE AccountId = :acc.Id", ctx, schema="test")
    assert cq.params == ["001XX"]


def test_compile_null_check():
    cq = compile_soql("SELECT Id FROM Account WHERE Name = null", schema="test")
    assert "name IS NULL" in cq.sql
    assert cq.params == []


def test_compile_not_null():
    cq = compile_soql("SELECT Id FROM Account WHERE Name != null", schema="test")
    assert "name IS NOT NULL" in cq.sql


def test_compile_bind_none_eq():
    cq = compile_soql("SELECT Id FROM Account WHERE Name = :x", {"x": None}, schema="test")
    assert "name IS NULL" in cq.sql
    assert cq.params == []


def test_compile_in_list():
    cq = compile_soql("SELECT Id FROM Account WHERE Name IN ('A', 'B')", schema="test")
    assert "IN (%s, %s)" in cq.sql
    assert cq.params == ["A", "B"]


def test_compile_in_bind_list():
    ctx = {"ids": ["001", "002", "003"]}
    cq = compile_soql("SELECT Id FROM Account WHERE Id IN :ids", ctx, schema="test")
    assert "IN (%s, %s, %s)" in cq.sql
    assert cq.params == ["001", "002", "003"]


def test_compile_in_bind_empty():
    ctx = {"ids": []}
    cq = compile_soql("SELECT Id FROM Account WHERE Id IN :ids", ctx, schema="test")
    assert "FALSE" in cq.sql


def test_compile_count():
    cq = compile_soql("SELECT COUNT() FROM Account", schema="test")
    assert "COUNT(*)" in cq.sql
    assert cq.is_count is True


def test_compile_aggregate():
    cq = compile_soql("SELECT SUM(Amount) total FROM Opportunity", schema="test")
    assert "SUM(amount) AS total" in cq.sql
    assert cq.is_aggregate is True


def test_compile_group_by():
    cq = compile_soql(
        "SELECT AccountId, COUNT(Id) cnt FROM Contact GROUP BY AccountId",
        schema="test"
    )
    assert "GROUP BY accountid" in cq.sql


def test_compile_order_by():
    cq = compile_soql("SELECT Id FROM Account ORDER BY Name DESC NULLS LAST", schema="test")
    assert "ORDER BY name DESC NULLS LAST" in cq.sql


def test_compile_today():
    cq = compile_soql("SELECT Id FROM Account WHERE CreatedDate = TODAY", schema="test")
    assert cq.params[0] is not None  # datetime.date


def test_compile_subquery_not_inlined():
    cq = compile_soql("SELECT Id, (SELECT Id FROM Contacts) FROM Account", schema="test")
    assert len(cq.subqueries) == 1
    assert "contacts" not in cq.sql.lower()  # la sous-requête n'est pas dans le SQL


def test_compile_not_in_subquery():
    cq = compile_soql(
        "SELECT Id FROM Account WHERE Id NOT IN (SELECT AccountId FROM Contact WHERE Active__c = true)",
        schema="test"
    )
    assert "NOT IN" in cq.sql
    assert "SELECT accountid FROM test.contact" in cq.sql
    assert cq.params == [True]


def test_compile_like():
    cq = compile_soql("SELECT Id FROM Account WHERE Name LIKE 'Acme%'", schema="test")
    assert "LIKE %s" in cq.sql
    assert cq.params == ["Acme%"]


def test_compile_and_or_precedence():
    cq = compile_soql(
        "SELECT Id FROM Account WHERE Name = 'A' OR Name = 'B' AND Active__c = true",
        schema="test"
    )
    # AND a priorité sur OR → (Name='A') OR (Name='B' AND Active=true)
    assert cq.params == ["A", "B", True]


def test_compile_date_bind():
    ctx = {"d": {"_type": "Date", "year": 2024, "month": 3, "day": 15}}
    cq = compile_soql("SELECT Id FROM Account WHERE CreatedDate = :d", ctx, schema="test")
    assert cq.params == ["2024-03-15"]
