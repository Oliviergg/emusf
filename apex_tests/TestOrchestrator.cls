public class TestOrchestrator {
    public static void run() {
        // --- Workflow status transitions ---
        System.assertEquals('10-Qualified', XPLOrchestrator.getNextStatus('01-New'));
        System.assertEquals('20-Prepared', XPLOrchestrator.getNextStatus('10-Qualified'));
        System.assertEquals('30-Extracted', XPLOrchestrator.getNextStatus('20-Prepared'));
        System.assertEquals('50-Lead', XPLOrchestrator.getNextStatus('30-Extracted'));
        System.assertEquals('98-Error', XPLOrchestrator.getNextStatus('unknown'));

        // --- hasNextStep ---
        System.assert(XPLOrchestrator.hasNextStep('01-New'));
        System.assert(XPLOrchestrator.hasNextStep('20-Prepared'));
        System.assert(!XPLOrchestrator.hasNextStep('50-Lead'));
        System.assert(!XPLOrchestrator.hasNextStep('98-Error'));

        // --- Constants ---
        System.assertEquals('01-New', XPLOrchestrator.STATUS_NEW);
        System.assertEquals('50-Lead', XPLOrchestrator.STATUS_LEAD);

        // --- Workflow loop simulation ---
        String status = '01-New';
        Integer steps = 0;
        while (XPLOrchestrator.hasNextStep(status)) {
            status = XPLOrchestrator.getNextStatus(status);
            steps = steps + 1;
        }
        System.assertEquals('50-Lead', status);
        System.assertEquals(4, steps);
    }
}
