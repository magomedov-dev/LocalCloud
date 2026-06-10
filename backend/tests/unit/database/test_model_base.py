"""Тесты вспомогательных методов декларативного Base (to_dict и __repr__)."""

from __future__ import annotations

import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base


class _SampleModel(Base):
    """Минимальная ORM-модель для проверки помощников Base."""

    __tablename__ = "_sample_base_helper"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)


def make_sample() -> _SampleModel:
    return _SampleModel(id=str(uuid.uuid4()), name="viewer")


class TestBaseToDict:
    def test_returns_dict_with_column_values(self) -> None:
        obj = make_sample()
        result = obj.to_dict()
        assert isinstance(result, dict)
        assert "id" in result
        assert result["name"] == "viewer"

    def test_keys_match_table_columns(self) -> None:
        obj = make_sample()
        result = obj.to_dict()
        expected = {col.name for col in _SampleModel.__table__.columns}
        assert set(result.keys()) == expected


class TestBaseRepr:
    def test_repr_includes_id_when_present(self) -> None:
        obj = make_sample()
        text = repr(obj)
        assert "_SampleModel" in text
        assert str(obj.id) in text

    def test_repr_without_id(self) -> None:
        obj = _SampleModel(name="noid")
        text = repr(obj)
        assert text == "<_SampleModel>"
