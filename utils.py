import sqlite3


def conn_db() -> sqlite3.Connection:
    return sqlite3.connect("data.db")
