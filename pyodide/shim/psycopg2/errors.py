"""Hiérarchie d'exceptions psycopg2 (sous-ensemble utilisé par emusf)."""


class Warning(Exception):
    pass


class Error(Exception):
    pass


class InterfaceError(Error):
    pass


class DatabaseError(Error):
    pass


class DataError(DatabaseError):
    pass


class OperationalError(DatabaseError):
    pass


class IntegrityError(DatabaseError):
    pass


class InternalError(DatabaseError):
    pass


class ProgrammingError(DatabaseError):
    pass


class NotSupportedError(DatabaseError):
    pass


class UndefinedTable(ProgrammingError):
    pass


class UndefinedColumn(ProgrammingError):
    pass


class DuplicateColumn(ProgrammingError):
    pass


class DuplicateTable(ProgrammingError):
    pass


class UniqueViolation(IntegrityError):
    pass


class ForeignKeyViolation(IntegrityError):
    pass


class NotNullViolation(IntegrityError):
    pass


class InvalidTextRepresentation(DataError):
    pass
