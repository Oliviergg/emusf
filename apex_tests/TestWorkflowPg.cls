public class TestWorkflowPg {
    public static void run() {
        // Simule un workflow XPL complet avec données en base

        // 1. Créer un marché
        Account marche = new Account(Name = 'Marché construction école', Type = 'Prospect');
        insert marche;

        // 2. Créer des contacts associés
        Contact c1 = new Contact(LastName = 'Chef projet', AccountId = marche.Id);
        Contact c2 = new Contact(LastName = 'Architecte', AccountId = marche.Id);
        insert c1;
        insert c2;

        // 3. Vérifier les données insérées
        String marcheId = marche.Id;
        List<Account> loaded = [SELECT Id, Name, Type, (SELECT Id, LastName FROM Contacts) FROM Account WHERE Id = :marcheId];
        System.assertEquals(1, loaded.size());
        System.assertEquals(2, loaded.get(0).Contacts.size());

        // 4. Simuler une transformation de données (pattern XPL)
        String rawPostalCode = '  69001  ';
        String rawCity = 'Lyon CEDEX 3';
        String normalizedCp = AddressNormalizer.normalizePostalCode(rawPostalCode);
        String normalizedCity = AddressNormalizer.normalizeCity(rawCity);

        System.assertEquals('69001', normalizedCp);
        System.assertEquals('Lyon', normalizedCity);

        // 5. Simuler un workflow de status
        String status = '01-New';
        Integer steps = 0;
        while (XPLOrchestrator.hasNextStep(status)) {
            status = XPLOrchestrator.getNextStatus(status);
            steps = steps + 1;
        }
        System.assertEquals('50-Lead', status);

        // 6. Mettre à jour le marché avec le résultat
        marche.Type = 'Client';
        marche.Name = 'Marché gagné - école';
        update marche;

        List<Account> finalCheck = [SELECT Id, Name, Type FROM Account WHERE Id = :marcheId];
        System.assertEquals('Client', finalCheck.get(0).Type);
        System.assertEquals('Marché gagné - école', finalCheck.get(0).Name);
    }
}
