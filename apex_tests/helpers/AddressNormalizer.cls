public class AddressNormalizer {
    public static String normalizePostalCode(String code) {
        if (String.isBlank(code)) {
            return null;
        }
        String trimmed = code.trim();
        if (trimmed.length() > 5) {
            return null;
        }
        return trimmed;
    }

    public static String normalizeCity(String city) {
        if (String.isBlank(city)) {
            return null;
        }
        String cleaned = city.trim();
        if (cleaned.contains('CEDEX')) {
            Integer idx = cleaned.indexOf('CEDEX');
            String before = cleaned.substring(0, idx);
            return before.trim();
        }
        return cleaned;
    }

    public static String cleanAddressField(String field) {
        if (String.isBlank(field)) {
            return null;
        }
        String trimmed = field.trim();
        if (trimmed == 'N/A' || trimmed == 'null' || trimmed == '-') {
            return null;
        }
        return trimmed;
    }
}
