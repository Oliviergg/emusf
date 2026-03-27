public class StringUtil {
    public static final String VERSION = 'v1';

    public static String truncate(String input, Integer maxLen) {
        if (input == null) {
            return null;
        }
        if (input.length() > maxLen) {
            return input.substring(0, maxLen);
        }
        return input;
    }

    public static String upper(String input) {
        if (input == null) {
            return null;
        }
        return input.toUpperCase();
    }
}
