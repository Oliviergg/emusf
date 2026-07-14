"""Tests de PgDataOrg — DML transactionnel sur un schéma de type export.

Utilise un schéma jetable data_emusf_test (tables typées, Ids réels 18 chars) :
ne touche jamais au vrai schéma data.
"""

import psycopg2
import pytest

from emusf import PgDataOrg, DmlException, sf_checksum, generate_sf_id
from emusf.dml import EMUSF_POD
from emusf.config import DSN

SCHEMA = "data_emusf_test"

# Ids réalistes du "vrai" export (pod IV) + un Id émulateur déjà persisté
# (pod Zz) pour tester la reprise de compteur après un run --commit
REAL_ID_1 = "001IV000031Xz4PYAS"
REAL_ID_2 = "001IV000031Xz4QYAS"
EMUSF_SEEDED_ID = generate_sf_id("001", EMUSF_POD, 5_000_000_042)


@pytest.fixture(scope="module")
def data_schema():
    """Schéma jetable avec tables typées et données seed."""
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP SCHEMA IF EXISTS {} CASCADE".format(SCHEMA))
    cur.execute("CREATE SCHEMA {}".format(SCHEMA))
    cur.execute("""
        CREATE TABLE {}.account (
            id TEXT PRIMARY KEY,
            name TEXT,
            active__c BOOLEAN,
            annualrevenue NUMERIC,
            createddate TIMESTAMP
        )""".format(SCHEMA))
    cur.execute("""
        CREATE TABLE {}.contact (
            id TEXT PRIMARY KEY,
            lastname TEXT,
            accountid TEXT
        )""".format(SCHEMA))
    cur.execute(
        "INSERT INTO {}.account (id, name, active__c, annualrevenue) VALUES "
        "(%s, 'Acme Réel', true, 1000000), (%s, 'Umbrella Réel', false, 500), "
        "(%s, 'Insérée par émulateur', true, 1)".format(SCHEMA),
        [REAL_ID_1, REAL_ID_2, EMUSF_SEEDED_ID])
    cur.close()
    yield conn
    cur = conn.cursor()
    cur.execute("DROP SCHEMA IF EXISTS {} CASCADE".format(SCHEMA))
    cur.close()
    conn.close()


@pytest.fixture()
def dorg(data_schema):
    o = PgDataOrg(DSN, schema=SCHEMA)
    yield o
    o.rollback_all()
    o.conn.close()


def _count_via_fresh_conn(sql, params=None):
    """Compte via une connexion indépendante (ne voit que le committé)."""
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(sql, params or [])
    n = cur.fetchone()[0]
    cur.close()
    conn.close()
    return n


# --- Visibilité transactionnelle ---

def test_insert_visible_dans_la_session(dorg):
    dorg.insert("Account", [{"Name": "Globex"}])
    rows = dorg.execute_soql("[SELECT Id, Name FROM Account WHERE Name = 'Globex']")
    assert len(rows) == 1
    assert dorg.pending_dml == 1


def test_insert_invisible_hors_session_avant_commit(dorg):
    dorg.insert("Account", [{"Name": "Initech"}])
    n = _count_via_fresh_conn(
        "SELECT count(*) FROM {}.account WHERE name = 'Initech'".format(SCHEMA))
    assert n == 0


def test_rollback_all_annule_tout(dorg):
    dorg.insert("Account", [{"Name": "Éphémère"}])
    dorg.rollback_all()
    assert dorg.pending_dml == 0
    rows = dorg.execute_soql("[SELECT Id FROM Account WHERE Name = 'Éphémère']")
    assert rows == []


def test_commit_persiste(dorg, data_schema):
    dorg.insert("Account", [{"Name": "Persistée"}])
    dorg.commit()
    assert dorg.pending_dml == 0
    n = _count_via_fresh_conn(
        "SELECT count(*) FROM {}.account WHERE name = 'Persistée'".format(SCHEMA))
    assert n == 1
    # cleanup (connexion autocommit de la fixture)
    cur = data_schema.cursor()
    cur.execute("DELETE FROM {}.account WHERE name = 'Persistée'".format(SCHEMA))
    cur.close()


# --- Update / delete ---

def test_update_round_trip(dorg):
    dorg.update("Account", [{"Id": REAL_ID_1, "AnnualRevenue": 2000000}])
    rows = dorg.execute_soql(
        "[SELECT AnnualRevenue FROM Account WHERE Id = '{}']".format(REAL_ID_1))
    assert float(rows[0]["AnnualRevenue"]) == 2000000
    assert dorg.pending_dml == 1


def test_delete_round_trip(dorg):
    dorg.delete("Account", [REAL_ID_2])
    rows = dorg.execute_soql(
        "[SELECT Id FROM Account WHERE Id = '{}']".format(REAL_ID_2))
    assert rows == []


