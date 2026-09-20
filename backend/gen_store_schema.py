"""Generate migrations/002_app_store.sql from lib/store.py.

Run:  python gen_store_schema.py
The script is additive only: every statement is guarded by an existence check, creates
objects named Fno* (no pre-existing AngleTrending object shares that prefix), and never
emits ALTER/DROP/RENAME. Regenerate it whenever store.COLUMNS changes so the tables and
the adapter cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path

from lib.store import COLUMNS, INDEXES, UNIQUE, table_name

OUT = Path(__file__).resolve().parent.parent / "migrations" / "002_app_store.sql"

HEADER = """/* =====================================================================
   002_app_store.sql — QuantPulse F&O application store (ADDITIVE ONLY)
   ---------------------------------------------------------------------
   Run this once against your AngleTrending database to make the whole
   application run on SQL Server:

       sqlcmd -S PRAKASHPC\\SQLEXPRESS -d AngleTrending -E -i 002_app_store.sql
       -- or open it in SSMS (make sure AngleTrending is the active database)

   What it does
   ------------
   * Creates the Fno* tables the application needs, ONLY IF they do not exist.
   * Creates their indexes, ONLY IF they do not exist.
   * Touches NOTHING you already have: no ALTER, no DROP, no RENAME, no data change
     to any existing table, view or procedure. Re-running it is safe.

   Storage shape
   -------------
   Each table keeps the full document in `Doc` (JSON) plus typed, indexed columns for
   the fields the application filters and sorts on. After this script is applied, set
   DB_BACKEND=sqlserver in backend/.env and restart the backend — every signal, candle,
   option-chain snapshot, paper trade, backtest and setting is then read from and
   written to this database.

   GENERATED FILE — produced by backend/gen_store_schema.py. Edit the generator.
   ===================================================================== */

SET NOCOUNT ON;
GO
"""

FOOTER = """
/* --------------------------------------------------------------------
   Verification — should list every table created above.
   -------------------------------------------------------------------- */
SELECT t.name AS TableName, p.rows AS [Rows]
FROM sys.tables t
JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
WHERE t.schema_id = SCHEMA_ID('dbo') AND t.name LIKE 'Fno%'
ORDER BY t.name;
GO
"""


def table_ddl(collection: str) -> str:
    full = table_name(collection)
    short = full.split(".")[-1]
    cols = [f"    RowId       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_{short} PRIMARY KEY",
            "    DocId       NVARCHAR(128)  NULL"]
    width = max([len(c) for c in COLUMNS[collection]] + [11])
    for field, sqltype in COLUMNS[collection].items():
        cols.append(f"    [{field}]{' ' * (width - len(field))} {sqltype} NULL")
    cols.append("    Doc         NVARCHAR(MAX)  NOT NULL")
    cols.append(f"    , CreatedUtc DATETIME2(3) NOT NULL CONSTRAINT DF_{short}_CreatedUtc "
                "DEFAULT (SYSUTCDATETIME())")
    body = ",\n".join(cols[:-1]) + "\n" + cols[-1]
    out = [f"/* ---------- {short} ({collection}) ---------- */",
           f"IF OBJECT_ID('{full}', 'U') IS NULL",
           "BEGIN",
           f"    CREATE TABLE {full}",
           "    (",
           body,
           "    );",
           f"    PRINT 'created {full}';",
           "END",
           f"ELSE PRINT '{full} already exists — left untouched';",
           "GO"]
    return "\n".join(out)


def index_ddl(collection: str) -> list[str]:
    full = table_name(collection)
    short = full.split(".")[-1]
    stmts: list[str] = []

    def guard(name: str, statement: str) -> str:
        return "\n".join([
            f"IF NOT EXISTS (SELECT 1 FROM sys.indexes "
            f"WHERE name = '{name}' AND object_id = OBJECT_ID('{full}'))",
            f"    {statement}",
            "GO",
        ])

    key = UNIQUE.get(collection)
    if key:
        cols = ", ".join(f"[{c}]" for c in key)
        notnull = " AND ".join(f"[{c}] IS NOT NULL" for c in key)
        name = f"UX_{short}_{'_'.join(key)}"
        stmts.append(guard(name, f"CREATE UNIQUE INDEX {name} ON {full} ({cols}) "
                                 f"WHERE {notnull};"))
    else:
        name = f"UX_{short}_DocId"
        stmts.append(guard(name, f"CREATE UNIQUE INDEX {name} ON {full} (DocId) "
                                 "WHERE DocId IS NOT NULL;"))
    for spec in INDEXES.get(collection, []):
        name = f"IX_{short}_{'_'.join(spec)}"
        cols = ", ".join(f"[{c}]" for c in spec)
        stmts.append(guard(name, f"CREATE INDEX {name} ON {full} ({cols});"))
    return stmts


def main() -> None:
    parts = [HEADER]
    for collection in COLUMNS:
        parts.append(table_ddl(collection))
        parts.extend(index_ddl(collection))
    parts.append(FOOTER)
    OUT.write_text("\n\n".join(parts), encoding="utf-8")
    print(f"wrote {OUT} ({len(COLUMNS)} tables)")


if __name__ == "__main__":
    main()
