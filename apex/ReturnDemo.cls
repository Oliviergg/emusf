public class ReturnDemo {
    public static void run() {
        List<Account> accounts = [SELECT Id, Name, Type FROM Account WHERE IsDeleted = false LIMIT 10];

        for (Account acc : accounts) {
            if (acc.Name == 'ILEX') {
                System.debug('Trouvé: ' + acc.Name);
                return;
            }
        }

        System.debug('ILEX non trouvé');
    }
}
