"""Модульные тесты утилит метаданных БД: доступ к MetaData, перечню таблиц,
соглашению об именовании и сводке по схеме."""
from __future__ import annotations

import pytest

from database.metadata import (
    get_metadata,
    get_metadata_summary,
    get_naming_convention,
    get_table,
    get_table_names,
    get_tables,
    has_table,
    require_tables,
)


class TestGetMetadata:
    def test_returns_metadata_object(self) -> None:
        from sqlalchemy import MetaData
        result = get_metadata()
        assert isinstance(result, MetaData)

    def test_returns_same_instance_on_multiple_calls(self) -> None:
        m1 = get_metadata()
        m2 = get_metadata()
        assert m1 is m2


class TestGetNamingConvention:
    def test_returns_dict(self) -> None:
        result = get_naming_convention()
        assert isinstance(result, dict)

    def test_contains_naming_keys(self) -> None:
        result = get_naming_convention()
        # Должны присутствовать ключи для ограничений/индексов
        assert len(result) > 0

    def test_returns_copy_not_original(self) -> None:
        r1 = get_naming_convention()
        r2 = get_naming_convention()
        assert r1 is not r2
        assert r1 == r2


class TestGetTableNames:
    def test_returns_list_of_strings(self) -> None:
        names = get_table_names()
        assert isinstance(names, list)
        assert all(isinstance(n, str) for n in names)

    def test_sorted_by_default(self) -> None:
        names = get_table_names(sorted_=True)
        assert names == sorted(names)

    def test_non_sorted_also_possible(self) -> None:
        names = get_table_names(sorted_=False)
        assert isinstance(names, list)

    def test_contains_known_tables(self) -> None:
        names = get_table_names()
        assert "users" in names
        assert "refresh_tokens" in names
        assert "file_system_nodes" in names

    def test_not_empty(self) -> None:
        names = get_table_names()
        assert len(names) > 0


class TestGetTables:
    def test_returns_list(self) -> None:
        from sqlalchemy import Table
        tables = get_tables()
        assert isinstance(tables, list)
        assert all(isinstance(t, Table) for t in tables)

    def test_sorted_tables_exist(self) -> None:
        tables_sorted = get_tables(sorted_=True)
        tables_unsorted = get_tables(sorted_=False)
        assert len(tables_sorted) == len(tables_unsorted)


class TestGetTable:
    def test_returns_table_for_known_name(self) -> None:
        from sqlalchemy import Table
        table = get_table("users")
        assert isinstance(table, Table)
        assert table.name == "users"

    def test_raises_key_error_for_unknown_table(self) -> None:
        with pytest.raises(KeyError):
            get_table("nonexistent_table_xyz")


class TestHasTable:
    def test_true_for_known_table(self) -> None:
        assert has_table("users") is True
        assert has_table("refresh_tokens") is True

    def test_false_for_unknown_table(self) -> None:
        assert has_table("nonexistent_table_xyz") is False


class TestRequireTables:
    def test_passes_for_existing_tables(self) -> None:
        require_tables(["users", "refresh_tokens"])  # без исключения

    def test_raises_runtime_error_for_missing_table(self) -> None:
        with pytest.raises(RuntimeError, match="отсутствуют обязательные таблицы"):
            require_tables(["nonexistent_xyz"])

    def test_raises_with_multiple_missing_tables(self) -> None:
        with pytest.raises(RuntimeError):
            require_tables(["missing_a", "missing_b"])

    def test_empty_list_passes(self) -> None:
        require_tables([])  # без исключения


class TestGetMetadataSummary:
    def test_returns_dict_with_required_keys(self) -> None:
        summary = get_metadata_summary()
        assert "tables_count" in summary
        assert "tables" in summary
        assert "naming_convention" in summary

    def test_tables_count_matches_tables_list(self) -> None:
        summary = get_metadata_summary()
        assert summary["tables_count"] == len(summary["tables"])

    def test_tables_list_sorted(self) -> None:
        summary = get_metadata_summary()
        assert summary["tables"] == sorted(summary["tables"])

    def test_tables_count_positive(self) -> None:
        summary = get_metadata_summary()
        assert summary["tables_count"] > 0


class TestClearMetadata:
    def test_calls_db_metadata_clear(self) -> None:
        # Подменяем db_metadata, чтобы не уничтожить реальные метаданные моделей,
        # иначе сломаются все остальные тесты, опирающиеся на зарегистрированные таблицы.
        from unittest.mock import MagicMock, patch

        from database.metadata import clear_metadata

        with patch("database.metadata.db_metadata", new=MagicMock()) as mock_md:
            clear_metadata()
            mock_md.clear.assert_called_once_with()
