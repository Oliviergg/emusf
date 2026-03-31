"""Tests pour les méthodes String Apex."""

from emusf import ApexParser, ApexInterpreter


def run_apex(org, code: str) -> ApexInterpreter:
    org.create_sobject("Account", {"Name": "TEXT"})
    interp = ApexInterpreter(org)
    parser = ApexParser()
    ast = parser.parse_class(
        "public class T {{ public static void run() {{ {} }} }}".format(code),
        "run",
    )
    interp._exec_block(ast)
    return interp


# === Méthodes existantes — validation de base ===


def test_length(org):
    interp = run_apex(org, """
        System.debug('hello'.length());
    """)
    assert interp.output == ["5"]


def test_contains(org):
    interp = run_apex(org, """
        System.debug('hello world'.contains('world'));
        System.debug('hello world'.contains('xyz'));
    """)
    assert interp.output == ["True", "False"]


def test_starts_ends_with(org):
    interp = run_apex(org, """
        System.debug('hello'.startsWith('hel'));
        System.debug('hello'.endsWith('llo'));
        System.debug('hello'.startsWith('xyz'));
    """)
    assert interp.output == ["True", "True", "False"]


def test_to_lower_upper_case(org):
    interp = run_apex(org, """
        System.debug('Hello'.toLowerCase());
        System.debug('Hello'.toUpperCase());
    """)
    assert interp.output == ["hello", "HELLO"]


def test_trim(org):
    interp = run_apex(org, """
        System.debug('  hi  '.trim());
    """)
    assert interp.output == ["hi"]


def test_substring(org):
    interp = run_apex(org, """
        System.debug('abcdef'.substring(2));
        System.debug('abcdef'.substring(1, 4));
    """)
    assert interp.output == ["cdef", "bcd"]


def test_index_of(org):
    interp = run_apex(org, """
        System.debug('hello world'.indexOf('world'));
        System.debug('hello world'.indexOf('xyz'));
    """)
    assert interp.output == ["6", "-1"]


def test_index_of_with_start(org):
    interp = run_apex(org, """
        System.debug('abcabc'.indexOf('bc', 2));
    """)
    assert interp.output == ["4"]


def test_replace(org):
    interp = run_apex(org, """
        System.debug('aabbcc'.replace('bb', 'XX'));
    """)
    assert interp.output == ["aaXXcc"]


def test_split(org):
    interp = run_apex(org, """
        List<String> parts = 'a,b,c'.split(',');
        System.debug(parts.size());
        System.debug(parts.get(1));
    """)
    assert interp.output == ["3", "b"]


def test_split_with_limit(org):
    interp = run_apex(org, """
        List<String> parts = 'a,b,c,d'.split(',', 2);
        System.debug(parts.size());
        System.debug(parts.get(0));
        System.debug(parts.get(1));
    """)
    assert interp.output == ["2", "a", "b,c,d"]


def test_left_right(org):
    interp = run_apex(org, """
        System.debug('abcdef'.left(3));
        System.debug('abcdef'.right(3));
    """)
    assert interp.output == ["abc", "def"]


def test_remove_start_end(org):
    interp = run_apex(org, """
        System.debug('HelloWorld'.removeStart('Hello'));
        System.debug('HelloWorld'.removeEnd('World'));
    """)
    assert interp.output == ["World", "Hello"]


def test_left_pad(org):
    interp = run_apex(org, """
        System.debug('hi'.leftPad(5));
        System.debug('hi'.leftPad(5, '0'));
    """)
    assert interp.output == ["   hi", "000hi"]


def test_replace_all(org):
    interp = run_apex(org, """
        System.debug('aaa bbb'.replaceAll('[a]+', 'X'));
    """)
    assert interp.output == ["X bbb"]


def test_equals_and_ignore_case(org):
    interp = run_apex(org, """
        System.debug('abc'.equals('abc'));
        System.debug('abc'.equals('ABC'));
        System.debug('abc'.equalsIgnoreCase('ABC'));
    """)
    assert interp.output == ["True", "False", "True"]


