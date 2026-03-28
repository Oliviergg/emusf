public class TestSoqlPg {
    public static void run() {
        // Setup : insérer des données
        Account acc1 = new Account(Name = 'Alpha Corp', Type = 'Client');
        Account acc2 = new Account(Name = 'Beta Inc', Type = 'Prospect');
        Account acc3 = new Account(Name = 'Gamma SA', Type = 'Client');
        insert acc1;
        insert acc2;
        insert acc3;

        // --- SELECT avec WHERE ---
        List<Account> clients = [SELECT Id, Name, Type FROM Account WHERE Type = 'Client'];
        System.assertEquals(2, clients.size());

        // --- SELECT avec LIMIT ---
        List<Account> limited = [SELECT Id, Name FROM Account LIMIT 2];
        System.assertEquals(2, limited.size());

        // --- SELECT avec ORDER BY ---
        List<Account> ordered = [SELECT Id, Name FROM Account ORDER BY Name];
        System.assertEquals('Alpha Corp', ordered.get(0).Name);

        // --- COUNT via size ---
        List<Account> all = [SELECT Id FROM Account];
        System.assert(all.size() >= 3);

        // --- Sous-requête: Account avec Contacts ---
        Contact c1 = new Contact(LastName = 'Dupont', AccountId = acc1.Id);
        Contact c2 = new Contact(LastName = 'Martin', AccountId = acc1.Id);
        Contact c3 = new Contact(LastName = 'Bernard', AccountId = acc2.Id);
        insert c1;
        insert c2;
        insert c3;

        String alphaId = acc1.Id;
        List<Account> withContacts = [SELECT Id, Name, (SELECT Id, LastName FROM Contacts) FROM Account WHERE Id = :alphaId];
        System.assertEquals(1, withContacts.size());
        System.assertEquals(2, withContacts.get(0).Contacts.size());

        // --- Bind variable ---
        String targetName = 'Beta Inc';
        List<Account> bound = [SELECT Id, Name FROM Account WHERE Name = :targetName];
        System.assertEquals(1, bound.size());
        System.assertEquals('Beta Inc', bound.get(0).Name);
    }
}
