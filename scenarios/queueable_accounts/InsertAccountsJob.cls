/**
 * QueueableJob (framework BTP) qui insère des comptes distincts.
 *
 * Les noms des comptes à créer sont passés via jsonParams. Le travail réel est
 * fait dans process(), exécuté de façon asynchrone par le framework de file
 * (QueueManager.enqueueJob -> Job_Event__e -> processNextJob -> execute).
 */
public class InsertAccountsJob extends QueueableJob {

    public class JobParams extends QueueableJob.JobParams {
        public List<String> accountNames = new List<String>();
    }

    public InsertAccountsJob() {
        super();
        this.jsonParams = JSON.serialize(new JobParams());
    }

    public InsertAccountsJob(List<String> accountNames) {
        super();
        JobParams params = new JobParams();
        params.accountNames = accountNames;
        this.jsonParams = JSON.serialize(params);
    }

    public override QueueableJob.JobParams getJobParams() {
        return (QueueableJob.JobParams) JSON.deserialize(this.jsonParams, JobParams.class);
    }

    protected override void process(Queue_Job__c job) {
        JobParams params = (JobParams) this.getJobParams();

        List<Account> toInsert = new List<Account>();
        for (String name : params.accountNames) {
            toInsert.add(new Account(Name = name));
        }
        insert toInsert;

        System.debug('InsertAccountsJob: ' + toInsert.size() + ' comptes insérés');
    }
}
