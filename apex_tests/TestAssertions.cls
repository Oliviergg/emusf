public class TestAssertions {
    public static void run() {
        // System.assert
        System.assert(true);
        System.assert(1 == 1);
        System.assert('hello' != 'world');

        // System.assertEquals
        System.assertEquals('abc', 'abc');
        System.assertEquals(42, 42);

        // System.assertNotEquals
        System.assertNotEquals('a', 'b');
        System.assertNotEquals(1, 2);

        // List assertions
        List<String> names = new List<String>();
        names.add('Alice');
        System.assertEquals(1, names.size());
        System.assert(names.contains('Alice'));

        // Map assertions
        Map<String, String> m = new Map<String, String>();
        m.put('key', 'val');
        System.assertEquals('val', m.get('key'));
        System.assert(m.containsKey('key'));
        System.assert(!m.containsKey('nope'));
    }
}
