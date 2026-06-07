"""Тесты вспомогательных методов декларативного Base (to_dict и __repr__)."""

from __future__ import annotations

import uuid

from database.models.roles import Role


def make_role() -> Role:
    return Role(
        id=uuid.uuid4(),
        name="viewer",
        description="A viewer role",
        is_system=False,
        is_active=True,
    )


class TestBaseToDict:
    def test_returns_dict_with_column_values(self) -> None:
        role = make_role()
        result = role.to_dict()
        assert isinstance(result, dict)
        assert "id" in result
        assert result["name"] == "viewer"

    def test_keys_match_table_columns(self) -> None:
        role = make_role()
        result = role.to_dict()
        expected = {col.name for col in Role.__table__.columns}
        assert set(result.keys()) == expected


class TestBaseRepr:
    def test_repr_includes_id_when_present(self) -> None:
        role = make_role()
        text = repr(role)
        assert "Role" in text
        assert str(role.id) in text

    def test_repr_without_id(self) -> None:
        # Role переопределяет Base.__repr__, поэтому всегда перечисляет ключевые
        # поля и выводит id=None, когда id не задан.
        role = Role(name="noid")
        text = repr(role)
        assert text.startswith("<Role(")
        assert "id=None" in text
        assert "name='noid'" in text
