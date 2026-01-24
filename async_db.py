# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/async_db.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

"""
Database abstraction layer for MediaCrawler
Provides unified interface for MySQL and SQLite operations
"""

import asyncio
from typing import Dict, List, Union, Any
from var import db_conn_pool_var
import aiosqlite


class AsyncMysqlDB:
    """
    MySQL database abstraction class
    Uses aiomysql connection pool for database operations
    """

    def __init__(self):
        self._pool = None

    async def _ensure_pool(self):
        """Ensure connection pool is initialized"""
        if self._pool is None:
            self._pool = db_conn_pool_var.get()
        if self._pool is None:
            raise RuntimeError("MySQL connection pool not initialized")

    async def query(self, sql: str, params: tuple = None) -> List[Dict]:
        """
        Execute SELECT query

        Args:
            sql: SQL query string
            params: Query parameters

        Returns:
            List of result dictionaries
        """
        await self._ensure_pool()

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, params or ())
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                rows = await cursor.fetchall()
                return [dict(zip(columns, row)) for row in rows]

    async def execute(self, sql: str, *params):
        """
        Execute SQL statement (for compatibility with chat modules)

        Args:
            sql: SQL query string
            *params: Query parameters
        """
        await self._ensure_pool()

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, params)
                await conn.commit()

    async def item_to_table(self, table_name: str, item: Dict) -> int:
        """
        Insert item into table

        Args:
            table_name: Target table name
            item: Data to insert

        Returns:
            Last inserted row ID
        """
        await self._ensure_pool()

        columns = ', '.join(item.keys())
        placeholders = ', '.join(['%s'] * len(item))
        values = tuple(item.values())

        sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, values)
                await conn.commit()
                return cursor.lastrowid

    async def update_table(self, table_name: str, item: Dict, id_field: str, id_value: str) -> int:
        """
        Update table row

        Args:
            table_name: Target table name
            item: Data to update
            id_field: ID field name
            id_value: ID field value

        Returns:
            Number of affected rows
        """
        await self._ensure_pool()

        set_clause = ', '.join([f"{k} = %s" for k in item.keys()])
        values = tuple(item.values()) + (id_value,)

        sql = f"UPDATE {table_name} SET {set_clause} WHERE {id_field} = %s"

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, values)
                await conn.commit()
                return cursor.rowcount


class AsyncSqliteDB:
    """
    SQLite database abstraction class
    Uses aiosqlite for database operations
    """

    def __init__(self, db_path: str = None):
        """
        Initialize SQLite database

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path

    async def query(self, sql: str, params: tuple = None) -> List[Dict]:
        """
        Execute SELECT query

        Args:
            sql: SQL query string
            params: Query parameters

        Returns:
            List of result dictionaries
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params or ()) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def item_to_table(self, table_name: str, item: Dict) -> int:
        """
        Insert item into table

        Args:
            table_name: Target table name
            item: Data to insert

        Returns:
            Last inserted row ID
        """
        async with aiosqlite.connect(self.db_path) as db:
            columns = ', '.join(item.keys())
            placeholders = ', '.join(['?'] * len(item))
            values = tuple(item.values())

            sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"

            async with db.execute(sql, values) as cursor:
                await db.commit()
                return cursor.lastrowid

    async def update_table(self, table_name: str, item: Dict, id_field: str, id_value: str) -> int:
        """
        Update table row

        Args:
            table_name: Target table name
            item: Data to update
            id_field: ID field name
            id_value: ID field value

        Returns:
            Number of affected rows
        """
        async with aiosqlite.connect(self.db_path) as db:
            set_clause = ', '.join([f"{k} = ?" for k in item.keys()])
            values = tuple(item.values()) + (id_value,)

            sql = f"UPDATE {table_name} SET {set_clause} WHERE {id_field} = ?"

            async with db.execute(sql, values) as cursor:
                await db.commit()
                return cursor.rowcount
