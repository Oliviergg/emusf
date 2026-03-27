public class AccountList100 {
    public static void run() {
        List<Account> accounts = [SELECT Id, Name, Type, IsPersonAccount, Famille__c, Famille_de_compte__c, Tech_RecordType__c FROM Account WHERE IsDeleted = false LIMIT 100];

        for (Account acc : accounts) {
            if (acc.IsPersonAccount == true) {
                System.debug('[B2C] ' + acc.Name + ' | ' + acc.Type + ' | Famille: ' + acc.Famille__c + ' | ' + acc.Tech_RecordType__c);
            } else {
                System.debug('[B2B] ' + acc.Name + ' | ' + acc.Type + ' | Famille: ' + acc.Famille_de_compte__c + ' | ' + acc.Tech_RecordType__c);
            }
        }
    }
}
