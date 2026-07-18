"""psycopg2.extensions — constantes minimales pour compatibilité."""

ISOLATION_LEVEL_AUTOCOMMIT = 0
ISOLATION_LEVEL_READ_COMMITTED = 1
ISOLATION_LEVEL_SERIALIZABLE = 3

TRANSACTION_STATUS_IDLE = 0
TRANSACTION_STATUS_INTRANS = 2


def register_adapter(*args, **kwargs):
    pass
