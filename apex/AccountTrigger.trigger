trigger AccountTrigger on Account (before insert, before update) {
    for (Account acc : Trigger.new) {
        if (acc.Name == 'BLOCKED') {
            System.debug('TRIGGER: Account bloqué — nom interdit');
        }
        if (acc.Active__c == 0) {
            System.debug('TRIGGER: Account ' + acc.Name + ' inactif, activation forcée');
            acc.Active__c = 1;
        }
    }
}
