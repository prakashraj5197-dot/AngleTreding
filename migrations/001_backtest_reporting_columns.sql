/* ============================================================================
   AngleTrending - Migration 001 : backtest reporting columns + additive procs
   ----------------------------------------------------------------------------
   Reviewed-by : (you)  |  Run manually against the AngleTrending database.

   WHAT THIS DOES
     1. Adds NULLABLE columns to dbo.BacktestRuns and dbo.BacktestTrades so the
        application can PERSIST the full backtest report it already computes
        (gross vs net P&L, costs, profit factor, avg/largest win & loss, avg R,
        timeframe/symbol, equity curve, assumptions, and per-trade side /
        target2 / R multiple / dataset segment / market regime / charges).
     2. Creates NEW stored procedures (suffix _V2) that write those columns.

   WHAT THIS DOES NOT DO
     - No table is dropped, renamed or re-created.
     - No existing column is altered, renamed or removed.
     - No existing stored procedure is modified. The original
       usp_BacktestRuns_Create / usp_BacktestTrades_Insert /
       usp_BacktestRuns_Complete / usp_BacktestRuns_GetResults remain exactly
       as you created them and keep working unchanged.
     - Every statement is idempotent: re-running this script is safe.
   ============================================================================ */

SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

USE AngleTrending;
GO

PRINT '--- Migration 001 starting ---';
GO

/* ---------------------------------------------------------------------------
   1. dbo.BacktestRuns : additive nullable columns
   --------------------------------------------------------------------------- */
IF COL_LENGTH('dbo.BacktestRuns','UnderlyingSymbol') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD UnderlyingSymbol NVARCHAR(50) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','TimeFrame') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD TimeFrame NVARCHAR(20) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','RiskPerTradePct') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD RiskPerTradePct DECIMAL(9,4) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','GrossPnL') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD GrossPnL DECIMAL(18,4) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','TotalCosts') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD TotalCosts DECIMAL(18,4) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','ProfitFactor') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD ProfitFactor DECIMAL(18,6) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','AvgWin') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD AvgWin DECIMAL(18,4) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','AvgLoss') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD AvgLoss DECIMAL(18,4) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','LargestWin') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD LargestWin DECIMAL(18,4) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','LargestLoss') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD LargestLoss DECIMAL(18,4) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','AvgRMultiple') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD AvgRMultiple DECIMAL(18,6) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','MaxDrawdownPct') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD MaxDrawdownPct DECIMAL(18,6) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','EquityCurveJson') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD EquityCurveJson NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','MetricsJson') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD MetricsJson NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','AssumptionsJson') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD AssumptionsJson NVARCHAR(MAX) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','ErrorMessage') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD ErrorMessage NVARCHAR(2000) NULL;
GO
IF COL_LENGTH('dbo.BacktestRuns','RunKey') IS NULL
    ALTER TABLE dbo.BacktestRuns ADD RunKey NVARCHAR(50) NULL;
GO

/* RunKey lets the application address a run by its own GUID without depending
   on the IDENTITY value. Unique only where populated, so existing rows (NULL)
   are unaffected. */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UQ_BacktestRuns_RunKey')
    CREATE UNIQUE INDEX UQ_BacktestRuns_RunKey
        ON dbo.BacktestRuns(RunKey) WHERE RunKey IS NOT NULL;
GO

/* ---------------------------------------------------------------------------
   2. dbo.BacktestTrades : additive nullable columns
   --------------------------------------------------------------------------- */
IF COL_LENGTH('dbo.BacktestTrades','UnderlyingSymbol') IS NULL
    ALTER TABLE dbo.BacktestTrades ADD UnderlyingSymbol NVARCHAR(50) NULL;
GO
IF COL_LENGTH('dbo.BacktestTrades','TradingSymbol') IS NULL
    ALTER TABLE dbo.BacktestTrades ADD TradingSymbol NVARCHAR(100) NULL;
GO
IF COL_LENGTH('dbo.BacktestTrades','ExpiryDate') IS NULL
    ALTER TABLE dbo.BacktestTrades ADD ExpiryDate DATE NULL;
GO
IF COL_LENGTH('dbo.BacktestTrades','StrikePrice') IS NULL
    ALTER TABLE dbo.BacktestTrades ADD StrikePrice DECIMAL(18,4) NULL;
GO
IF COL_LENGTH('dbo.BacktestTrades','OptionType') IS NULL
    ALTER TABLE dbo.BacktestTrades ADD OptionType CHAR(2) NULL;
GO
IF COL_LENGTH('dbo.BacktestTrades','Target2Price') IS NULL
    ALTER TABLE dbo.BacktestTrades ADD Target2Price DECIMAL(18,4) NULL;
