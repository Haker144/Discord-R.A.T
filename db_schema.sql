-- SQLite schema for Discord RAT logging
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    command TEXT NOT NULL,
    output TEXT,
    success INTEGER NOT NULL
);
