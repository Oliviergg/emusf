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
        System.debug('Insert OK!');

        // --- Update: le flow before update doit positionner BillingCity ---
        Account toUpdate = results[0];
        toUpdate.Name = 'Acme Corp Updated';
        update toUpdate;

        List<Account> after = [SELECT Id, Name, BillingCity FROM Account WHERE Id = :toUpdate.Id];
        System.debug('Name apres update: ' + after[0].Name);
        System.debug('BillingCity apres update: ' + after[0].BillingCity);

        System.assertEquals('Acme Corp Updated', after[0].Name);
        System.assertEquals('Paris', after[0].BillingCity);
        System.debug('Scenario OK!');
    }
}
