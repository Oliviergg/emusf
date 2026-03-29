public class AccountDemo {
    public static void run() {
        String accountId = '001001';
        List<Account> accounts = [SELECT Id, Name, famille_de_compte__c FROM Account WHERE Id = :accountId];
        for (Account acc : accounts) {
            System.debug('Account: ' + acc.Name + ' - Famille: ' + acc.famille_de_compte__c);
        }
    }
}
