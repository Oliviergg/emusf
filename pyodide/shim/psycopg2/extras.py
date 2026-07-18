"""psycopg2.extras — RealDictCursor pour le shim SQLite."""


class RealDictRow(dict):
    """Ligne résultat sous forme de dict (comme psycopg2.extras.RealDictRow)."""
    pass


def _make_real_dict_cursor():
    from . import Cursor

    class _RealDictCursor(Cursor):
        as_dict = True

    return _RealDictCursor


class _RealDictCursorMeta(type):
    """RealDictCursor est à la fois un marqueur (cursor_factory=RealDictCursor)
    et une classe instanciable — résolue paresseusement pour éviter l'import
    circulaire avec le module racine."""

    _impl = None

    def _resolve(cls):
        if cls._impl is None:
            cls._impl = _make_real_dict_cursor()
        return cls._impl

    def __call__(cls, connection):
        return cls._resolve()(connection)

    def __instancecheck__(cls, instance):
        return isinstance(instance, cls._resolve())


class RealDictCursor(metaclass=_RealDictCursorMeta):
    pass


class DictCursor(RealDictCursor):
    pass
