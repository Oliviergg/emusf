"""Tests pour les namespaces Apex : UserInfo, Limits, Schema, Blob, Id, Decimal/Double, Matcher, Assert."""

from emusf import ApexParser, ApexInterpreter
from emusf.interpreter import ApexException
import pytest


def run_apex(org, code: str) -> ApexInterpreter:
    org.create_sobject("Account", {"Name": "TEXT", "Industry": "TEXT", "AnnualRevenue": "NUMERIC"})
    org.create_sobject("Contact", {"FirstName": "TEXT", "LastName": "TEXT"})
    interp = ApexInterpreter(org)
    parser = ApexParser()
    ast = parser.parse_class(
        "public class T {{ public static void run() {{ {} }} }}".format(code),
        "run",
    )
    interp._exec_block(ast)
    return interp


# ============================================================
# UserInfo
# ============================================================

def test_userinfo_get_user_id(org):
    interp = run_apex(org, """
        System.debug(UserInfo.getUserId());
    """)
    assert interp.output[0].startswith("005")


def test_userinfo_get_name(org):
    interp = run_apex(org, """
        System.debug(UserInfo.getName());
    """)
    assert interp.output == ["Test User"]


def test_userinfo_get_user_name(org):
    interp = run_apex(org, """
        System.debug(UserInfo.getUserName());
    """)
    assert "@" in interp.output[0]


def test_userinfo_get_organization_id(org):
    interp = run_apex(org, """
        System.debug(UserInfo.getOrganizationId());
    """)
    assert interp.output[0].startswith("00D")


def test_userinfo_get_language(org):
    interp = run_apex(org, """
        System.debug(UserInfo.getLanguage());
    """)
    assert interp.output == ["fr"]


def test_userinfo_get_locale(org):
    interp = run_apex(org, """
        System.debug(UserInfo.getLocale());
    """)
    assert interp.output == ["fr_FR"]


def test_userinfo_is_multi_currency(org):
    interp = run_apex(org, """
        System.debug(UserInfo.isMultiCurrencyOrganization());
    """)
    assert interp.output == ["False"]


# ============================================================
# Limits
# ============================================================

def test_limits_get_queries(org):
    interp = run_apex(org, """
        System.debug(Limits.getQueries());
    """)
    assert interp.output == ["0"]


def test_limits_get_limit_queries(org):
    interp = run_apex(org, """
        System.debug(Limits.getLimitQueries());
    """)
    assert interp.output == ["100"]


def test_limits_get_dml_statements(org):
    interp = run_apex(org, """
        System.debug(Limits.getDmlStatements());
    """)
    assert interp.output == ["0"]


def test_limits_get_limit_dml(org):
    interp = run_apex(org, """
        System.debug(Limits.getLimitDmlStatements());
    """)
    assert interp.output == ["150"]


def test_limits_get_limit_cpu_time(org):
    interp = run_apex(org, """
        System.debug(Limits.getLimitCpuTime());
    """)
    assert interp.output == ["10000"]


def test_limits_get_limit_heap_size(org):
    interp = run_apex(org, """
        System.debug(Limits.getLimitHeapSize());
    """)
    assert interp.output == ["6000000"]


def test_limits_get_limit_callouts(org):
    interp = run_apex(org, """
        System.debug(Limits.getLimitCallouts());
    """)
    assert interp.output == ["100"]


def test_limits_defensive_pattern(org):
    """Pattern typique de code Apex défensif."""
    interp = run_apex(org, """
        Boolean canQuery = Limits.getQueries() < Limits.getLimitQueries();
        System.debug(canQuery);
    """)
    assert interp.output == ["True"]


# ============================================================
# Schema
# ============================================================

def test_schema_get_global_describe(org):
    interp = run_apex(org, """
        Map<String, Schema.SObjectType> gd = Schema.getGlobalDescribe();
        System.debug(gd != null);
    """)
    assert interp.output == ["True"]


def test_sobject_type_get_describe(org):
    interp = run_apex(org, """
        Schema.SObjectType accType = SObjectType.Account;
        Schema.DescribeSObjectResult d = accType.getDescribe();
        System.debug(d.name);
        System.debug(d.isCustom);
    """)
    assert interp.output == ["Account", "False"]


def test_sobject_type_custom(org):
    interp = run_apex(org, """
        Schema.SObjectType t = SObjectType.MyObj__c;
        Schema.DescribeSObjectResult d = t.getDescribe();
        System.debug(d.isCustom);
    """)
    assert interp.output == ["True"]


