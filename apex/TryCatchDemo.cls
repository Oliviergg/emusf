public class TryCatchDemo {
    public static void run() {
        try {
            System.debug('Avant erreur');
            Account acc = new Account(Name = 'Test');
            insert acc;
            System.debug('Insert OK: ' + acc.Id);
        } catch (Exception e) {
            System.debug('Erreur capturée: ' + e.getMessage);
        }

        System.debug('Après try/catch — exécution continue');
    }
}
