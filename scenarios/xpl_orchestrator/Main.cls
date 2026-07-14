/**
 * Scénario LIVE — pipeline de qualification XPL sur un lot de marchés réels.
 *
 * Pour chaque marché : crée une analyse au statut '01 - New', déroule l'étape
 * QUALIFY (appel LLM LIVE via OpenRouter), et affiche le verdict. Résumé final
 * qualifiés / rejetés — exactement ce que fait la qualification de masse de
 * l'orchestrateur, mais exécutée localement sur les vraies données.
 */
public class Main {
    // Marchés publics réels (schéma data) — types d'avis variés
    static final List<Id> MARCHE_IDS = new List<Id>{
        'a31IV000002eXT0YAM', // Mission de CT — établissement de soins (cœur de métier)
        'a31IV000002eXpQYAU', // Missions de CT contrôle technique
        'a31IV000002eXQwYAM', // MOE rénovation thermique (hors périmètre)
        'a31IV000002eXSUYA2'  // AOT centrales photovoltaïques (hors périmètre)
    };

    public static void run() {
        XPL_Analyse_Type__c analyseType = [
            SELECT Id, Name FROM XPL_Analyse_Type__c LIMIT 1
        ];
        System.debug('=== Qualification LIVE — type: ' + analyseType.Name + ' ===');

        Integer qualified = 0;
        Integer rejected = 0;

        for (Id marcheId : MARCHE_IDS) {
            XPLMarchePublic__c marche = [
                SELECT Id, objet__c, TYPE_AVIS__c
                FROM XPLMarchePublic__c WHERE Id = :marcheId
            ];

            XPL_Analyse__c analyse = new XPL_Analyse__c(
                XPLMarchePublic__c = marcheId,
                XPL_Analyse_Type__c = analyseType.Id,
                Status__c = '01 - New'
            );
            insert analyse;

            // Étape QUALIFY (appel LLM LIVE)
            XPLAnalyseService.doProcessAnalyse(analyse.Id);

            XPL_Analyse__c result = [
                SELECT Status__c, relevance_score__c, relevance_score_reason__c
                FROM XPL_Analyse__c WHERE Id = :analyse.Id
            ];

            System.debug('--- ' + marche.objet__c);
            System.debug('    Avis: ' + marche.TYPE_AVIS__c
                + ' | Score: ' + result.relevance_score__c
                + ' | ' + result.Status__c);
            System.debug('    -> ' + result.relevance_score_reason__c);

            if (result.Status__c == '10 - Qualified') {
                qualified++;
            } else if (result.Status__c == '99 - Rejected') {
                rejected++;
            }
            System.assertNotEquals(null, result.relevance_score__c,
                'Le LLM doit produire un score pour chaque marché');
        }

        System.debug('=== Bilan: ' + qualified + ' qualifiés, ' + rejected + ' rejetés '
            + 'sur ' + MARCHE_IDS.size() + ' marchés ===');
        System.assertEquals(MARCHE_IDS.size(), qualified + rejected,
            'Chaque marché doit être soit qualifié soit rejeté');
    }
}
