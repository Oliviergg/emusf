public class TestFormulaEval {
    public static void run() {
        // --- FormulaBuilder fluent API ---
        FormulaEval.FormulaInstance fi = Formula.builder()
            .withType(Account.SObjectType)
            .withReturnType(FormulaEval.FormulaReturnType.BOOLEAN)
            .withFormula('AnnualRevenue > 10000')
            .build();
        System.assert(fi != null);

        // --- evaluate() with Boolean return ---
        Account acc = new Account();
        acc.AnnualRevenue = 50000;
        Boolean result = (Boolean) fi.evaluate(acc);
        System.assertEquals(true, result);

        // Low revenue → false
        Account acc2 = new Account();
        acc2.AnnualRevenue = 5000;
        System.assertEquals(false, (Boolean) fi.evaluate(acc2));

        // --- String formula with concatenation ---
        FormulaEval.FormulaInstance strFormula = Formula.builder()
            .withReturnType(FormulaEval.FormulaReturnType.STRING)
            .withFormula('Name & " (" & Industry & ")"')
            .build();

        Account acc3 = new Account();
        acc3.Name = 'Acme';
        acc3.Industry = 'Tech';
        String label = (String) strFormula.evaluate(acc3);
        System.assertEquals('Acme (Tech)', label);

        // --- NUMBER return type ---
        FormulaEval.FormulaInstance numFormula = Formula.builder()
            .withReturnType(FormulaEval.FormulaReturnType.NUMBER)
            .withFormula('AnnualRevenue * 0.1')
            .build();

        Account acc4 = new Account();
        acc4.AnnualRevenue = 200;
        Object numResult = numFormula.evaluate(acc4);
        System.assertEquals(20.0, numResult);

        // --- getReferencedFields ---
        FormulaEval.FormulaInstance refFormula = Formula.builder()
            .withFormula('Name & " - " & Industry')
            .withReturnType(FormulaEval.FormulaReturnType.STRING)
            .build();
        Set<String> fields = refFormula.getReferencedFields();
        System.assert(fields.contains('Name'));
        System.assert(fields.contains('Industry'));

        // --- IF / ISBLANK functions ---
        FormulaEval.FormulaInstance ifFormula = Formula.builder()
            .withReturnType(FormulaEval.FormulaReturnType.STRING)
            .withFormula('IF(ISBLANK(Name), "Unknown", Name)')
            .build();

        Account acc5 = new Account();
        acc5.Name = 'Test';
        System.assertEquals('Test', (String) ifFormula.evaluate(acc5));

        // --- Template mode ---
        FormulaEval.FormulaInstance tmpl = Formula.builder()
            .withReturnType(FormulaEval.FormulaReturnType.STRING)
            .withFormula('{!LastName}, {!FirstName}')
            .parseAsTemplate(true)
            .build();

        Contact c = new Contact();
        c.LastName = 'Doe';
        c.FirstName = 'John';
        System.assertEquals('Doe, John', (String) tmpl.evaluate(c));

        // --- Formula.recalculateFormulas ---
        Account acc6 = new Account();
        acc6.Name = 'Recalc';
        List<FormulaRecalcResult> results = Formula.recalculateFormulas(new List<Account>{ acc6 });
        System.assertEquals(1, results.size());
        System.assertEquals(true, results[0].isSuccess());

        System.debug('TestFormulaEval: ALL PASSED');
    }
}
