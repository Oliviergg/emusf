public class TestDataTransform {
    public static void run() {
        // Simule le pattern XPLExploreService : données API → SObject

        // --- 1. Données brutes (simulant une réponse API) ---
        Map<String, String> rawMarche = new Map<String, String>();
        rawMarche.put('titre', 'Construction école primaire');
        rawMarche.put('organisme', 'Mairie de Lyon');
        rawMarche.put('codePostal', '69001');
        rawMarche.put('ville', 'Lyon CEDEX 2');
        rawMarche.put('dateLimite', '15/06/2025');
        rawMarche.put('typeAvis', 'Avis initial');

        // --- 2. Normalisation des données ---
        String cp = AddressNormalizer.normalizePostalCode(rawMarche.get('codePostal'));
        System.assertEquals('69001', cp);

        String ville = AddressNormalizer.normalizeCity(rawMarche.get('ville'));
        System.assertEquals('Lyon', ville);

        String dateLimite = DateParser.parseNumericDate(rawMarche.get('dateLimite'));
        System.assertEquals('2025-06-15', dateLimite);

        // --- 3. Truncation (XPLUtil pattern) ---
        String titre = XPLUtil.truncateString(rawMarche.get('titre'), 20);
        System.assertEquals('Construction école p', titre);

        // --- 4. Status determination (XPLAnalyseService pattern) ---
        String typeAvis = rawMarche.get('typeAvis');
        String initialStatus = 'unknown';
        switch on typeAvis {
            when 'Avis initial' {
                initialStatus = '01-New';
            }
            when 'Avis de modification' {
                initialStatus = '02-Update';
            }
            when 'Avis d attribution' {
                initialStatus = '03-Attribution';
            }
        }
        System.assertEquals('01-New', initialStatus);

        // --- 5. Filtering (eliminateExistingMarches pattern) ---
        Set<String> existingIds = new Set<String>{'M001', 'M002', 'M003'};
        List<String> incoming = new List<String>();
        incoming.add('M002');
        incoming.add('M004');
        incoming.add('M005');
        incoming.add('M001');

        List<String> toInsert = new List<String>();
        for (String id : incoming) {
            if (!existingIds.contains(id)) {
                toInsert.add(id);
            }
        }
        System.assertEquals(2, toInsert.size());

        // --- 6. Workflow execution ---
        String status = initialStatus;
        List<String> log = new List<String>();

        while (XPLOrchestrator.hasNextStep(status)) {
            String nextStatus = XPLOrchestrator.getNextStatus(status);
            log.add(status + ' -> ' + nextStatus);
            status = nextStatus;
        }
        System.assertEquals('50-Lead', status);
        System.assertEquals(4, log.size());
        System.assertEquals('01-New -> 10-Qualified', log.get(0));
        System.assertEquals('30-Extracted -> 50-Lead', log.get(3));

        // --- 7. Result assembly ---
        Map<String, String> result = new Map<String, String>();
        result.put('titre', titre);
        result.put('codePostal', cp);
        result.put('ville', ville);
        result.put('dateLimite', dateLimite);
        result.put('status', status);

        System.assertEquals('50-Lead', result.get('status'));
        System.assertEquals('Lyon', result.get('ville'));
        System.assert(!result.isEmpty());
        System.assertEquals(5, result.size());
    }
}
