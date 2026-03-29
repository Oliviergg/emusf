public class AccountHelper {
    public static String defaultRating() {
        return 'Cold';
    }

    public static void stampDescription(List<Account> accounts) {
        for (Account acc : accounts) {
            if (acc.Description == null) {
                acc.Description = 'Auto-filled by trigger';
            }
        }
    }
}
