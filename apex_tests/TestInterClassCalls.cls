public class TestInterClassCalls {
    public static void run() {
        // Ce test valide les appels entre classes
        // MathUtil et StringUtil sont chargés par le runner
        String result = StringUtil.truncate('Hello World', 5);
        System.assertEquals('Hello', result);

        String result2 = StringUtil.truncate('Hi', 10);
        System.assertEquals('Hi', result2);

        System.assertEquals('HELLO', StringUtil.upper('hello'));

        // Constantes de classe
        System.assertEquals('v1', StringUtil.VERSION);
    }
}
