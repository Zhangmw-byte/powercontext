# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Persisted evidence eligibility shared by Topic search and lifecycle commands."""

from typing import Any

from sqlalchemy import select

from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_NODES_TABLE


def topic_is_available(scope_id: Any, artifact_id: Any) -> Any:
    """Unregistered Topics retain their previous visibility."""

    nodes = SOURCE_LIFECYCLE_NODES_TABLE
    return (
        ~select(nodes.c.node_id)
        .where(
            nodes.c.scope_id == scope_id,
            nodes.c.kind == "topic",
            nodes.c.artifact_id == artifact_id,
            nodes.c.available.is_(False),
        )
        .exists()
    )
