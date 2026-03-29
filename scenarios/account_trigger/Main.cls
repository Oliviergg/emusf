public class Main {
    public static void run() {
        Account acc = new Account();
        acc.Name = 'Acme Corp';
        insert acc;

        // Vérifier que le trigger a bien positionné les champs
        List<Account> results = [SELECT Id, Name, Rating, Description FROM Account WHERE Name = 'Acme Corp'];
        System.debug('Nombre de résultats: ' + results.size());
        System.debug('Rating: ' + results[0].Rating);
        System.debug('Description: ' + results[0].Description);

        System.assertEquals('Cold', results[0].Rating);
        System.assertEquals('Auto-filled by trigger', results[0].Description);
        System.debug('Scenario OK!');
    }
}
