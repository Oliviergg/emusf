public class TestDmlPg {
    public static void run() {
        // --- INSERT ---
        Account acc = new Account(Name = 'Test Company', Type = 'Client');
        insert acc;
        System.assertNotEquals(null, acc.Id);

        // Relire depuis la base
        String accId = acc.Id;
        List<Account> results = [SELECT Id, Name, Type FROM Account WHERE Id = :accId];
        System.assertEquals(1, results.size());
        System.assertEquals('Test Company', results.get(0).Name);

        // --- INSERT Contact ---
        Contact c = new Contact(LastName = 'Dupont', FirstName = 'Jean', AccountId = acc.Id);
        insert c;
        System.assertNotEquals(null, c.Id);

        // --- UPDATE ---
        acc.Name = 'Updated Company';
        update acc;

        List<Account> updated = [SELECT Id, Name FROM Account WHERE Id = :accId];
        System.assertEquals('Updated Company', updated.get(0).Name);

        // --- DELETE ---
        String contactId = c.Id;
        delete c;
        List<Contact> deleted = [SELECT Id FROM Contact WHERE Id = :contactId];
        System.assertEquals(0, deleted.size());

        // --- Bulk INSERT ---
        List<Account> bulk = new List<Account>();
        Account a1 = new Account(Name = 'Bulk 1');
        Account a2 = new Account(Name = 'Bulk 2');
        Account a3 = new Account(Name = 'Bulk 3');
        insert a1;
        insert a2;
        insert a3;

        List<Account> all = [SELECT Id, Name FROM Account WHERE Name = 'Bulk 1'];
        System.assert(all.size() > 0);
    }
}
