public virtual class Animal {
    public String name;

    public Animal(String name) {
        this.name = name;
    }

    public virtual String speak() {
        return '...';
    }

    public virtual String getType() {
        return 'Animal';
    }

    public String introduce() {
        return this.name + ' says: ' + this.speak();
    }
}
