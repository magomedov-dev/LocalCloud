"""${message}

Идентификатор ревизии: ${up_revision}
Предыдущая ревизия: ${down_revision | comma,n}
Дата создания: ${create_date}

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# Идентификаторы ревизии, используемые Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """Применяет изменения схемы базы данных.

    Функция вызывается Alembic при обновлении базы данных до этой ревизии.
    Здесь размещаются операции создания, изменения или удаления объектов схемы.
    """

    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Откатывает изменения схемы базы данных.

    Функция вызывается Alembic при откате базы данных с этой ревизии на
    предыдущую. Здесь размещаются операции, обратные изменениям из "upgrade".
    """

    ${downgrades if downgrades else "pass"}
