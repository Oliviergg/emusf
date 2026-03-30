"""Tests de l'API FormulaEval dans l'interpréteur Apex — sans base de données."""

from emusf.test_runner import ApexTestInterpreter


class FakeOrg:
    """Org factice pour les tests sans DB."""
    def execute_soql(self, soql):
        return []
    def insert(self, sobject, records):
        return type('R', (), {'record_ids': ['001000000000001']})()
    def update(self, sobject, records):
        pass
    def delete(self, sobject, ids):
        pass
    def add_trigger(self, *a):
        pass


def _run_apex(code: str) -> ApexTestInterpreter:
    """Parse et exécute du code Apex, retourne l'interpréteur."""
    interp = ApexTestInterpreter(FakeOrg())
    cls = interp.load_class(code, is_path=False)
    interp.call_method(cls.name, "run")
    return interp


def test_formula_builder_basic():
    """FormulaBuilder fluent API + evaluate boolean."""
    interp = _run_apex("""
    public class Test1 {
        public static void run() {
            FormulaEval.FormulaInstance fi = Formula.builder()
                .withReturnType(FormulaEval.FormulaReturnType.BOOLEAN)
                .withFormula('Amount > 100')
                .build();

            Account acc = new Account();
            acc.Amount = 200;
            Boolean result = (Boolean) fi.evaluate(acc);
            System.assert(result);

            Account acc2 = new Account();
            acc2.Amount = 50;
            System.assert(!(Boolean) fi.evaluate(acc2));
        }
    }
    """)
    assert "AssertionError" not in str(interp.output)


def test_formula_string_concat():
    """String formula with & concatenation."""
    interp = _run_apex("""
    public class Test2 {
        public static void run() {
            FormulaEval.FormulaInstance fi = Formula.builder()
                .withReturnType(FormulaEval.FormulaReturnType.STRING)
                .withFormula('Name & " - " & City')
                .build();

            Account acc = new Account();
            acc.Name = 'Acme';
            acc.City = 'Paris';
            String result = (String) fi.evaluate(acc);
            System.assertEquals('Acme - Paris', result);
        }
    }
    """)
    assert "AssertionError" not in str(interp.output)


def test_formula_number():
    """Number formula with arithmetic."""
    interp = _run_apex("""
    public class Test3 {
        public static void run() {
            FormulaEval.FormulaInstance fi = Formula.builder()
                .withReturnType(FormulaEval.FormulaReturnType.NUMBER)
                .withFormula('Price * Quantity')
                .build();

            Account acc = new Account();
            acc.Price = 10;
            acc.Quantity = 5;
            System.assertEquals(50.0, fi.evaluate(acc));
        }
    }
    """)
    assert "AssertionError" not in str(interp.output)


def test_formula_if_isblank():
    """IF/ISBLANK functions in formula."""
    interp = _run_apex("""
    public class Test4 {
        public static void run() {
            FormulaEval.FormulaInstance fi = Formula.builder()
                .withReturnType(FormulaEval.FormulaReturnType.STRING)
                .withFormula('IF(ISBLANK(Name), "N/A", Name)')
                .build();

            Account acc1 = new Account();
            acc1.Name = 'Test';
            System.assertEquals('Test', (String) fi.evaluate(acc1));

            Account acc2 = new Account();
            System.assertEquals('N/A', (String) fi.evaluate(acc2));
        }
    }
    """)
    assert "AssertionError" not in str(interp.output)


def test_get_referenced_fields():
    """getReferencedFields() returns field names."""
    interp = _run_apex("""
    public class Test5 {
        public static void run() {
            FormulaEval.FormulaInstance fi = Formula.builder()
                .withFormula('Name & " " & Industry')
                .withReturnType(FormulaEval.FormulaReturnType.STRING)
                .build();
            Set<String> fields = fi.getReferencedFields();
            System.assert(fields.contains('Name'));
            System.assert(fields.contains('Industry'));
        }
    }
    """)
    assert "AssertionError" not in str(interp.output)


def test_template_mode():
    """parseAsTemplate(true) with {!Field} merge syntax."""
    interp = _run_apex("""
    public class Test6 {
        public static void run() {
            FormulaEval.FormulaInstance fi = Formula.builder()
                .withReturnType(FormulaEval.FormulaReturnType.STRING)
                .withFormula('{!LastName}, {!FirstName}')
                .parseAsTemplate(true)
                .build();

            Contact c = new Contact();
            c.LastName = 'Doe';
            c.FirstName = 'John';
            System.assertEquals('Doe, John', (String) fi.evaluate(c));
        }
    }
    """)
    assert "AssertionError" not in str(interp.output)


def test_formula_recalculate():
    """Formula.recalculateFormulas() returns results."""
    interp = _run_apex("""
    public class Test7 {
        public static void run() {
            Account acc = new Account();
            acc.Name = 'Test';
            List<FormulaRecalcResult> results = Formula.recalculateFormulas(
                new List<Account>{ acc }
            );
            System.assertEquals(1, results.size());
            System.assert(results[0].isSuccess());
        }
    }
    """)
    assert "AssertionError" not in str(interp.output)


def test_enum_values():
    """FormulaEval.FormulaReturnType enum values are accessible."""
    interp = _run_apex("""
    public class Test8 {
        public static void run() {
            String rt = FormulaEval.FormulaReturnType.STRING;
            System.assertEquals('STRING', rt);

            String rt2 = FormulaEval.FormulaReturnType.BOOLEAN;
            System.assertEquals('BOOLEAN', rt2);

            String rt3 = FormulaEval.FormulaReturnType.NUMBER;
            System.assertEquals('NUMBER', rt3);
        }
    }
    """)
    assert "AssertionError" not in str(interp.output)


def test_formula_with_salesforce_functions():
    """Complex formula with LEN, UPPER, etc."""
    interp = _run_apex("""
    public class Test9 {
        public static void run() {
            FormulaEval.FormulaInstance fi = Formula.builder()
                .withReturnType(FormulaEval.FormulaReturnType.STRING)
                .withFormula('UPPER(LEFT(Name, 3))')
                .build();

            Account acc = new Account();
            acc.Name = 'acme corp';
            System.assertEquals('ACM', (String) fi.evaluate(acc));
        }
    }
    """)
    assert "AssertionError" not in str(interp.output)
