public class NestedLoop {
    public static void run() {
        List<Account> accounts = [SELECT Id, Name FROM Account];
        List<Contact> contacts = [SELECT Id, LastName, AccountId FROM Contact];

        for (Account i : accounts) {
            for (Contact j : contacts) {
                if (j.AccountId == i.Id) {
                    System.debug('i=' + i.Name + ' j=' + j.LastName);
                }
            }
        }
    }
}