def test_char_at(org):
    interp = run_apex(org, """
        System.debug('abc'.charAt(1));
    """)
    assert interp.output == ["b"]


def test_repeat(org):
    interp = run_apex(org, """
        System.debug('ab'.repeat(3));
    """)
    assert interp.output == ["ababab"]


def test_abbreviate(org):
    interp = run_apex(org, """
        System.debug('Hello World Test'.abbreviate(10));
        System.debug('Short'.abbreviate(10));
    """)
    assert interp.output == ["Hello W...", "Short"]


def test_capitalize(org):
    interp = run_apex(org, """
        System.debug('hello'.capitalize());
    """)
    assert interp.output == ["Hello"]


def test_escape_single_quotes(org):
    interp = run_apex(org, r"""
        System.debug('it\'s'.escapeSingleQuotes());
    """)
    assert interp.output == ["it\\'s"]


def test_normalize_space(org):
    interp = run_apex(org, """
        System.debug('  a   b  c  '.normalizeSpace());
    """)
    assert interp.output == ["a b c"]


def test_count_matches(org):
    interp = run_apex(org, """
        System.debug('abcabcabc'.countMatches('abc'));
    """)
    assert interp.output == ["3"]


# === Nouvelles méthodes : recherche & comparaison ===


def test_contains_ignore_case(org):
    interp = run_apex(org, """
        System.debug('Hello World'.containsIgnoreCase('hello'));
        System.debug('Hello World'.containsIgnoreCase('xyz'));
    """)
    assert interp.output == ["True", "False"]


def test_starts_with_ignore_case(org):
    interp = run_apex(org, """
        System.debug('Hello'.startsWithIgnoreCase('HEL'));
        System.debug('Hello'.startsWithIgnoreCase('xyz'));
    """)
    assert interp.output == ["True", "False"]


def test_ends_with_ignore_case(org):
    interp = run_apex(org, """
        System.debug('Hello'.endsWithIgnoreCase('LLO'));
        System.debug('Hello'.endsWithIgnoreCase('xyz'));
    """)
    assert interp.output == ["True", "False"]


def test_index_of_ignore_case(org):
    interp = run_apex(org, """
        System.debug('Hello World'.indexOfIgnoreCase('WORLD'));
        System.debug('Hello World'.indexOfIgnoreCase('xyz'));
    """)
    assert interp.output == ["6", "-1"]


def test_last_index_of(org):
    interp = run_apex(org, """
        System.debug('abcabc'.lastIndexOf('abc'));
        System.debug('abcabc'.lastIndexOf('xyz'));
    """)
    assert interp.output == ["3", "-1"]


def test_last_index_of_ignore_case(org):
    interp = run_apex(org, """
        System.debug('abcABC'.lastIndexOfIgnoreCase('abc'));
    """)
    assert interp.output == ["3"]


def test_compare_to(org):
    interp = run_apex(org, """
        System.debug('abc'.compareTo('abc'));
        System.debug('abc'.compareTo('def'));
        System.debug('def'.compareTo('abc'));
    """)
    assert interp.output == ["0", "-1", "1"]


# === Nouvelles méthodes : manipulation ===


def test_mid(org):
    interp = run_apex(org, """
        System.debug('abcdef'.mid(2, 3));
    """)
    assert interp.output == ["cde"]


def test_reverse(org):
    interp = run_apex(org, """
        System.debug('hello'.reverse());
    """)
    assert interp.output == ["olleh"]


def test_right_pad(org):
    interp = run_apex(org, """
        System.debug('hi'.rightPad(5));
        System.debug('hi'.rightPad(5, '0'));
    """)
    assert interp.output == ["hi   ", "hi000"]


def test_center(org):
    interp = run_apex(org, """
        System.debug('ab'.center(6));
        System.debug('ab'.center(6, '-'));
    """)
    assert interp.output == ["  ab  ", "--ab--"]


