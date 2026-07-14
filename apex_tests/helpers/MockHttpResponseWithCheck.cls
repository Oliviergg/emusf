public class MockHttpResponseWithCheck implements HttpCalloutMock {
    public HttpResponse respond(HttpRequest req) {
        HttpResponse res = new HttpResponse();
        res.setStatusCode(200);
        res.setBody(req.getEndpoint());
        return res;
    }
}
