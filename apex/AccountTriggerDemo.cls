public class AccountTriggerDemo {
    public static void run() {
        // 1. Insert un compte inactif → le trigger force Active__c = 1
        Account acc = new Account(Name = 'Startup', Active__c = false);
        System.debug('Avant insert: Active = ' + acc.Active__c);
        insert acc;

        String accId = acc.Id;
        List<Account> check = [SELECT Id, Name, Active__c FROM Account WHERE Id = :accId];
        for (Account a : check) {
            System.debug('Après insert (trigger): ' + a.Name + ' Active = ' + a.Active__c);
        }

        // 2. Insert un compte déjà actif → pas de changement
        Account active = new Account(Name = 'Big Corp', Active__c = true);
        insert active;

        String activeId = active.Id;
        List<Account> check2 = [SELECT Id, Name, Active__c FROM Account WHERE Id = :activeId];
        for (Account a : check2) {
            System.debug('Déjà actif: ' + a.Name + ' Active = ' + a.Active__c);
        }

        // 3. Update qui rend inactif → trigger re-force
        active.Active__c = false;
        update active;

        List<Account> check3 = [SELECT Id, Name, Active__c FROM Account WHERE Id = :activeId];
        for (Account a : check3) {
            System.debug('Après update (trigger): ' + a.Name + ' Active = ' + a.Active__c);
        }
    }
}