def test_remove(org):
    interp = run_apex(org, """
        System.debug('abcabc'.remove('bc'));
    """)
    assert interp.output == ["aa"]


def test_remove_start_ignore_case(org):
    interp = run_apex(org, """
        System.debug('HelloWorld'.removeStartIgnoreCase('hello'));
    """)
    assert interp.output == ["World"]


def test_remove_end_ignore_case(org):
    interp = run_apex(org, """
        System.debug('HelloWorld'.removeEndIgnoreCase('WORLD'));
    """)
    assert interp.output == ["Hello"]


def test_replace_first(org):
    interp = run_apex(org, """
        System.debug('aaa'.replaceFirst('a', 'X'));
    """)
    assert interp.output == ["Xaa"]


def test_uncapitalize(org):
    interp = run_apex(org, """
        System.debug('Hello'.uncapitalize());
    """)
    assert interp.output == ["hello"]


def test_swap_case(org):
    interp = run_apex(org, """
        System.debug('Hello'.swapCase());
    """)
    assert interp.output == ["hELLO"]


def test_delete_whitespace(org):
    interp = run_apex(org, """
        System.debug('a b c'.deleteWhitespace());
    """)
    assert interp.output == ["abc"]


def test_strip_html_tags(org):
    interp = run_apex(org, """
        System.debug('<b>hello</b>'.stripHtmlTags());
    """)
    assert interp.output == ["hello"]


# === Nouvelles méthodes : substring helpers ===


def test_substring_after(org):
    interp = run_apex(org, """
        System.debug('hello-world'.substringAfter('-'));
    """)
    assert interp.output == ["world"]


def test_substring_after_last(org):
    interp = run_apex(org, """
        System.debug('a.b.c'.substringAfterLast('.'));
    """)
    assert interp.output == ["c"]


def test_substring_before(org):
    interp = run_apex(org, """
        System.debug('hello-world'.substringBefore('-'));
    """)
    assert interp.output == ["hello"]


def test_substring_before_last(org):
    interp = run_apex(org, """
        System.debug('a.b.c'.substringBeforeLast('.'));
    """)
    assert interp.output == ["a.b"]


def test_substring_between(org):
    interp = run_apex(org, """
        System.debug('(hello)'.substringBetween('(', ')'));
    """)
    assert interp.output == ["hello"]


# === Nouvelles méthodes : tests de contenu ===


def test_is_alpha(org):
    interp = run_apex(org, """
        System.debug('abc'.isAlpha());
        System.debug('ab2'.isAlpha());
    """)
    assert interp.output == ["True", "False"]


def test_is_alphanumeric(org):
    interp = run_apex(org, """
        System.debug('abc123'.isAlphanumeric());
        System.debug('abc 123'.isAlphanumeric());
    """)
    assert interp.output == ["True", "False"]


def test_is_numeric(org):
    interp = run_apex(org, """
        System.debug('12345'.isNumeric());
        System.debug('123a5'.isNumeric());
    """)
    assert interp.output == ["True", "False"]


def test_is_all_lower_upper(org):
    interp = run_apex(org, """
        System.debug('abc'.isAllLowerCase());
        System.debug('ABC'.isAllUpperCase());
        System.debug('Abc'.isAllLowerCase());
    """)
    assert interp.output == ["True", "True", "False"]


def test_is_whitespace(org):
    interp = run_apex(org, """
        System.debug('   '.isWhitespace());
        System.debug(' a '.isWhitespace());
    """)
    assert interp.output == ["True", "False"]


def test_contains_whitespace(org):
    interp = run_apex(org, """
        System.debug('hello world'.containsWhitespace());
        System.debug('hello'.containsWhitespace());
    """)
    assert interp.output == ["True", "False"]


def test_contains_any(org):
    interp = run_apex(org, """
        System.debug('hello'.containsAny('aeiou'));
        System.debug('xyz'.containsAny('aeiou'));
    """)
    assert interp.output == ["True", "False"]


