-- Stock Insights server 1.1 schema migration: trade tags, trade uids,
-- wider password hashes, missing indexes.
--
-- Safe to run any number of times: every step is guarded and nothing is
-- dropped or shrunk. server.py runs these same batches at start-up; run this
-- file by hand only when the server's SQL login lacks ALTER rights (the
-- server log then says so and /health reports "schema": "needs_migration").
--
-- Run as a database owner, against the app's database:
--   SSMS:    open this file, pick the StockInsights database, Execute (F5)
--   sqlcmd:  sqlcmd -S localhost\STOCKINSIGHTS -d StockInsights -E -b -I -i 001_tags_trade_uid.sql
--            (-b stops on the first error, -I turns QUOTED_IDENTIFIER on,
--             -E = Windows login; use -U/-P for a SQL login)
-- No USE statement on purpose: the database is whatever you connected to.
--
-- Each batch (between GO lines) is executed separately by server.py too, so
-- keep every batch self-contained and guarded.

-- Filtered indexes need these session options (sqlcmd defaults
-- QUOTED_IDENTIFIER to OFF).
SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET ARITHABORT ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET NUMERIC_ROUNDABORT OFF;
GO

-- 1. dbo.trades.tag: free-text label, '' when unset.
IF COL_LENGTH('dbo.trades', 'tag') IS NULL
    ALTER TABLE dbo.trades
        ADD tag NVARCHAR(40) NOT NULL CONSTRAINT DF_trades_tag DEFAULT N'';
GO

-- 2. dbo.trades.client_id: the client-generated trade uid (uuid4 hex).
IF COL_LENGTH('dbo.trades', 'client_id') IS NULL
    ALTER TABLE dbo.trades ADD client_id NVARCHAR(36) NULL;
GO

-- 3. Backfill a uid for every existing trade. Dynamic SQL so the batch still
--    compiles if step 2 failed (the column would not exist yet).
IF COL_LENGTH('dbo.trades', 'client_id') IS NOT NULL
    EXEC(N'UPDATE dbo.trades
           SET client_id = LOWER(REPLACE(CONVERT(NVARCHAR(36), NEWID()), ''-'', ''''))
           WHERE client_id IS NULL;');
GO

-- 4. uids are unique; rows without one (written by an old server) are allowed.
IF COL_LENGTH('dbo.trades', 'client_id') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.indexes
                   WHERE object_id = OBJECT_ID('dbo.trades') AND name = 'UX_trades_client_id')
    EXEC(N'CREATE UNIQUE INDEX UX_trades_client_id ON dbo.trades (client_id)
           WHERE client_id IS NOT NULL;');
GO

-- 5. Widen dbo.users.password_hash to NVARCHAR(255) if it is narrower
--    (scrypt hashes are ~111 chars). Nullability is kept as it is.
--    CHARACTER_MAXIMUM_LENGTH is -1 for (N)VARCHAR(MAX), which is left alone.
DECLARE @len INT, @nullable VARCHAR(3), @sql NVARCHAR(200);
SELECT @len = CHARACTER_MAXIMUM_LENGTH, @nullable = IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'users' AND COLUMN_NAME = 'password_hash';
IF @len IS NOT NULL AND @len <> -1 AND @len < 255
BEGIN
    SET @sql = N'ALTER TABLE dbo.users ALTER COLUMN password_hash NVARCHAR(255) '
               + CASE WHEN @nullable = 'YES' THEN N'NULL;' ELSE N'NOT NULL;' END;
    EXEC sp_executesql @sql;
END
GO

-- 6. Indexes for the hot lookups, only when no index already starts with
--    that column (avoids duplicating one created by init_stockinsights.sql).
IF NOT EXISTS (SELECT 1 FROM sys.index_columns ic
               JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
               WHERE ic.object_id = OBJECT_ID('dbo.trades')
                 AND ic.key_ordinal = 1 AND c.name = 'account_id')
    CREATE INDEX IX_trades_account_id ON dbo.trades (account_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.index_columns ic
               JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
               WHERE ic.object_id = OBJECT_ID('dbo.sessions')
                 AND ic.key_ordinal = 1 AND c.name = 'user_id')
    CREATE INDEX IX_sessions_user_id ON dbo.sessions (user_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.index_columns ic
               JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
               WHERE ic.object_id = OBJECT_ID('dbo.sessions')
                 AND ic.key_ordinal = 1 AND c.name = 'expires_at')
    CREATE INDEX IX_sessions_expires_at ON dbo.sessions (expires_at);
GO
