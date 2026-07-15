public class TestHttpMock {
    public static void run() {
        // Test 1 : sans mock, Http.send retourne une réponse par défaut
        Http h1 = new Http();
        HttpRequest req1 = new HttpRequest();
        req1.setEndpoint('https://example.com/api');
        req1.setMethod('GET');
        HttpResponse res1 = h1.send(req1);
        System.assertEquals(200, res1.getStatusCode());
        System.assertEquals('{}', res1.getBody());

        // Test 2 : avec mock, Http.send délègue au mock
        MockHttpResponse mock = new MockHttpResponse(201, '{"id":"001"}');
        Test.setMock(HttpCalloutMock.class, mock);

        Http h2 = new Http();
        HttpRequest req2 = new HttpRequest();
        req2.setEndpoint('https://example.com/api/create');
        req2.setMethod('POST');
        req2.setBody('{"Name":"Test"}');
        HttpResponse res2 = h2.send(req2);
        System.assertEquals(201, res2.getStatusCode());
        System.assertEquals('{"id":"001"}', res2.getBody());

        // Test 3 : le mock reçoit bien la request (vérif endpoint)
        MockHttpResponseWithCheck mockCheck = new MockHttpResponseWithCheck();
        Test.setMock(HttpCalloutMock.class, mockCheck);

        Http h3 = new Http();
        HttpRequest req3 = new HttpRequest();
        req3.setEndpoint('https://api.test.com/check');
        req3.setMethod('GET');
        HttpResponse res3 = h3.send(req3);
        System.assertEquals(200, res3.getStatusCode());
        System.assertEquals('https://api.test.com/check', res3.getBody());
    }
}
