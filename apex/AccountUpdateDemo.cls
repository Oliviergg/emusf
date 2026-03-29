public class AccountUpdateDemo {
    public static void run() {
        // 1. Créer un compte
        Account acc = new Account(Name = 'Ma Startup', Industry = 'Finance', Rating = 'Cold');
        insert acc;
        String accId = acc.Id;

        List<Account> check1 = [SELECT Id, Name, Industry, Rating FROM Account WHERE Id = :accId];
        for (Account a : check1) {
            System.debug('Après insert: ' + a.Name + ' | Industry=' + a.Industry + ' | Rating=' + a.Rating);
        }

        // 2. Update: changer l'industrie en Technology → le trigger force Rating = Hot
        acc.Industry = 'Technology';
        update acc;

        List<Account> check2 = [SELECT Id, Name, Industry, Rating FROM Account WHERE Id = :accId];
        for (Account a : check2) {
            System.debug('Après update: ' + a.Name + ' | Industry=' + a.Industry + ' | Rating=' + a.Rating);
        }

        // 3. Update: mettre un nom très long → le trigger le tronque
        acc.Name = 'Entreprise avec un nom vraiment beaucoup trop long pour tenir dans le champ';
        update acc;

        List<Account> check3 = [SELECT Id, Name, Industry, Rating FROM Account WHERE Id = :accId];
        for (Account a : check3) {
            System.debug('Après troncature: ' + a.Name + ' | length=' + a.Name.length());
        }
    }
}
