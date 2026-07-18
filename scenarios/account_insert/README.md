# Insertion simple

Le scénario le plus court : `Main.run()` insère un compte, vérifie que
l'émulateur a généré un Id Salesforce (base 62, préfixe `001`) et que le
compte se retrouve bien en SOQL.

Illustre : DML `insert`, génération d'Id, auto-création de table,
`System.assertEquals` (3 assertions).
