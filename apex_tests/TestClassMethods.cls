public class TestClassMethods {
    public static void run() {
        // Test: chargement de classe avec constantes et méthodes paramétrées
        // Simulé via les variables de l'interpréteur (la classe MathUtil est chargée par le runner)

        // String static methods
        System.assert(String.isBlank(''));
        System.assert(String.isBlank('   '));
        System.assert(!String.isBlank('hello'));
        System.assert(String.isNotBlank('hello'));
        System.assert(!String.isNotBlank(''));

        // String.valueOf
        System.assertEquals('42', String.valueOf(42));

        // List and String.join
        List<String> parts = new List<String>();
        parts.add('a');
        parts.add('b');
        parts.add('c');
        System.assertEquals('a-b-c', String.join(parts, '-'));

        // Integer.valueOf
        System.assertEquals(42, Integer.valueOf('42'));
    }
}
