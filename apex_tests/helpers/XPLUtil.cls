public class XPLUtil {
    public static final String TYPE_AVIS_INITIAL = 'Avis initial';
    public static final String TYPE_AVIS_MODIFICATION = 'Avis de modification';
    public static final String TYPE_AVIS_ATTRIBUTION = 'Avis d attribution';
    public static final String TYPE_AVIS_RECTIFICATIF = 'Avis rectificatif';

    public static String truncateString(String input, Integer maxLength) {
        if (input == null) {
            return null;
        }
        if (input.length() <= maxLength) {
            return input;
        }
        return input.substring(0, maxLength);
    }
}
