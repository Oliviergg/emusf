public class TestSetAndSwitch {
    public static void run() {
        // --- Set ---
        Set<String> ids = new Set<String>();
        ids.add('001');
        ids.add('002');
        ids.add('001');
        System.assertEquals(2, ids.size());
        System.assert(ids.contains('001'));
        System.assert(!ids.contains('003'));

        ids.remove('002');
        System.assertEquals(1, ids.size());

        System.assert(!ids.isEmpty());

        // Set with init values
        Set<String> colors = new Set<String>{'red', 'blue', 'green'};
        System.assertEquals(3, colors.size());
        System.assert(colors.contains('blue'));

        // --- Switch ---
        String action = 'PREPARE';
        String result = 'unknown';

        switch on action {
            when 'QUALIFY' {
                result = 'qualifying';
            }
            when 'PREPARE' {
                result = 'preparing';
            }
            when 'EXTRACT' {
                result = 'extracting';
            }
            when else {
                result = 'default';
            }
        }
        System.assertEquals('preparing', result);

        // Switch with else
        String other = 'NONE';
        String res2 = 'x';
        switch on other {
            when 'A' {
                res2 = 'a';
            }
            when else {
                res2 = 'default';
            }
        }
        System.assertEquals('default', res2);
    }
}
