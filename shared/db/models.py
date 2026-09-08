"""SQLAlchemy declarative models cho Postgres control-plane — schema mô tả ở
mục 4 của `docs/2026-09-08-generic-agent-loop-design.md`. Đây là bảng
*metadata vận hành* (usecase nào dùng agent nào), KHÔNG phải nơi chứa
prompt/tool code (nằm trong `agents/`, xem mục 0/0.1 của design doc).
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    UUID,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, relationship
from sqlalchemy.types import JSON

__all__ = [
    "Base",
    "BaseTableModel",
    "UsecaseStatus",
    "UsecaseVersionStatus",
    "AgentKind",
    "Usecase",
    "UsecaseVersion",
    "AgentcoreAgent",
    "UsecaseAgent",
]


class Base(DeclarativeBase):
    type_annotation_map = {
        dict[str, Any]: JSON,
        list[Any]: JSON,
    }

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_`%(constraint_name)s`",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class BaseTableModel(Base):
    """Copy nguyên tinh thần `app/models/base.py` bên synaptix-platform — xem
    ghi chú "Lưu ý bắt buộc khi định nghĩa model" ở mục 4 design doc: KHÔNG
    dựa vào `__tablename__` default (`cls.__name__.lower()`, không tự chèn
    `_`) — mọi model con override tường minh."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=datetime.now, server_default=func.now()
    )
    # Activity (Worker) không có identity người dùng -> luôn null trên các
    # dòng do Activity ghi. Có giá trị thật khi ghi qua admin CRUD (mục 6).
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    def __repr__(self) -> str:
        return ", ".join(f"{c.name}: {getattr(self, c.name)}" for c in self.__table__.columns)


class UsecaseStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class UsecaseVersionStatus(str, enum.Enum):
    DRAFT = "draft"
    READY = "ready"


class AgentKind(str, enum.Enum):
    ORCHESTRATOR = "orchestrator"
    SUBAGENT = "subagent"


class Usecase(BaseTableModel):
    __tablename__ = "usecases"

    usecase_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[UsecaseStatus] = mapped_column(
        SAEnum(UsecaseStatus, name="usecase_status", native_enum=False, length=16),
        nullable=False,
        default=UsecaseStatus.ACTIVE,
    )
    default_max_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    max_iterations_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    versions: Mapped[list["UsecaseVersion"]] = relationship(back_populates="usecase")


class UsecaseVersion(BaseTableModel):
    __tablename__ = "usecase_versions"
    __table_args__ = (
        UniqueConstraint("usecase_id", "version_number", name="uq_usecase_versions_usecase_id_version_number"),
        # partial unique index: đúng 1 dòng is_latest=true / usecase (mục 4)
        Index(
            "uq_usecase_versions_one_latest_per_usecase",
            "usecase_id",
            unique=True,
            postgresql_where="is_latest",
        ),
    )

    usecase_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usecases.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[UsecaseVersionStatus] = mapped_column(
        SAEnum(UsecaseVersionStatus, name="usecase_version_status", native_enum=False, length=16),
        nullable=False,
        default=UsecaseVersionStatus.DRAFT,
    )

    usecase: Mapped[Usecase] = relationship(back_populates="versions")
    agents: Mapped[list["UsecaseAgent"]] = relationship(back_populates="usecase_version")


class AgentcoreAgent(BaseTableModel):
    """Identity của 1 agent, độc lập usecase (mục 4) — 1 dòng có thể được
    nhiều `usecase_agents` khác nhau tham chiếu tới (tái sử dụng)."""

    __tablename__ = "agentcore_agents"
    __table_args__ = (
        CheckConstraint(
            "(agentcore_agent_arn IS NOT NULL) != (local_tool_ref IS NOT NULL)",
            name="exactly_one_of_arn_or_local_tool_ref",
        ),
    )

    agent_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    agentcore_agent_arn: Mapped[str | None] = mapped_column(String(512))
    # `module:function` trỏ vào agents/ (mục 0.1) — CHỈ dùng khi
    # agentcore_agent_arn null (chế độ mô phỏng cục bộ).
    local_tool_ref: Mapped[str | None] = mapped_column(String(256))
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    secrets: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    default_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    default_retry_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # KHÔNG đặt tên "metadata" — Base.metadata (BaseTableModel) là thuộc tính
    # SQLAlchemy Declarative riêng cho MetaData object (mục 4 design doc).
    agent_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    usecase_links: Mapped[list["UsecaseAgent"]] = relationship(back_populates="agent")


class UsecaseAgent(BaseTableModel):
    """Bảng liên kết N-N: usecase version nào dùng agent nào, vai trò gì
    (mục 4)."""

    __tablename__ = "usecase_agents"
    __table_args__ = (
        UniqueConstraint(
            "usecase_version_id", "agent_name", name="uq_usecase_agents_usecase_version_id_agent_name"
        ),
        # partial unique index: đúng 1 dòng kind='orchestrator' / version
        Index(
            "uq_usecase_agents_one_orchestrator_per_version",
            "usecase_version_id",
            unique=True,
            postgresql_where="kind = 'orchestrator'",
        ),
    )

    usecase_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usecase_versions.id"), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agentcore_agents.id"), nullable=False)
    # backend tự sinh f"{usecase_key}__{agent_key}" — KHÔNG nhận free-text từ
    # admin UI (mục 4). Không unique riêng lẻ ở cột này: unique theo cặp
    # (usecase_version_id, agent_name) ở trên là đủ, và tự thoả mãn vì
    # (usecase_version_id, agent_id) vốn đã xác định agent_name duy nhất.
    agent_name: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[AgentKind] = mapped_column(
        SAEnum(AgentKind, name="usecase_agent_kind", native_enum=False, length=16), nullable=False
    )
    timeout_seconds: Mapped[int | None] = mapped_column(Integer)
    retry_policy: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    usecase_version: Mapped[UsecaseVersion] = relationship(back_populates="agents")
    agent: Mapped[AgentcoreAgent] = relationship(back_populates="usecase_links")
