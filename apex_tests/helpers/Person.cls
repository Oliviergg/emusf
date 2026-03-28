public class Person {
    public String name;
    public Integer age;

    public Person(String name, Integer age) {
        this.name = name;
        this.age = age;
    }

    public String greet() {
        return 'Hello, ' + this.name;
    }

    public Boolean isAdult() {
        return this.age >= 18;
    }
}
