public class AccountDemo {
    public static void run() {
        List<Account> accounts = [SELECT Id, Name, Active__c FROM Account];
        for (Account acc : accounts) {
            System.debug('Account: ' + acc.Name + ' - Active: ' + acc.Active__c);
        }
    }
}
