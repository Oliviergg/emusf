public class DateParser {
    public static final String EMPTY_MARKER_1 = 'Non spécifié';
    public static final String EMPTY_MARKER_2 = 'Non renseigné';

    public static Boolean isEmptyMarker(String value) {
        if (String.isBlank(value)) {
            return true;
        }
        String trimmed = value.trim().toLowerCase();
        if (trimmed == 'non spécifié' || trimmed == 'non renseigné' || trimmed == 'n/a' || trimmed == '-') {
            return true;
        }
        return false;
    }

    public static String parseNumericDate(String input) {
        if (String.isBlank(input)) {
            return null;
        }
        if (isEmptyMarker(input)) {
            return null;
        }
        String trimmed = input.trim();
        // Simple DD/MM/YYYY check
        if (trimmed.length() == 10 && trimmed.substring(2, 3) == '/' && trimmed.substring(5, 6) == '/') {
            String day = trimmed.substring(0, 2);
            String month = trimmed.substring(3, 5);
            String year = trimmed.substring(6, 10);
            return year + '-' + month + '-' + day;
        }
        return null;
    }

    public static String extractMonth(String monthName) {
        String lower = monthName.toLowerCase().trim();
        if (lower == 'janvier' || lower == 'janv') {
            return '01';
        }
        if (lower == 'février' || lower == 'fevrier' || lower == 'fev') {
            return '02';
        }
        if (lower == 'mars') {
            return '03';
        }
        if (lower == 'avril' || lower == 'avr') {
            return '04';
        }
        if (lower == 'mai') {
            return '05';
        }
        if (lower == 'juin') {
            return '06';
        }
        if (lower == 'juillet' || lower == 'juil') {
            return '07';
        }
        if (lower == 'août' || lower == 'aout') {
            return '08';
        }
        if (lower == 'septembre' || lower == 'sept') {
            return '09';
        }
        if (lower == 'octobre' || lower == 'oct') {
            return '10';
        }
        if (lower == 'novembre' || lower == 'nov') {
            return '11';
        }
        if (lower == 'décembre' || lower == 'decembre' || lower == 'dec') {
            return '12';
        }
        return null;
    }
}