def test_sobject_type_new_sobject(org):
    interp = run_apex(org, """
        Schema.SObjectType accType = SObjectType.Account;
        SObject a = accType.newSObject();
        System.debug(a != null);
    """)
    assert interp.output == ["True"]


# ============================================================
# Blob
# ============================================================

def test_blob_value_of(org):
    interp = run_apex(org, """
        Blob b = Blob.valueOf('Hello');
        System.debug(b.toString());
    """)
    assert interp.output == ["Hello"]


def test_blob_size(org):
    interp = run_apex(org, """
        Blob b = Blob.valueOf('AB');
        System.debug(b.size());
    """)
    assert interp.output == ["2"]


# ============================================================
# Id
# ============================================================

def test_id_value_of(org):
    interp = run_apex(org, """
        Id myId = Id.valueOf('001000000000001AAA');
        System.debug(myId);
    """)
    assert interp.output == ["001000000000001AAA"]


# ============================================================
# Decimal / Double
# ============================================================

def test_decimal_set_scale(org):
    interp = run_apex(org, """
        Decimal d = 3.14159;
        System.debug(d.setScale(2));
    """)
    assert interp.output == ["3.14"]


def test_decimal_abs(org):
    interp = run_apex(org, """
        Decimal d = -42.5;
        System.debug(d.abs());
    """)
    assert interp.output == ["42.5"]


def test_decimal_int_value(org):
    interp = run_apex(org, """
        Decimal d = 3.7;
        System.debug(d.intValue());
    """)
    assert interp.output == ["3"]


def test_decimal_double_value(org):
    interp = run_apex(org, """
        Integer n = 42;
        System.debug(n.doubleValue());
    """)
    assert interp.output == ["42.0"]


def test_decimal_compare_to(org):
    interp = run_apex(org, """
        Decimal a = 10;
        Decimal b = 20;
        System.debug(a.compareTo(b));
        System.debug(b.compareTo(a));
        System.debug(a.compareTo(a));
    """)
    assert interp.output == ["-1", "1", "0"]


def test_decimal_format(org):
    interp = run_apex(org, """
        Decimal d = 42;
        System.debug(d.format());
    """)
    assert interp.output == ["42"]


def test_double_value_of(org):
    interp = run_apex(org, """
        Double d = Double.valueOf('3.14');
        System.debug(d > 3);
    """)
    assert interp.output == ["True"]


def test_decimal_value_of(org):
    interp = run_apex(org, """
        Decimal d = Decimal.valueOf('99.9');
        System.debug(d);
    """)
    assert interp.output == ["99.9"]


def test_decimal_min_max(org):
    interp = run_apex(org, """
        Decimal a = 10;
        Decimal b = 20;
        System.debug(a.min(b));
        System.debug(a.max(b));
    """)
    assert interp.output == ["10", "20"]


# ============================================================
# Matcher (complété)
# ============================================================

def test_matcher_find_group(org):
    interp = run_apex(org, """
        Pattern p = Pattern.compile('(\\\\d+)');
        Matcher m = p.matcher('abc 123 def 456');
        Boolean found = m.find();
        System.debug(found);
        System.debug(m.group(0));
    """)
    assert interp.output == ["True", "123"]


def test_matcher_iterative_find(org):
    """Vérifie que find() itère sur tous les matches."""
    interp = run_apex(org, """
        Pattern p = Pattern.compile('\\\\d+');
        Matcher m = p.matcher('a1b2c3');
        List<String> results = new List<String>();
        while (m.find()) {
            results.add(m.group(0));
        }
        System.debug(results.size());
        System.debug(results.get(0));
        System.debug(results.get(1));
        System.debug(results.get(2));
    """)
    assert interp.output == ["3", "1", "2", "3"]


def test_matcher_matches(org):
    interp = run_apex(org, """
        Pattern p = Pattern.compile('\\\\d+');
        Matcher m = p.matcher('12345');
        System.debug(m.matches());
    """)
    assert interp.output == ["True"]


def test_matcher_matches_fail(org):
    interp = run_apex(org, """
        Pattern p = Pattern.compile('\\\\d+');
        Matcher m = p.matcher('abc');
        System.debug(m.matches());
    """)
    assert interp.output == ["False"]


def test_matcher_replace_all(org):
    interp = run_apex(org, """
        Pattern p = Pattern.compile('\\\\d');
        Matcher m = p.matcher('a1b2c3');
        System.debug(m.replaceAll('X'));
    """)
    assert interp.output == ["aXbXcX"]


