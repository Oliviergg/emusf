"""Tests pour les extensions du langage Apex (List, Map, String, return, try/catch)."""

from emusf import ApexParser, ApexInterpreter


def run_apex(org, code: str) -> ApexInterpreter:
    org.create_sobject("Account", {"Name": "TEXT", "Active__c": "INTEGER DEFAULT 0"})
    interp = ApexInterpreter(org)
    parser = ApexParser()
    ast = parser.parse_class(
        "public class T {{ public static void run() {{ {} }} }}".format(code),
        "run",
    )
    interp._exec_block(ast)
    return interp


def test_list_add_size(org):
    interp = run_apex(org, """
        List<String> names = new List<String>();
        names.add('a');
        names.add('b');
        System.debug(names.size());
    """)
    assert interp.output == ["2"]


def test_list_get_contains(org):
    interp = run_apex(org, """
        List<String> items = new List<String>();
        items.add('x');
        items.add('y');
        System.debug(items.get(0));
        System.debug(items.contains('y'));
    """)
    assert interp.output == ["x", "True"]


def test_list_isEmpty(org):
    interp = run_apex(org, """
        List<String> empty = new List<String>();
        System.debug(empty.isEmpty());
        empty.add('a');
        System.debug(empty.isEmpty());
    """)
    assert interp.output == ["True", "False"]


def test_map_put_get(org):
    interp = run_apex(org, """
        Map<String, String> m = new Map<String, String>();
        m.put('key', 'val');
        System.debug(m.get('key'));
        System.debug(m.containsKey('nope'));
    """)
    assert interp.output == ["val", "False"]


def test_map_size(org):
    interp = run_apex(org, """
        Map<String, String> m = new Map<String, String>();
        m.put('a', '1');
        m.put('b', '2');
        System.debug(m.size());
    """)
    assert interp.output == ["2"]


def test_string_methods(org):
    interp = run_apex(org, """
        String s = 'Hello World';
        System.debug(s.length());
        System.debug(s.toLowerCase());
        System.debug(s.contains('World'));
        System.debug(s.indexOf('World'));
    """)
    assert interp.output == ["11", "hello world", "True", "6"]


def test_return_stops_execution(org):
    interp = run_apex(org, """
        System.debug('before');
        return;
        System.debug('after');
    """)
    assert interp.output == ["before"]


def test_try_catch(org):
    interp = run_apex(org, """
        try {
            System.debug('in try');
        } catch (Exception e) {
            System.debug('caught');
        }
        System.debug('after');
    """)
    assert interp.output == ["in try", "after"]
