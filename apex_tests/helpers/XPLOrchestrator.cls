public class XPLOrchestrator {
    public static final String STATUS_NEW = '01-New';
    public static final String STATUS_QUALIFIED = '10-Qualified';
    public static final String STATUS_PREPARED = '20-Prepared';
    public static final String STATUS_EXTRACTED = '30-Extracted';
    public static final String STATUS_LEAD = '50-Lead';
    public static final String STATUS_ERROR = '98-Error';

    public class WorkflowResult {
        public Boolean success;
        public String message;
        public String nextStatus;
    }

    public static String getNextStatus(String currentStatus) {
        String next = STATUS_ERROR;
        switch on currentStatus {
            when '01-New' {
                next = STATUS_QUALIFIED;
            }
            when '10-Qualified' {
                next = STATUS_PREPARED;
            }
            when '20-Prepared' {
                next = STATUS_EXTRACTED;
            }
            when '30-Extracted' {
                next = STATUS_LEAD;
            }
            when else {
                next = STATUS_ERROR;
            }
        }
        return next;
    }

    public static Boolean hasNextStep(String status) {
        Set<String> terminalStatuses = new Set<String>{STATUS_LEAD, STATUS_ERROR};
        return !terminalStatuses.contains(status);
    }
}
