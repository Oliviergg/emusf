trigger AccountUpdateTrigger on Account (before update) {
    for (Account acc : Trigger.new) {
        if (acc.Industry == 'Technology') {
            acc.Rating = 'Hot';
            System.debug('TRIGGER: ' + acc.Name + ' est dans la Tech → Rating forcé à Hot');
        }
        if (acc.Name != null && acc.Name.length() > 50) {
            acc.Name = acc.Name.substring(0, 50);
            System.debug('TRIGGER: Nom tronqué à 50 caractères');
        }
    }
}
