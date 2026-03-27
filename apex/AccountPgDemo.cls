public class AccountPgDemo {
    public static void run() {
        // Lire les 5 premiers comptes clients
        List<Account> accounts = [SELECT Id, Name, Type, Phone FROM Account WHERE Type = 'Client' LIMIT 5];

        for (Account acc : accounts) {
            System.debug('Account: ' + acc.Name + ' | Type: ' + acc.Type);
        }

        // Lire un compte avec ses contacts
        List<Account> withContacts = [SELECT Id, Name, (SELECT Id, LastName, FirstName, Email FROM Contacts) FROM Account WHERE Name = 'ILEX'];

        for (Account acc : withContacts) {
            System.debug('--- ' + acc.Name + ' ---');
            for (Contact c : acc.Contacts) {
                System.debug('  Contact: ' + c.FirstName + ' ' + c.LastName + ' | ' + c.Email);
            }
        }
    }
}
