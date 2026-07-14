/**
 * Scénario LIVE — orchestrateur XPL de qualification d'un marché public.
 *
 * Déroule la première étape de la machine à états ('01 - New' -> QUALIFY) :
 * lit un vrai marché, appelle le LLM via OpenRouter (LIVE), parse le score
 * et fait transiter l'analyse vers '10 - Qualified' ou '99 - Rejected'.
 *
 * Prérequis : Named Credential OpenRouterAPI (clé réelle dans
 * credentials.local.yaml), config seedée depuis le schéma data.
 */
public class Main {
    // Un vrai marché public présent dans le schéma data
    static final Id MARCHE_ID = 'a31IV000002eXLtYAM';

    public static void run() {
        // 1. Vérifier que la config de la machine à états est bien chargée
        XPL_Analyse_Type__c analyseType = [
            SELECT Id, Name FROM XPL_Analyse_Type__c LIMIT 1
        ];
        System.debug('Type d\'analyse: ' + analyseType.Name);

        XPL_Prompt_by_analyse_type__c config = [
            SELECT Id, statusApplication__c, Next_Action__c
            FROM XPL_Prompt_by_analyse_type__c
            WHERE XPL_Analyse_Type__c = :analyseType.Id
              AND statusApplication__c = '01 - New'
        ];
        System.assertEquals('QUALIFY', config.Next_Action__c,
            'La config 01-New doit déclencher QUALIFY');

        // 2. Créer une analyse fraîche pour le marché, au statut initial
        XPLMarchePublic__c marche = [
            SELECT Id, objet__c FROM XPLMarchePublic__c WHERE Id = :MARCHE_ID
        ];
        System.debug('Marché: ' + marche.objet__c);

        XPL_Analyse__c analyse = new XPL_Analyse__c(
            XPLMarchePublic__c = MARCHE_ID,
            XPL_Analyse_Type__c = analyseType.Id,
            Status__c = '01 - New'
        );
        insert analyse;
        System.debug('Analyse créée: ' + analyse.Id + ' au statut 01 - New');

        // 3. Étape QUALIFY (ce que dispatch l'orchestrateur) — appel LLM LIVE
        System.debug('=== Appel LLM (LIVE OpenRouter) ===');
        XPLAnalyseService.doProcessAnalyse(analyse.Id);

        // 4. Vérifier la transition d'état et le score produit par le LLM
        XPL_Analyse__c result = [
            SELECT Id, Status__c, relevance_score__c, relevance_score_reason__c
            FROM XPL_Analyse__c WHERE Id = :analyse.Id
        ];
        System.debug('Nouveau statut: ' + result.Status__c);
        System.debug('Score LLM: ' + result.relevance_score__c);
        System.debug('Justification: ' + result.relevance_score_reason__c);

        System.assertNotEquals('01 - New', result.Status__c,
            'Le statut doit avoir évolué après la qualification');
        System.assertNotEquals(null, result.relevance_score__c,
            'Le LLM doit avoir produit un score de pertinence');
        System.assert(
            result.Status__c == '10 - Qualified' || result.Status__c == '99 - Rejected',
            'Statut attendu Qualified ou Rejected, obtenu: ' + result.Status__c);

        System.debug('=== Scénario orchestrateur LIVE OK ===');
    }
}
