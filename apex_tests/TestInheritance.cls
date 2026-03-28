public class TestInheritance {
    public static void run() {
        // Animal (base) → Dog (child) with override
        Dog d = new Dog('Rex');
        System.assertEquals('Rex', d.name);
        System.assertEquals('Woof!', d.speak());
        System.assertEquals('Dog', d.getType());

        // Polymorphism: base method calls overridden method
        System.assertEquals('Rex says: Woof!', d.introduce());
    }
}
