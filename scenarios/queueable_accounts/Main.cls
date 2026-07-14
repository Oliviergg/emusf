/**
 * Scénario — insère 3 comptes distincts via un QueueableJob (framework BTP).
 *
 * Enfile un InsertAccountsJob avec 3 noms distincts via QueueManager, laisse le
 * framework de file l'exécuter (Job_Event__e -> JobEventTrigger -> processNextJob
 * -> execute -> process), puis vérifie que les 3 comptes existent bien.
 */
public class Main {
    public static void run() {
        List<String> noms = new List<String>{
            'BTP Consultants Nord',
            'BTP Consultants Sud',
            'BTP Consultants Est'
        };

        System.debug('=== Enfilement du QueueableJob ===');
        InsertAccountsJob job = new InsertAccountsJob(noms);
        // createQueueJob (framework BTP) crée le Queue_Job__c et pose recordId ;
        // System.enqueueJob exécute le Queueable -> execute -> process.
        QueueableJob.createQueueJob(job);
        System.enqueueJob(job);

        // Le framework a exécuté le job de façon synchrone dans l'émulateur
        List<Account> comptes = [
            SELECT Id, Name FROM Account
            WHERE Name IN ('BTP Consultants Nord', 'BTP Consultants Sud', 'BTP Consultants Est')
            ORDER BY Name
        ];
        System.debug('Comptes trouvés: ' + comptes.size());
        for (Account a : comptes) {
            System.debug('  - ' + a.Name + ' (' + a.Id + ')');
        }

        System.assertEquals(3, comptes.size(),
            'Le QueueableJob doit avoir inséré 3 comptes distincts');

        // Vérifier qu'ils sont bien distincts (3 Ids uniques)
        Set<Id> ids = new Set<Id>();
        for (Account a : comptes) {
            ids.add(a.Id);
        }
        System.assertEquals(3, ids.size(), 'Les 3 comptes doivent avoir des Ids distincts');

        System.debug('=== 3 comptes distincts insérés via QueueableJob ===');
    }
}
