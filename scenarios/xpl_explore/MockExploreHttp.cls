public class MockExploreHttp implements HttpCalloutMock {
    public HttpResponse respond(HttpRequest req) {
        HttpResponse res = new HttpResponse();
        String endpoint = req.getEndpoint();

        if (endpoint.contains('MarchesPublics')) {
            res.setStatusCode(200);
            res.setBody('[' +
                '{' +
                    '"ALLOTISSEMENT": false,' +
                    '"CLE_MARCHE_PUBLIC_EXPLORE": "CLE-TEST-001",' +
                    '"CODE_MESSAGE_CANDIDAT": null,' +
                    '"CODE_NATURE_CONTRAT": "TRAVAUX",' +
                    '"DATE_DEBUT_PRESTATION": "2026-04-01T00:00:00",' +
                    '"DATE_DETECTION": "2026-03-28T10:00:00",' +
                    '"DATE_ECHEANCE": "2026-06-01T00:00:00",' +
                    '"DATE_LIMITE_CANDIDATURE": null,' +
                    '"DATE_LIMITE_DEMANDE_DOC": null,' +
                    '"DATE_LIMITE_RECEPTION": "2026-04-15T12:00:00",' +
                    '"DATE_PARUTION": "2026-03-27T00:00:00",' +
                    '"DUREE": 180,' +
                    '"IDENTIFIANT": 12345,' +
                    '"IDENTIFIANT_EXPLORE": "MP#TEST-001",' +
                    '"MESSAGE_CANDIDAT": null,' +
                    '"MONTANT_MAX": 500000.00,' +
                    '"MONTANT_MIN": 100000.00,' +
                    '"MONTANT_REEL": null,' +
                    '"NATURE_CONTRAT": "Travaux",' +
                    '"OBJET": "Construction batiment bureaux ZAC Nord",' +
                    '"RENOUVELLEMENT": false,' +
                    '"SOURCE": "BOAMP",' +
                    '"TEXTE_ANNONCE": "Marche de travaux pour la construction...",' +
                    '"TYPE_AVIS": "Appel offre",' +
                    '"URL_AVIS_ORIGINAL": null,' +
                    '"URL_DETAIL": null,' +
                    '"DCES": [' +
                        '{"DATE": "2026-03-27T00:00:00", "NOM": "DCE_cahier_charges.pdf", "URL_TELECHARGEMENT": "https://example.com/dce1.pdf"}' +
                    '],' +
                    '"FORMES_MARCHE": [],' +
                    '"LOCALISATIONS": [],' +
                    '"MISSIONS": [],' +
                    '"PROCEDURES": [{"CODE": "AO", "LIBELLE": "Appel ouvert"}],' +
                    '"SOCIETES": [' +
                        '{"ACTIVITE_PRINCIPALE": "Construction", "CODE_NAF": "4120A", "CODE_TRANCHE_EFFECTIF": "50", ' +
                        '"IDENTIFIANT_SOCIETE_EXPLORE": 99999, "LOCALISATION": null, ' +
                        '"NATURE_ETABLISSEMENT": "Siege", "RAISON_SOCIALE": "Mairie de TestVille", ' +
                        '"ROLE": "Acheteur", "SIREN": "123456789", "SIRET": "12345678900010", ' +
                        '"SITE_WEB": null, "TELEPHONE": null, "TRANCHE_EFFECTIF": "50 a 99"}' +
                    '],' +
                    '"TYPES_CONTRATS": [],' +
                    '"TYPES_PRESTATIONS": []' +
                '}' +
            ']');
        } else {
            res.setStatusCode(204);
            res.setBody('');
        }

        return res;
    }
}
