public class ListMapDemo {
    public static void run() {
        // List
        List<String> names = new List<String>();
        names.add('Alice');
        names.add('Bob');
        names.add('Charlie');
        System.debug('Size: ' + names.size());
        System.debug('First: ' + names.get(0));
        System.debug('Contains Bob: ' + names.contains('Bob'));

        // Map
        Map<String, String> emails = new Map<String, String>();
        emails.put('Alice', 'alice@example.com');
        emails.put('Bob', 'bob@example.com');
        System.debug('Map size: ' + emails.size());
        System.debug('Alice email: ' + emails.get('Alice'));
        System.debug('Has Charlie: ' + emails.containsKey('Charlie'));

        // String methods
        String msg = '  Hello World  ';
        System.debug('Trimmed: ' + msg.trim());
        System.debug('Upper: ' + msg.toUpperCase());
        System.debug('Contains World: ' + msg.contains('World'));
        System.debug('Length: ' + msg.length());
    }
}
