# Trigger + Flow sur Account

`Main.run()` insère un compte puis le met à jour :

- à l'**insert**, le trigger `AccountTrigger` (before insert) pose le
  `Rating` par défaut via `AccountHelper` et tamponne la `Description` ;
- à l'**update**, le flow `FL_SetBillingCity` (record-triggered, before
  save) positionne `BillingCity` à « Paris ».

Illustre : trigger before insert, classe utilitaire appelée depuis un
trigger, flow record-triggered exécuté par l'émulateur, 4 assertions.
