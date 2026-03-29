public class Main {
    public static void run() {
        // --- 1. Test POST : créer un compte via l'API externe ---
        HttpRequest req = new HttpRequest();
        req.setEndpoint('callout:TestAPI/api/accounts');
        req.setMethod('POST');
        req.setHeader('Content-Type', 'application/json');
        req.setBody('{"name": "Acme Corp", "industry": "Technology"}');

        Http http = new Http();
        HttpResponse res = http.send(req);

        System.debug('POST status: ' + res.getStatusCode());
        System.debug('POST body: ' + res.getBody());
        System.assertEquals(201, res.getStatusCode(), 'POST doit retourner 201');

        // --- 2. Test GET : récupérer la liste ---
        HttpRequest getReq = new HttpRequest();
        getReq.setEndpoint('callout:TestAPI/api/accounts');
        getReq.setMethod('GET');

        HttpResponse getRes = http.send(getReq);

        System.debug('GET status: ' + getRes.getStatusCode());
        System.debug('GET body: ' + getRes.getBody());
        System.assertEquals(200, getRes.getStatusCode(), 'GET doit retourner 200');

        // --- 3. Test echo avec headers personnalisés ---
        HttpRequest echoReq = new HttpRequest();
        echoReq.setEndpoint('callout:TestAPI/api/echo');
        echoReq.setMethod('POST');
        echoReq.setBody('{"message": "hello from Apex"}');

        HttpResponse echoRes = http.send(echoReq);

        System.debug('Echo status: ' + echoRes.getStatusCode());
        System.debug('Echo body: ' + echoRes.getBody());
        System.assertEquals(200, echoRes.getStatusCode(), 'Echo doit retourner 200');

        // --- 4. Health check ---
        HttpRequest statusReq = new HttpRequest();
        statusReq.setEndpoint('callout:TestAPI/api/status');
        statusReq.setMethod('GET');

        HttpResponse statusRes = http.send(statusReq);
        System.debug('Status: ' + statusRes.getBody());
        System.assertEquals(200, statusRes.getStatusCode(), 'Status doit retourner 200');

        System.debug('Tous les tests HTTP callout sont passés !');
    }
}
