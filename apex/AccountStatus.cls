public class AccountStatus {
    public static void run() {
        // Lire un compte
        String accountId = '001001';
        List<Account> results = [SELECT Id, Name, Active__c FROM Account WHERE Id = :accountId];

        for (Account acc : results) {
            if (acc.Active__c == 1) {
                System.debug(acc.Name + ' est ACTIF');
            } else {
                System.debug(acc.Name + ' est INACTIF');
            }
        }

        // Tester avec le compte inactif
        String inactiveId = '001002';
        List<Account> inactive = [SELECT Id, Name, Active__c FROM Account WHERE Id = :inactiveId];

        for (Account acc : inactive) {
            if (acc.Active__c == 1) {
                System.debug(acc.Name + ' est ACTIF');
            } else if (acc.Name == 'Boring Corp') {
                System.debug(acc.Name + ' est inactif ET boring');
            } else {
                System.debug(acc.Name + ' est juste inactif');
            }
        }

        // Test avec comparaisons numériques
        Account big = new Account(Name = 'Big Corp', Active__c = true);
        insert big;

        String bigId = big.Id;
        List<Account> check = [SELECT Id, Name, Active__c FROM Account WHERE Id = :bigId];
        for (Account a : check) {
            if (a.Active__c > 0) {
                System.debug(a.Name + ' : actif (> 0)');
            }
        }
    }
}
