trigger AccountTrigger on Account (before insert) {
    for (Account acc : Trigger.new) {
        if (acc.Rating == null) {
            acc.Rating = AccountHelper.defaultRating();
        }
    }
    AccountHelper.stampDescription(Trigger.new);
}
