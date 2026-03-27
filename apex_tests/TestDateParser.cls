public class TestDateParser {
    public static void run() {
        // --- Empty markers ---
        System.assert(DateParser.isEmptyMarker(''));
        System.assert(DateParser.isEmptyMarker('  '));
        System.assert(DateParser.isEmptyMarker('Non spécifié'));
        System.assert(DateParser.isEmptyMarker('N/A'));
        System.assert(DateParser.isEmptyMarker('-'));
        System.assert(!DateParser.isEmptyMarker('25/12/2024'));

        // --- Numeric date parsing ---
        System.assertEquals('2024-12-25', DateParser.parseNumericDate('25/12/2024'));
        System.assertEquals('2024-01-15', DateParser.parseNumericDate('15/01/2024'));
        System.assertEquals(null, DateParser.parseNumericDate(''));
        System.assertEquals(null, DateParser.parseNumericDate('Non spécifié'));
        System.assertEquals(null, DateParser.parseNumericDate('invalid'));

        // --- Month extraction ---
        System.assertEquals('01', DateParser.extractMonth('janvier'));
        System.assertEquals('01', DateParser.extractMonth('janv'));
        System.assertEquals('06', DateParser.extractMonth('juin'));
        System.assertEquals('12', DateParser.extractMonth('décembre'));
        System.assertEquals('12', DateParser.extractMonth('dec'));
        System.assertEquals('08', DateParser.extractMonth('août'));
        System.assertEquals(null, DateParser.extractMonth('invalid'));

        // --- Integration: parse and validate ---
        String raw = '  15/03/2025  ';
        String parsed = DateParser.parseNumericDate(raw);
        System.assertEquals('2025-03-15', parsed);

        // Pipeline : check then parse
        String input = 'Non renseigné';
        String result = null;
        if (!DateParser.isEmptyMarker(input)) {
            result = DateParser.parseNumericDate(input);
        }
        System.assertEquals(null, result);
    }
}
