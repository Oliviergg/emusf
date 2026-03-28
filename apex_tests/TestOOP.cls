public class TestOOP {
    public static void run() {
        // Instance creation with constructor
        Person p = new Person('Alice', 25);
        System.assertEquals('Alice', p.name);
        System.assertEquals(25, p.age);

        // Instance method
        System.assertEquals('Hello, Alice', p.greet());
        System.assert(p.isAdult());

        // Second instance
        Person child = new Person('Bob', 10);
        System.assertEquals('Bob', child.name);
        System.assert(!child.isAdult());

        // Mutate instance field
        child.age = 18;
        System.assert(child.isAdult());
    }
}