GO
IF COL_LENGTH('dbo.BacktestTrades','RMultiple') IS NULL
    ALTER TABLE dbo.BacktestTrades ADD RMultiple DECIMAL(18,6) NULL;
GO
IF COL_LENGTH('dbo.BacktestTrades','Segment') IS NULL
    ALTER TABLE dbo.BacktestTrades ADD Segment NVARCHAR(20) NULL;
GO
IF COL_LENGTH('dbo.BacktestTrades','MarketRegime') IS NULL
    ALTER TABLE dbo.BacktestTrades ADD MarketRegime NVARCHAR(30) NULL;
GO
IF COL_LENGTH('dbo.BacktestTrades','GrossPnL') IS NULL
    ALTER TABLE dbo.BacktestTrades ADD GrossPnL DECIMAL(18,4) NULL;
GO
IF COL_LENGTH('dbo.BacktestTrades','Charges') IS NULL
    ALTER TABLE dbo.BacktestTrades ADD Charges DECIMAL(18,4) NULL;
GO
IF COL_LENGTH('dbo.BacktestTrades','SignalScore') IS NULL
    ALTER TABLE dbo.BacktestTrades ADD SignalScore DECIMAL(10,4) NULL;
GO
IF COL_LENGTH('dbo.BacktestTrades','TradeNumber') IS NULL
    ALTER TABLE dbo.BacktestTrades ADD TradeNumber INT NULL;
GO

/* CE/PE guard for the new column only; existing rows are NULL and pass. */
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_BacktestTrades_OptionType')
    ALTER TABLE dbo.BacktestTrades WITH NOCHECK
        ADD CONSTRAINT CK_BacktestTrades_OptionType
        CHECK (OptionType IS NULL OR OptionType IN ('CE','PE'));
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_BacktestTrades_RunSegment')
    CREATE INDEX IX_BacktestTrades_RunSegment
        ON dbo.BacktestTrades(BacktestRunId, Segment) INCLUDE (PnL, RMultiple);
GO

/* ---------------------------------------------------------------------------
   3. NEW stored procedures (your originals are left untouched)
   --------------------------------------------------------------------------- */
CREATE OR ALTER PROCEDURE dbo.usp_BacktestRuns_CreateV2
    @RunKey NVARCHAR(50),
    @StrategyId INT = NULL,
    @StrategyVersion NVARCHAR(50) = NULL,
    @UnderlyingSymbol NVARCHAR(50) = NULL,
    @TimeFrame NVARCHAR(20) = NULL,
    @StartDate DATE,
    @EndDate DATE,
    @InitialCapital DECIMAL(18,4) = NULL,
    @RiskPerTradePct DECIMAL(9,4) = NULL,
    @AssumptionsJson NVARCHAR(MAX) = NULL,
    @Status NVARCHAR(30) = 'QUEUED'
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO dbo.BacktestRuns
        (StrategyId, StrategyVersion, UnderlyingSymbol, TimeFrame, StartDate, EndDate,
         InitialCapital, RiskPerTradePct, AssumptionsJson, Status, RunKey, CreatedAt)
    VALUES
        (@StrategyId, @StrategyVersion, @UnderlyingSymbol, @TimeFrame, @StartDate, @EndDate,
         @InitialCapital, @RiskPerTradePct, @AssumptionsJson, @Status, @RunKey, SYSUTCDATETIME());

    SELECT CAST(SCOPE_IDENTITY() AS BIGINT) AS BacktestRunId;
END;
GO

CREATE OR ALTER PROCEDURE dbo.usp_BacktestRuns_SetStatus
    @BacktestRunId BIGINT,
    @Status NVARCHAR(30),
    @ErrorMessage NVARCHAR(2000) = NULL
AS
BEGIN
    SET NOCOUNT ON;

    UPDATE dbo.BacktestRuns
       SET Status = @Status,
           ErrorMessage = @ErrorMessage,
           CompletedAt = CASE WHEN @Status IN ('COMPLETED','FAILED')
                              THEN SYSUTCDATETIME() ELSE CompletedAt END
     WHERE BacktestRunId = @BacktestRunId;
END;
GO

CREATE OR ALTER PROCEDURE dbo.usp_BacktestRuns_CompleteV2
    @BacktestRunId BIGINT,
    @TotalTrades INT,
    @WinningTrades INT,
    @LosingTrades INT,
    @WinRate DECIMAL(9,4) = NULL,
    @GrossPnL DECIMAL(18,4) = NULL,
    @TotalCosts DECIMAL(18,4) = NULL,
    @NetPnL DECIMAL(18,4) = NULL,
    @ProfitFactor DECIMAL(18,6) = NULL,
    @AvgWin DECIMAL(18,4) = NULL,
    @AvgLoss DECIMAL(18,4) = NULL,
    @LargestWin DECIMAL(18,4) = NULL,
    @LargestLoss DECIMAL(18,4) = NULL,
    @AvgRMultiple DECIMAL(18,6) = NULL,
    @MaxDrawdown DECIMAL(18,4) = NULL,
    @MaxDrawdownPct DECIMAL(18,6) = NULL,
    @EquityCurveJson NVARCHAR(MAX) = NULL,
    @MetricsJson NVARCHAR(MAX) = NULL,
    @Status NVARCHAR(30) = 'COMPLETED'
