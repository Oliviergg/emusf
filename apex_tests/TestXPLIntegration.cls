public class TestXPLIntegration {
    public static void run() {
        // --- XPLUtil constants ---
        System.assertEquals('Avis initial', XPLUtil.TYPE_AVIS_INITIAL);
        System.assertEquals('Avis de modification', XPLUtil.TYPE_AVIS_MODIFICATION);

        // --- XPLUtil.truncateString ---
        System.assertEquals('Hello', XPLUtil.truncateString('Hello World', 5));
        System.assertEquals('Hi', XPLUtil.truncateString('Hi', 10));
        System.assertEquals(null, XPLUtil.truncateString(null, 5));

        // --- AddressNormalizer.normalizePostalCode ---
        System.assertEquals('75001', AddressNormalizer.normalizePostalCode('75001'));
        System.assertEquals('75001', AddressNormalizer.normalizePostalCode('  75001  '));
        System.assertEquals(null, AddressNormalizer.normalizePostalCode(''));
        System.assertEquals(null, AddressNormalizer.normalizePostalCode('123456'));

        // --- AddressNormalizer.normalizeCity ---
        System.assertEquals('Paris', AddressNormalizer.normalizeCity('Paris'));
        System.assertEquals('Lyon', AddressNormalizer.normalizeCity('Lyon CEDEX 3'));
        System.assertEquals(null, AddressNormalizer.normalizeCity(''));

        // --- AddressNormalizer.cleanAddressField ---
        System.assertEquals('12 rue de la Paix', AddressNormalizer.cleanAddressField('12 rue de la Paix'));
        System.assertEquals(null, AddressNormalizer.cleanAddressField('N/A'));
        System.assertEquals(null, AddressNormalizer.cleanAddressField('null'));
        System.assertEquals(null, AddressNormalizer.cleanAddressField('-'));
        System.assertEquals(null, AddressNormalizer.cleanAddressField(''));

        // --- Workflow simulation : determine status based on type ---
        String typeAvis = 'Avis initial';
        String status = 'unknown';

        switch on typeAvis {
            when 'Avis initial' {
                status = '01-New';
            }
            when 'Avis de modification' {
                status = '02-Update';
            }
            when 'Avis d attribution' {
                status = '03-Attribution';
            }
            when else {
                status = '99-Unknown';
            }
        }
        System.assertEquals('01-New', status);

        // --- Collection workflow : filter ids ---
        Set<String> existingIds = new Set<String>{'ID1', 'ID2', 'ID3'};
        List<String> newIds = new List<String>();
        newIds.add('ID2');
        newIds.add('ID4');
        newIds.add('ID5');

        List<String> toInsert = new List<String>();
        for (String id : newIds) {
            if (!existingIds.contains(id)) {
                toInsert.add(id);
            }
        }
        System.assertEquals(2, toInsert.size());
    }
}