def test_update_sans_id_refuse(dorg):
    with pytest.raises(DmlException, match="Id manquant"):
        dorg.update("Account", [{"Name": "Sans Id"}])


# --- Schéma strict ---

def test_sobject_inconnu_refuse(dorg):
    with pytest.raises(DmlException, match="Opportunity"):
        dorg.insert("Opportunity", [{"Name": "Deal"}])


def test_champ_inconnu_refuse_sans_alter(dorg, data_schema):
    with pytest.raises(DmlException, match="Foo__c"):
        dorg.insert("Account", [{"Name": "X", "Foo__c": "bar"}])
    # Ni table ni colonne créées
    cur = data_schema.cursor()
    cur.execute(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = 'account'", [SCHEMA])
    assert cur.fetchone()[0] == 5
    cur.close()


# --- Adaptation typée ---

def test_valeurs_typees(dorg):
    dorg.insert("Account", [{
        "Name": "Typée",
        "Active__c": True,
        "AnnualRevenue": 42,
        "CreatedDate": "2026-07-14T12:00:00",
    }])
    rows = dorg.execute_soql(
        "[SELECT Active__c, AnnualRevenue, CreatedDate FROM Account WHERE Name = 'Typée']")
    assert rows[0]["Active__c"] is True
    assert float(rows[0]["AnnualRevenue"]) == 42


def test_booleen_depuis_chaine(dorg):
    dorg.insert("Account", [{"Name": "BoolStr", "Active__c": "true"}])
    rows = dorg.execute_soql("[SELECT Active__c FROM Account WHERE Name = 'BoolStr']")
    assert rows[0]["Active__c"] is True


def test_cast_invalide_leve_dml_exception(dorg):
    with pytest.raises(DmlException):
        dorg.insert("Account", [{"Name": "BadCast", "AnnualRevenue": "pas-un-nombre"}])


# --- Génération d'Id ---

def test_id_genere_pod_emulateur(dorg):
    result = dorg.insert("Account", [{"Name": "AvecId"}])
    new_id = result.record_ids[0]
    assert len(new_id) == 18
    assert new_id[:3] == "001"
    assert new_id[3:5] == EMUSF_POD
    assert sf_checksum(new_id[:15]) == new_id[15:]
    assert new_id not in (REAL_ID_1, REAL_ID_2, EMUSF_SEEDED_ID)


def test_compteur_reprend_apres_id_persiste(dorg):
    # Un Id émulateur (compteur 5_000_000_042) existe déjà dans la table :
    # le compteur doit reprendre après, pas repartir du début
    result = dorg.insert("Account", [{"Name": "Suivant"}])
    assert result.record_ids[0] > EMUSF_SEEDED_ID


# --- Récupération savepoint ---

def test_dml_rate_ne_tue_pas_la_session(dorg):
    dorg.insert("Account", [{"Name": "Avant erreur"}])
    with pytest.raises(DmlException):
        dorg.insert("Account", [{"Name": "X", "Inconnu__c": 1}])
    # La session et l'écriture précédente survivent
    dorg.insert("Account", [{"Name": "Après erreur"}])
    avant = dorg.execute_soql("[SELECT Id FROM Account WHERE Name = 'Avant erreur']")
    apres = dorg.execute_soql("[SELECT Id FROM Account WHERE Name = 'Après erreur']")
    assert len(avant) == 1 and len(apres) == 1


def test_soql_rate_ne_tue_pas_la_session(dorg):
    dorg.insert("Account", [{"Name": "Avant SOQL raté"}])
    with pytest.raises(Exception):
        dorg.execute_soql("[SELECT Id FROM TableInconnue]")
    rows = dorg.execute_soql("[SELECT Id FROM Account WHERE Name = 'Avant SOQL raté']")
    assert len(rows) == 1


# --- Triggers opt-in ---

def test_triggers_desactives_par_defaut(dorg):
    fired = []
    dorg.add_trigger("before_insert", "Account", lambda recs, old_records=None: fired.append(1))
    dorg.insert("Account", [{"Name": "Sans trigger"}])
    assert fired == []


def test_triggers_actives_via_flag(data_schema):
    o = PgDataOrg(DSN, schema=SCHEMA, triggers_enabled=True)
    try:
        def before(recs, old_records=None):
            for r in recs:
                r["Name"] = r["Name"] + " [trigged]"
        o.add_trigger("before_insert", "Account", before)
        o.insert("Account", [{"Name": "Avec trigger"}])
        rows = o.execute_soql(
            "[SELECT Name FROM Account WHERE Name = 'Avec trigger [trigged]']")
        assert len(rows) == 1
    finally:
        o.rollback_all()
        o.conn.close()
