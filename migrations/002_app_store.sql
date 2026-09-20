/* =====================================================================
   002_app_store.sql — QuantPulse F&O application store (ADDITIVE ONLY)
   ---------------------------------------------------------------------
   Run this once against your AngleTrending database to make the whole
   application run on SQL Server:

       sqlcmd -S PRAKASHPC\SQLEXPRESS -d AngleTrending -E -i 002_app_store.sql
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


/* ---------- FnoSettings (settings) ---------- */
IF OBJECT_ID('dbo.FnoSettings', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.FnoSettings
    (
    RowId       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_FnoSettings PRIMARY KEY,
    DocId       NVARCHAR(128)  NULL,
    Doc         NVARCHAR(MAX)  NOT NULL
    , CreatedUtc DATETIME2(3) NOT NULL CONSTRAINT DF_FnoSettings_CreatedUtc DEFAULT (SYSUTCDATETIME())
    );
    PRINT 'created dbo.FnoSettings';
END
ELSE PRINT 'dbo.FnoSettings already exists — left untouched';
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_FnoSettings_DocId' AND object_id = OBJECT_ID('dbo.FnoSettings'))
    CREATE UNIQUE INDEX UX_FnoSettings_DocId ON dbo.FnoSettings (DocId) WHERE DocId IS NOT NULL;
GO

/* ---------- FnoPaperAccount (paper_account) ---------- */
IF OBJECT_ID('dbo.FnoPaperAccount', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.FnoPaperAccount
    (
    RowId       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_FnoPaperAccount PRIMARY KEY,
    DocId       NVARCHAR(128)  NULL,
    Doc         NVARCHAR(MAX)  NOT NULL
    , CreatedUtc DATETIME2(3) NOT NULL CONSTRAINT DF_FnoPaperAccount_CreatedUtc DEFAULT (SYSUTCDATETIME())
    );
    PRINT 'created dbo.FnoPaperAccount';
END
ELSE PRINT 'dbo.FnoPaperAccount already exists — left untouched';
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_FnoPaperAccount_DocId' AND object_id = OBJECT_ID('dbo.FnoPaperAccount'))
    CREATE UNIQUE INDEX UX_FnoPaperAccount_DocId ON dbo.FnoPaperAccount (DocId) WHERE DocId IS NOT NULL;
GO

/* ---------- FnoCandles (candles) ---------- */
IF OBJECT_ID('dbo.FnoCandles', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.FnoCandles
    (
    RowId       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_FnoCandles PRIMARY KEY,
    DocId       NVARCHAR(128)  NULL,
    [symbol]      NVARCHAR(128) NULL,
    [timeframe]   NVARCHAR(128) NULL,
    [ts]          DATETIME2(3) NULL,
    Doc         NVARCHAR(MAX)  NOT NULL
    , CreatedUtc DATETIME2(3) NOT NULL CONSTRAINT DF_FnoCandles_CreatedUtc DEFAULT (SYSUTCDATETIME())
    );
    PRINT 'created dbo.FnoCandles';
END
ELSE PRINT 'dbo.FnoCandles already exists — left untouched';
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_FnoCandles_symbol_timeframe_ts' AND object_id = OBJECT_ID('dbo.FnoCandles'))
    CREATE UNIQUE INDEX UX_FnoCandles_symbol_timeframe_ts ON dbo.FnoCandles ([symbol], [timeframe], [ts]) WHERE [symbol] IS NOT NULL AND [timeframe] IS NOT NULL AND [ts] IS NOT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_FnoCandles_symbol_timeframe_ts' AND object_id = OBJECT_ID('dbo.FnoCandles'))
    CREATE INDEX IX_FnoCandles_symbol_timeframe_ts ON dbo.FnoCandles ([symbol], [timeframe], [ts]);
GO

/* ---------- FnoSignals (signals) ---------- */
IF OBJECT_ID('dbo.FnoSignals', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.FnoSignals
    (
    RowId       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_FnoSignals PRIMARY KEY,
    DocId       NVARCHAR(128)  NULL,
    [id]               NVARCHAR(128) NULL,
    [status]           NVARCHAR(128) NULL,
    [symbol]           NVARCHAR(128) NULL,
    [day_ist]          NVARCHAR(128) NULL,
    [strategy_name]    NVARCHAR(400) NULL,
    [strategy_version] NVARCHAR(128) NULL,
    [result]           NVARCHAR(128) NULL,
    [option_type]      NVARCHAR(128) NULL,
    [direction]        NVARCHAR(128) NULL,
    [score]            FLOAT NULL,
    [created_at]       DATETIME2(3) NULL,
    [exit_time]        DATETIME2(3) NULL,
    [paper_executed]   BIT NULL,
    Doc         NVARCHAR(MAX)  NOT NULL
    , CreatedUtc DATETIME2(3) NOT NULL CONSTRAINT DF_FnoSignals_CreatedUtc DEFAULT (SYSUTCDATETIME())
    );
    PRINT 'created dbo.FnoSignals';
END
ELSE PRINT 'dbo.FnoSignals already exists — left untouched';
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_FnoSignals_id' AND object_id = OBJECT_ID('dbo.FnoSignals'))
    CREATE UNIQUE INDEX UX_FnoSignals_id ON dbo.FnoSignals ([id]) WHERE [id] IS NOT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_FnoSignals_created_at' AND object_id = OBJECT_ID('dbo.FnoSignals'))
    CREATE INDEX IX_FnoSignals_created_at ON dbo.FnoSignals ([created_at]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_FnoSignals_status_created_at' AND object_id = OBJECT_ID('dbo.FnoSignals'))
    CREATE INDEX IX_FnoSignals_status_created_at ON dbo.FnoSignals ([status], [created_at]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_FnoSignals_day_ist_symbol' AND object_id = OBJECT_ID('dbo.FnoSignals'))
    CREATE INDEX IX_FnoSignals_day_ist_symbol ON dbo.FnoSignals ([day_ist], [symbol]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_FnoSignals_symbol_strategy_name_status' AND object_id = OBJECT_ID('dbo.FnoSignals'))
    CREATE INDEX IX_FnoSignals_symbol_strategy_name_status ON dbo.FnoSignals ([symbol], [strategy_name], [status]);
GO

/* ---------- FnoEngineState (engine_state) ---------- */
IF OBJECT_ID('dbo.FnoEngineState', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.FnoEngineState
    (
    RowId       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_FnoEngineState PRIMARY KEY,
    DocId       NVARCHAR(128)  NULL,
    [symbol]      NVARCHAR(128) NULL,
    Doc         NVARCHAR(MAX)  NOT NULL
    , CreatedUtc DATETIME2(3) NOT NULL CONSTRAINT DF_FnoEngineState_CreatedUtc DEFAULT (SYSUTCDATETIME())
    );
    PRINT 'created dbo.FnoEngineState';
END
ELSE PRINT 'dbo.FnoEngineState already exists — left untouched';
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_FnoEngineState_symbol' AND object_id = OBJECT_ID('dbo.FnoEngineState'))
    CREATE UNIQUE INDEX UX_FnoEngineState_symbol ON dbo.FnoEngineState ([symbol]) WHERE [symbol] IS NOT NULL;
GO

/* ---------- FnoSimState (sim_state) ---------- */
IF OBJECT_ID('dbo.FnoSimState', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.FnoSimState
    (
    RowId       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_FnoSimState PRIMARY KEY,
    DocId       NVARCHAR(128)  NULL,
    [symbol]      NVARCHAR(128) NULL,
    Doc         NVARCHAR(MAX)  NOT NULL
    , CreatedUtc DATETIME2(3) NOT NULL CONSTRAINT DF_FnoSimState_CreatedUtc DEFAULT (SYSUTCDATETIME())
    );
    PRINT 'created dbo.FnoSimState';
END
ELSE PRINT 'dbo.FnoSimState already exists — left untouched';
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_FnoSimState_symbol' AND object_id = OBJECT_ID('dbo.FnoSimState'))
    CREATE UNIQUE INDEX UX_FnoSimState_symbol ON dbo.FnoSimState ([symbol]) WHERE [symbol] IS NOT NULL;
GO

/* ---------- FnoOptionChainSnapshots (option_chain_snapshots) ---------- */
IF OBJECT_ID('dbo.FnoOptionChainSnapshots', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.FnoOptionChainSnapshots
    (
    RowId       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_FnoOptionChainSnapshots PRIMARY KEY,
    DocId       NVARCHAR(128)  NULL,
    [underlying]  NVARCHAR(128) NULL,
    [expiry]      NVARCHAR(128) NULL,
    [ts]          DATETIME2(3) NULL,
    Doc         NVARCHAR(MAX)  NOT NULL
    , CreatedUtc DATETIME2(3) NOT NULL CONSTRAINT DF_FnoOptionChainSnapshots_CreatedUtc DEFAULT (SYSUTCDATETIME())
    );
    PRINT 'created dbo.FnoOptionChainSnapshots';
END
ELSE PRINT 'dbo.FnoOptionChainSnapshots already exists — left untouched';
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_FnoOptionChainSnapshots_DocId' AND object_id = OBJECT_ID('dbo.FnoOptionChainSnapshots'))
    CREATE UNIQUE INDEX UX_FnoOptionChainSnapshots_DocId ON dbo.FnoOptionChainSnapshots (DocId) WHERE DocId IS NOT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_FnoOptionChainSnapshots_underlying_ts' AND object_id = OBJECT_ID('dbo.FnoOptionChainSnapshots'))
    CREATE INDEX IX_FnoOptionChainSnapshots_underlying_ts ON dbo.FnoOptionChainSnapshots ([underlying], [ts]);
GO

/* ---------- FnoNotifications (notifications) ---------- */
IF OBJECT_ID('dbo.FnoNotifications', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.FnoNotifications
    (
    RowId       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_FnoNotifications PRIMARY KEY,
    DocId       NVARCHAR(128)  NULL,
    [signal_id]   NVARCHAR(128) NULL,
    [type]        NVARCHAR(128) NULL,
    [read]        BIT NULL,
    [ts]          DATETIME2(3) NULL,
    Doc         NVARCHAR(MAX)  NOT NULL
    , CreatedUtc DATETIME2(3) NOT NULL CONSTRAINT DF_FnoNotifications_CreatedUtc DEFAULT (SYSUTCDATETIME())
    );
    PRINT 'created dbo.FnoNotifications';
END
ELSE PRINT 'dbo.FnoNotifications already exists — left untouched';
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_FnoNotifications_DocId' AND object_id = OBJECT_ID('dbo.FnoNotifications'))
    CREATE UNIQUE INDEX UX_FnoNotifications_DocId ON dbo.FnoNotifications (DocId) WHERE DocId IS NOT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_FnoNotifications_ts' AND object_id = OBJECT_ID('dbo.FnoNotifications'))
    CREATE INDEX IX_FnoNotifications_ts ON dbo.FnoNotifications ([ts]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_FnoNotifications_read_ts' AND object_id = OBJECT_ID('dbo.FnoNotifications'))
    CREATE INDEX IX_FnoNotifications_read_ts ON dbo.FnoNotifications ([read], [ts]);
GO

/* ---------- FnoPaperPositions (paper_positions) ---------- */
IF OBJECT_ID('dbo.FnoPaperPositions', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.FnoPaperPositions
    (
    RowId       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_FnoPaperPositions PRIMARY KEY,
    DocId       NVARCHAR(128)  NULL,
    [id]          NVARCHAR(128) NULL,
    [signal_id]   NVARCHAR(128) NULL,
    [symbol]      NVARCHAR(128) NULL,
    [status]      NVARCHAR(128) NULL,
    [entry_time]  DATETIME2(3) NULL,
    [exit_time]   DATETIME2(3) NULL,
    Doc         NVARCHAR(MAX)  NOT NULL
    , CreatedUtc DATETIME2(3) NOT NULL CONSTRAINT DF_FnoPaperPositions_CreatedUtc DEFAULT (SYSUTCDATETIME())
    );
    PRINT 'created dbo.FnoPaperPositions';
END
ELSE PRINT 'dbo.FnoPaperPositions already exists — left untouched';
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_FnoPaperPositions_id' AND object_id = OBJECT_ID('dbo.FnoPaperPositions'))
    CREATE UNIQUE INDEX UX_FnoPaperPositions_id ON dbo.FnoPaperPositions ([id]) WHERE [id] IS NOT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_FnoPaperPositions_status_entry_time' AND object_id = OBJECT_ID('dbo.FnoPaperPositions'))
    CREATE INDEX IX_FnoPaperPositions_status_entry_time ON dbo.FnoPaperPositions ([status], [entry_time]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_FnoPaperPositions_status_exit_time' AND object_id = OBJECT_ID('dbo.FnoPaperPositions'))
    CREATE INDEX IX_FnoPaperPositions_status_exit_time ON dbo.FnoPaperPositions ([status], [exit_time]);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_FnoPaperPositions_signal_id' AND object_id = OBJECT_ID('dbo.FnoPaperPositions'))
    CREATE INDEX IX_FnoPaperPositions_signal_id ON dbo.FnoPaperPositions ([signal_id]);
GO

/* ---------- FnoBacktestJobs (backtest_jobs) ---------- */
IF OBJECT_ID('dbo.FnoBacktestJobs', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.FnoBacktestJobs
    (
    RowId       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_FnoBacktestJobs PRIMARY KEY,
    DocId       NVARCHAR(128)  NULL,
    [id]          NVARCHAR(128) NULL,
    [symbol]      NVARCHAR(128) NULL,
    [status]      NVARCHAR(128) NULL,
    [created_at]  DATETIME2(3) NULL,
    Doc         NVARCHAR(MAX)  NOT NULL
    , CreatedUtc DATETIME2(3) NOT NULL CONSTRAINT DF_FnoBacktestJobs_CreatedUtc DEFAULT (SYSUTCDATETIME())
    );
    PRINT 'created dbo.FnoBacktestJobs';
END
ELSE PRINT 'dbo.FnoBacktestJobs already exists — left untouched';
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_FnoBacktestJobs_id' AND object_id = OBJECT_ID('dbo.FnoBacktestJobs'))
    CREATE UNIQUE INDEX UX_FnoBacktestJobs_id ON dbo.FnoBacktestJobs ([id]) WHERE [id] IS NOT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_FnoBacktestJobs_created_at' AND object_id = OBJECT_ID('dbo.FnoBacktestJobs'))
    CREATE INDEX IX_FnoBacktestJobs_created_at ON dbo.FnoBacktestJobs ([created_at]);
GO

/* ---------- FnoBacktestTrades (backtest_trades) ---------- */
IF OBJECT_ID('dbo.FnoBacktestTrades', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.FnoBacktestTrades
    (
    RowId       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_FnoBacktestTrades PRIMARY KEY,
    DocId       NVARCHAR(128)  NULL,
    [job_id]      NVARCHAR(128) NULL,
    [n]           INT NULL,
    [segment]     NVARCHAR(128) NULL,
    [result]      NVARCHAR(128) NULL,
    Doc         NVARCHAR(MAX)  NOT NULL
    , CreatedUtc DATETIME2(3) NOT NULL CONSTRAINT DF_FnoBacktestTrades_CreatedUtc DEFAULT (SYSUTCDATETIME())
    );
    PRINT 'created dbo.FnoBacktestTrades';
END
ELSE PRINT 'dbo.FnoBacktestTrades already exists — left untouched';
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_FnoBacktestTrades_DocId' AND object_id = OBJECT_ID('dbo.FnoBacktestTrades'))
    CREATE UNIQUE INDEX UX_FnoBacktestTrades_DocId ON dbo.FnoBacktestTrades (DocId) WHERE DocId IS NOT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_FnoBacktestTrades_job_id_n' AND object_id = OBJECT_ID('dbo.FnoBacktestTrades'))
    CREATE INDEX IX_FnoBacktestTrades_job_id_n ON dbo.FnoBacktestTrades ([job_id], [n]);
GO

/* ---------- FnoSessions (sessions) ---------- */
IF OBJECT_ID('dbo.FnoSessions', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.FnoSessions
    (
    RowId       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_FnoSessions PRIMARY KEY,
    DocId       NVARCHAR(128)  NULL,
    [token]       NVARCHAR(400) NULL,
    [email]       NVARCHAR(400) NULL,
    [expires_at]  DATETIME2(3) NULL,
    Doc         NVARCHAR(MAX)  NOT NULL
    , CreatedUtc DATETIME2(3) NOT NULL CONSTRAINT DF_FnoSessions_CreatedUtc DEFAULT (SYSUTCDATETIME())
    );
    PRINT 'created dbo.FnoSessions';
END
ELSE PRINT 'dbo.FnoSessions already exists — left untouched';
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_FnoSessions_token' AND object_id = OBJECT_ID('dbo.FnoSessions'))
    CREATE UNIQUE INDEX UX_FnoSessions_token ON dbo.FnoSessions ([token]) WHERE [token] IS NOT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_FnoSessions_expires_at' AND object_id = OBJECT_ID('dbo.FnoSessions'))
    CREATE INDEX IX_FnoSessions_expires_at ON dbo.FnoSessions ([expires_at]);
GO


/* --------------------------------------------------------------------
   Verification — should list every table created above.
   -------------------------------------------------------------------- */
SELECT t.name AS TableName, p.rows AS [Rows]
FROM sys.tables t
JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
WHERE t.schema_id = SCHEMA_ID('dbo') AND t.name LIKE 'Fno%'
ORDER BY t.name;
GO
