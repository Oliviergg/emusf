public class Main {
    public static void run() {
        Account acc = new Account();
        acc.Name = 'Globex';
        acc.Industry = 'Technology';
        insert acc;

        System.debug('Id genere: ' + acc.Id);

        // Vérifier que l'Account est bien inséré
        List<Account> results = [SELECT Id, Name, Industry FROM Account WHERE Name = 'Globex'];
        System.assertEquals(1, results.size());
        System.assertEquals('Globex', results[0].Name);
        System.assertEquals('Technology', results[0].Industry);
        System.debug('Scenario OK!');
    }
}
