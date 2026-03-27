"""Tests pour if/else et opérateurs de comparaison."""

from emusf import FakeOrg, ApexParser, ApexInterpreter


def make_interp():
    org = FakeOrg()
    org.create_sobject("Account", {"Name": "TEXT", "Active__c": "INTEGER DEFAULT 0"})
    return ApexInterpreter(org)


def test_if_true():
    interp = make_interp()
    parser = ApexParser()
    ast = parser.parse_class("""
    public class T {
        public static void run() {
            String x = 'yes';
            if (x == 'yes') {
                System.debug('ok');
            }
        }
    }
    """, "run")
    interp._exec_block(ast)
    assert interp.output == ["ok"]


def test_if_false_else():
    interp = make_interp()
    parser = ApexParser()
    ast = parser.parse_class("""
    public class T {
        public static void run() {
            String x = 'no';
            if (x == 'yes') {
                System.debug('ok');
            } else {
                System.debug('nope');
            }
        }
    }
    """, "run")
    interp._exec_block(ast)
    assert interp.output == ["nope"]


def test_else_if():
    interp = make_interp()
    parser = ApexParser()
    ast = parser.parse_class("""
    public class T {
        public static void run() {
            String x = 'maybe';
            if (x == 'yes') {
                System.debug('1');
            } else if (x == 'maybe') {
                System.debug('2');
            } else {
                System.debug('3');
            }
        }
    }
    """, "run")
    interp._exec_block(ast)
    assert interp.output == ["2"]


def test_comparison_operators():
    interp = make_interp()
    parser = ApexParser()
    ast = parser.parse_class("""
    public class T {
        public static void run() {
            if (5 > 3) {
                System.debug('gt');
            }
            if (2 < 10) {
                System.debug('lt');
            }
            if (3 >= 3) {
                System.debug('gte');
            }
            if (3 <= 3) {
                System.debug('lte');
            }
            if (1 != 2) {
                System.debug('neq');
            }
        }
    }
    """, "run")
    interp._exec_block(ast)
    assert interp.output == ["gt", "lt", "gte", "lte", "neq"]


def test_logical_and_or():
    interp = make_interp()
    parser = ApexParser()
    ast = parser.parse_class("""
    public class T {
        public static void run() {
            if (1 == 1 && 2 == 2) {
                System.debug('and_ok');
            }
            if (1 == 2 || 3 == 3) {
                System.debug('or_ok');
            }
        }
    }
    """, "run")
    interp._exec_block(ast)
    assert interp.output == ["and_ok", "or_ok"]