def test_matcher_replace_first(org):
    interp = run_apex(org, """
        Pattern p = Pattern.compile('\\\\d');
        Matcher m = p.matcher('a1b2c3');
        System.debug(m.replaceFirst('X'));
    """)
    assert interp.output == ["aXb2c3"]


def test_matcher_start_end(org):
    interp = run_apex(org, """
        Pattern p = Pattern.compile('\\\\d+');
        Matcher m = p.matcher('abc123def');
        m.find();
        System.debug(m.start());
        System.debug(m.end());
    """)
    assert interp.output == ["3", "6"]


def test_matcher_group_count(org):
    interp = run_apex(org, """
        Pattern p = Pattern.compile('(\\\\w+)@(\\\\w+)');
        Matcher m = p.matcher('user@host');
        m.find();
        System.debug(m.groupCount());
        System.debug(m.group(1));
        System.debug(m.group(2));
    """)
    assert interp.output == ["2", "user", "host"]


def test_matcher_reset(org):
    interp = run_apex(org, """
        Pattern p = Pattern.compile('\\\\d+');
        Matcher m = p.matcher('abc 123');
        m.find();
        System.debug(m.group(0));
        m.reset();
        m.find();
        System.debug(m.group(0));
    """)
    assert interp.output == ["123", "123"]


def test_matcher_looking_at(org):
    interp = run_apex(org, """
        Pattern p = Pattern.compile('\\\\d+');
        Matcher m = p.matcher('123abc');
        System.debug(m.lookingAt());
    """)
    assert interp.output == ["True"]


def test_matcher_looking_at_fail(org):
    interp = run_apex(org, """
        Pattern p = Pattern.compile('\\\\d+');
        Matcher m = p.matcher('abc123');
        System.debug(m.lookingAt());
    """)
    assert interp.output == ["False"]


# ============================================================
# Assert (API 59+)
# ============================================================

def test_assert_is_true(org):
    interp = run_apex(org, """
        Assert.isTrue(1 == 1);
        System.debug('passed');
    """)
    assert interp.output == ["passed"]


def test_assert_is_true_fails(org):
    with pytest.raises(ApexException, match="expected true"):
        run_apex(org, """
            Assert.isTrue(1 == 2);
        """)


def test_assert_is_false(org):
    interp = run_apex(org, """
        Assert.isFalse(1 == 2);
        System.debug('passed');
    """)
    assert interp.output == ["passed"]


def test_assert_is_false_fails(org):
    with pytest.raises(ApexException, match="expected false"):
        run_apex(org, """
            Assert.isFalse(true);
        """)


def test_assert_are_equal(org):
    interp = run_apex(org, """
        Assert.areEqual(42, 42);
        System.debug('passed');
    """)
    assert interp.output == ["passed"]


def test_assert_are_equal_fails(org):
    with pytest.raises(ApexException):
        run_apex(org, """
            Assert.areEqual(1, 2);
        """)


def test_assert_are_not_equal(org):
    interp = run_apex(org, """
        Assert.areNotEqual(1, 2);
        System.debug('passed');
    """)
    assert interp.output == ["passed"]


def test_assert_are_not_equal_fails(org):
    with pytest.raises(ApexException, match="values are equal"):
        run_apex(org, """
            Assert.areNotEqual(42, 42);
        """)


def test_assert_is_not_null(org):
    interp = run_apex(org, """
        Assert.isNotNull('hello');
        System.debug('passed');
    """)
    assert interp.output == ["passed"]


def test_assert_is_not_null_fails(org):
    with pytest.raises(ApexException, match="expected non-null"):
        run_apex(org, """
            Assert.isNotNull(null);
        """)


def test_assert_is_null(org):
    interp = run_apex(org, """
        Assert.isNull(null);
        System.debug('passed');
    """)
    assert interp.output == ["passed"]


def test_assert_is_null_fails(org):
    with pytest.raises(ApexException, match="expected null"):
        run_apex(org, """
            Assert.isNull('not null');
        """)


def test_assert_fail(org):
    with pytest.raises(ApexException, match="Custom message"):
        run_apex(org, """
            Assert.fail('Custom message');
        """)


def test_assert_are_equal_custom_message(org):
    with pytest.raises(ApexException, match="should be equal"):
        run_apex(org, """
            Assert.areEqual(1, 2, 'should be equal');
        """)
