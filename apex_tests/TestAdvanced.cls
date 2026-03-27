public class TestAdvanced {
    public static void run() {
        // --- Ternaire ---
        String x = 'hello';
        String result = x == 'hello' ? 'yes' : 'no';
        System.assertEquals('yes', result);

        String result2 = x == 'world' ? 'yes' : 'no';
        System.assertEquals('no', result2);

        // --- While ---
        Integer count = 0;
        Integer sum = 0;
        while (count < 5) {
            sum = sum + count;
            count = count + 1;
        }
        System.assertEquals(10, sum);
        System.assertEquals(5, count);

        // --- Throw / Try-Catch ---
        String caught = '';
        try {
            throw new CustomException('test error');
        } catch (Exception e) {
            caught = e.getMessage;
        }
        System.assertEquals('test error', caught);

        // --- Method chaining ---
        String msg = '  Hello World  ';
        String trimUpper = msg.trim().toUpperCase();
        System.assertEquals('HELLO WORLD', trimUpper);

        // --- Ternaire avec null ---
        String val = null;
        String safe = val == null ? 'default' : val;
        System.assertEquals('default', safe);

        // --- While avec List ---
        List<String> items = new List<String>();
        Integer i = 0;
        while (i < 3) {
            items.add('item' + i);
            i = i + 1;
        }
        System.assertEquals(3, items.size());
        System.assertEquals('item0', items.get(0));
        System.assertEquals('item2', items.get(2));
    }
}
