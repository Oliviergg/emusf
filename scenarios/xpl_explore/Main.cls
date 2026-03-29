public class Main {
    public static void run() {
        // Pas de mock : vrai appel HTTP a l API Explore
        System.debug('=== Lancement fetchMarchesPublics (LIVE) ===');
        List<XPLMarchePublic__c> result = XPLExploreService.fetchMarchesPublics();
        System.debug('Nombre de marches inseres: ' + result.size());

        // Verifier les marches en base
        List<XPLMarchePublic__c> marches = [SELECT Id, IDENTIFIANT_EXPLORE__c, Objet__c, TYPE_AVIS__c FROM XPLMarchePublic__c LIMIT 5];
        System.debug('Marches en base: ' + marches.size());

        for (XPLMarchePublic__c m : marches) {
            System.debug('  > ' + m.IDENTIFIANT_EXPLORE__c + ' | ' + m.Objet__c);
        }

        // Verifier les DCEs
        List<XPLDCE__c> dces = [SELECT Id, NOM__c FROM XPLDCE__c LIMIT 5];
        System.debug('DCEs en base: ' + dces.size());

        System.debug('=== Fin ===');
    }
}