def test_contains_none(org):
    interp = run_apex(org, """
        System.debug('hello'.containsNone('xyz'));
        System.debug('hello'.containsNone('aeiou'));
    """)
    assert interp.output == ["True", "False"]


def test_contains_only(org):
    interp = run_apex(org, """
        System.debug('aab'.containsOnly('abc'));
        System.debug('aab'.containsOnly('bc'));
    """)
    assert interp.output == ["True", "False"]


def test_is_ascii_printable(org):
    interp = run_apex(org, """
        System.debug('hello'.isAsciiPrintable());
    """)
    assert interp.output == ["True"]


# === Nouvelles méthodes : char & code ===


def test_get_chars(org):
    interp = run_apex(org, """
        List<Integer> chars = 'AB'.getChars();
        System.debug(chars.size());
        System.debug(chars.get(0));
    """)
    assert interp.output == ["2", "65"]


# === Nouvelles méthodes : distance ===


def test_difference(org):
    interp = run_apex(org, """
        System.debug('abc'.difference('abxyz'));
    """)
    assert interp.output == ["xyz"]


def test_index_of_difference(org):
    interp = run_apex(org, """
        System.debug('abc'.indexOfDifference('abxyz'));
    """)
    assert interp.output == ["2"]


# === Nouvelles méthodes : escape / unescape ===


def test_escape_html4(org):
    interp = run_apex(org, """
        System.debug('<b>hi</b>'.escapeHtml4());
    """)
    assert interp.output == ["&lt;b&gt;hi&lt;/b&gt;"]


def test_unescape_html4(org):
    interp = run_apex(org, """
        System.debug('&lt;b&gt;'.unescapeHtml4());
    """)
    assert interp.output == ["<b>"]


def test_escape_xml(org):
    interp = run_apex(org, """
        System.debug('a&b'.escapeXml());
    """)
    assert interp.output == ["a&amp;b"]


def test_unescape_xml(org):
    interp = run_apex(org, """
        System.debug('a&amp;b'.unescapeXml());
    """)
    assert interp.output == ["a&b"]


# === Méthodes statiques ===


def test_static_is_blank(org):
    interp = run_apex(org, """
        System.debug(String.isBlank(''));
        System.debug(String.isBlank('  '));
        System.debug(String.isBlank('a'));
    """)
    assert interp.output == ["True", "True", "False"]


def test_static_is_not_blank(org):
    interp = run_apex(org, """
        System.debug(String.isNotBlank('hello'));
        System.debug(String.isNotBlank(''));
    """)
    assert interp.output == ["True", "False"]


def test_static_is_empty(org):
    interp = run_apex(org, """
        System.debug(String.isEmpty(''));
        System.debug(String.isEmpty('  '));
        System.debug(String.isEmpty('a'));
    """)
    assert interp.output == ["True", "False", "False"]


def test_static_is_not_empty(org):
    interp = run_apex(org, """
        System.debug(String.isNotEmpty('hello'));
        System.debug(String.isNotEmpty(''));
    """)
    assert interp.output == ["True", "False"]


def test_static_value_of(org):
    interp = run_apex(org, """
        System.debug(String.valueOf(42));
        System.debug(String.valueOf(true));
    """)
    assert interp.output == ["42", "True"]


def test_static_join(org):
    interp = run_apex(org, """
        List<String> items = new List<String>();
        items.add('a');
        items.add('b');
        items.add('c');
        System.debug(String.join(items, '-'));
    """)
    assert interp.output == ["a-b-c"]


def test_static_format(org):
    interp = run_apex(org, """
        List<String> params = new List<String>();
        params.add('World');
        params.add('42');
        System.debug(String.format('Hello {0}, num={1}', params));
    """)
    assert interp.output == ["Hello World, num=42"]


def test_static_from_char_array(org):
    interp = run_apex(org, """
        List<Integer> chars = new List<Integer>();
        chars.add(65);
        chars.add(66);
        System.debug(String.fromCharArray(chars));
    """)
    assert interp.output == ["AB"]
