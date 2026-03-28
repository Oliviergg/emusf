public class Dog extends Animal {

    public Dog(String name) {
        super(name);
    }

    public override String speak() {
        return 'Woof!';
    }

    public override String getType() {
        return 'Dog';
    }
}