AS
BEGIN
    SET NOCOUNT ON;

    UPDATE dbo.BacktestRuns
       SET TotalTrades = @TotalTrades,
           WinningTrades = @WinningTrades,
           LosingTrades = @LosingTrades,
           WinRate = @WinRate,
           GrossPnL = @GrossPnL,
           TotalCosts = @TotalCosts,
           NetPnL = @NetPnL,
           ProfitFactor = @ProfitFactor,
           AvgWin = @AvgWin,
           AvgLoss = @AvgLoss,
           LargestWin = @LargestWin,
           LargestLoss = @LargestLoss,
           AvgRMultiple = @AvgRMultiple,
           MaxDrawdown = @MaxDrawdown,
           MaxDrawdownPct = @MaxDrawdownPct,
           EquityCurveJson = @EquityCurveJson,
           MetricsJson = @MetricsJson,
           Status = @Status,
           CompletedAt = SYSUTCDATETIME()
     WHERE BacktestRunId = @BacktestRunId;
END;
GO

CREATE OR ALTER PROCEDURE dbo.usp_BacktestTrades_InsertV2
    @BacktestRunId BIGINT,
    @TradeNumber INT = NULL,
    @InstrumentId BIGINT = NULL,
    @UnderlyingSymbol NVARCHAR(50) = NULL,
    @TradingSymbol NVARCHAR(100) = NULL,
    @ExpiryDate DATE = NULL,
    @StrikePrice DECIMAL(18,4) = NULL,
    @OptionType CHAR(2) = NULL,
    @EntryTime DATETIME2(3),
    @ExitTime DATETIME2(3) = NULL,
    @EntryPrice DECIMAL(18,4),
    @ExitPrice DECIMAL(18,4) = NULL,
    @Quantity INT = NULL,
    @StopLossPrice DECIMAL(18,4) = NULL,
    @TargetPrice DECIMAL(18,4) = NULL,
    @Target2Price DECIMAL(18,4) = NULL,
    @GrossPnL DECIMAL(18,4) = NULL,
    @Charges DECIMAL(18,4) = NULL,
    @PnL DECIMAL(18,4) = NULL,
    @RMultiple DECIMAL(18,6) = NULL,
    @SignalScore DECIMAL(10,4) = NULL,
    @Segment NVARCHAR(20) = NULL,
    @MarketRegime NVARCHAR(30) = NULL,
    @ExitReason NVARCHAR(500) = NULL
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO dbo.BacktestTrades
        (BacktestRunId, TradeNumber, InstrumentId, UnderlyingSymbol, TradingSymbol,
         ExpiryDate, StrikePrice, OptionType, EntryTime, ExitTime, EntryPrice, ExitPrice,
         Quantity, StopLossPrice, TargetPrice, Target2Price, GrossPnL, Charges, PnL,
         RMultiple, SignalScore, Segment, MarketRegime, ExitReason)
    VALUES
        (@BacktestRunId, @TradeNumber, @InstrumentId, @UnderlyingSymbol, @TradingSymbol,
         @ExpiryDate, @StrikePrice, @OptionType, @EntryTime, @ExitTime, @EntryPrice, @ExitPrice,
         @Quantity, @StopLossPrice, @TargetPrice, @Target2Price, @GrossPnL, @Charges, @PnL,
         @RMultiple, @SignalScore, @Segment, @MarketRegime, @ExitReason);
END;
GO

CREATE OR ALTER PROCEDURE dbo.usp_BacktestRuns_GetList
    @Top INT = 20
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@Top) *
    FROM dbo.BacktestRuns
    ORDER BY BacktestRunId DESC;
END;
GO

CREATE OR ALTER PROCEDURE dbo.usp_BacktestTrades_GetByRun
    @BacktestRunId BIGINT,
    @Top INT = 1000
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@Top) *
    FROM dbo.BacktestTrades
    WHERE BacktestRunId = @BacktestRunId
    ORDER BY COALESCE(TradeNumber, 0), BacktestTradeId;
END;
GO

PRINT '--- Migration 001 complete: 17 columns on BacktestRuns, 13 on BacktestTrades, 6 new procedures. No existing object was dropped, renamed or modified. ---';
GO
