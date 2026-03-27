public class AccountDml {
    public static void run() {
        // 1. Créer un nouveau Account
        Account acc = new Account(Name = 'Nouvelle Entreprise', Active__c = false);
        System.debug('Avant insert: Id = ' + acc.Id);
        insert acc;
        System.debug('Après insert: Id = ' + acc.Id);

        // 2. Lire le compte inséré
        String accountId = acc.Id;
        List<Account> results = [SELECT Id, Name, Active__c FROM Account WHERE Id = :accountId];
        for (Account a : results) {
            System.debug('Lu en base: ' + a.Name + ' - Active: ' + a.Active__c);
        }

        // 3. Mettre à jour le compte
        acc.Name = 'Entreprise Renommée';
        acc.Active__c = true;
        update acc;

        // 4. Relire après update
        List<Account> updated = [SELECT Id, Name, Active__c FROM Account WHERE Id = :accountId];
        for (Account u : updated) {
            System.debug('Après update: ' + u.Name + ' - Active: ' + u.Active__c);
        }
    }
}
