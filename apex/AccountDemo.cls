public class AccountDemo {
    public static void run() {
        String accountId = '001001';
        List<Account> accounts = [SELECT Id, Name, Active__c FROM Account WHERE Id = :accountId];
        for (Account acc : accounts) {
            System.debug('Account: ' + acc.Name + ' - Active: ' + acc.Active__c);
        }
    }
}
