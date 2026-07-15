public class Main {
    public static void run() {
        // Lire une donnée réelle de l'export
        List<Account> existing = [SELECT Id, Name FROM Account LIMIT 1];
        System.assertEquals(1, existing.size());
        System.debug('Compte réel: ' + existing[0].Name);

        // Insérer dans la transaction (annulée à la fin sauf --commit)
        Account acc = new Account();
        acc.Name = 'EMUSF Demo DML';
        insert acc;
        System.debug('Id genere (pod emulateur): ' + acc.Id);

        // La session voit sa propre écriture non committée
        List<Account> mine = [SELECT Id, Name FROM Account WHERE Name = 'EMUSF Demo DML'];
        System.assertEquals(1, mine.size());
        System.assertEquals(acc.Id, mine[0].Id);

        // Update puis relecture
        acc.Name = 'EMUSF Demo DML (maj)';
        update acc;
        List<Account> updated = [SELECT Name FROM Account WHERE Id = :acc.Id];
        System.assertEquals('EMUSF Demo DML (maj)', updated[0].Name);

        // Delete puis relecture
        delete acc;
        List<Account> gone = [SELECT Id FROM Account WHERE Id = :acc.Id];
        System.assertEquals(0, gone.size());

        System.debug('Scenario data DML OK!');
    }
}
