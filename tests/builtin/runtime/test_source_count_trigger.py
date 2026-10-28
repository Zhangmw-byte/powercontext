# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Count admission retains the supervisor's durable request guarantees."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from powercontext.builtin.persistence.processing_intents import ArtifactProcessingIntentRepository
from powercontext.builtin.runtime import BuiltinConfig, RuntimeConfig, open_builtin_runtime
from powercontext.builtin.runtime.artifact_processing import ArtifactProcessingBinding, ArtifactProcessingSupervisor
from powercontext.builtin.runtime.composition import BuiltinConfigurationError
from tests.builtin.runtime.test_processing_scheduler import _intent, _Launcher, _profile, _request, _wait


@pytest.mark.parametrize("field", ["memory_source_count_threshold", "topic_memory_source_count_threshold"])
def test_count_configuration_round_trips_without_coercing_strings(field):
    config = RuntimeConfig(**{field: 3})
    assert getattr(RuntimeConfig.model_validate_json(config.model_dump_json()), field) == 3
    with pytest.raises(ValidationError):
        RuntimeConfig.model_validate_json('{"' + field + '": "3"}')


@pytest.mark.parametrize("field", ["memory_source_count_threshold", "topic_memory_source_count_threshold"])
async def test_count_configuration_requires_a_processing_provider(field):
    with pytest.raises(BuiltinConfigurationError):
        async with open_builtin_runtime(BuiltinConfig(runtime=RuntimeConfig(**{field: 3}))):
            pytest.fail("A count-triggered native processor needs a reconstructible provider")


async def test_ineligible_count_pages_do_not_hide_later_scopes(tmp_path):
    async with _profile(tmp_path, "count-pages") as profile:
        for number in range(120):
            await _request(profile.database, "memory-binding", f"s-{number:03}", requested=False)

        async def eligible(_connection, scopes):
            return frozenset(scope for scope in scopes if scope in {"s-110", "s-119"})

        launcher = _Launcher(profile.database)
        async with ArtifactProcessingSupervisor(
            database=profile.database,
            bindings=(
                ArtifactProcessingBinding("memory-binding", "memory", launcher, source_count_scope_filter=eligible),
            ),
            lease_mode="single-process",
            oceanbase_tick_seconds=0.02,
        ) as supervisor:
            await _wait(lambda: supervisor.family_status["memory"]["completed"] == 2)
            assert {work.scope_id for work in launcher.assignments} == {"s-110", "s-119"}
            assert (await _intent(profile.database, "memory-binding", "s-000")).requested_generation == 0


async def test_accepted_count_work_retries_even_when_count_eligibility_changes(tmp_path):
    async with _profile(tmp_path, "count-retry") as profile:
        await _request(profile.database, "memory-binding", "scope", requested=False)
        eligible_now = True
        attempts = 0

        async def eligible(_connection, scopes):
            return frozenset(scopes) if eligible_now else frozenset()

        async def fail_once(_work):
            nonlocal attempts, eligible_now
            attempts += 1
            if attempts == 1:
                eligible_now = False
                raise RuntimeError("retry the already accepted invocation")  # noqa: TRY003

        launcher = _Launcher(profile.database, on_work=fail_once)
        async with ArtifactProcessingSupervisor(
            database=profile.database,
            bindings=(
                ArtifactProcessingBinding("memory-binding", "memory", launcher, source_count_scope_filter=eligible),
            ),
            lease_mode="single-process",
            oceanbase_tick_seconds=0.02,
            retry_base_seconds=0.1,
            retry_cap_seconds=0.1,
            retry_jitter=lambda: 1,
        ) as supervisor:
            await _wait(lambda: supervisor.family_status["memory"]["completed"] == 1)
            row = await _intent(profile.database, "memory-binding", "scope")
            assert attempts == 2
            assert row.requested_generation == row.handled_generation == 1


class _AdmissionFailure(ArtifactProcessingIntentRepository):
    failed = False

    async def request(self, connection, scope_id, binding_name, /):
        result = await super().request(connection, scope_id, binding_name)
        if scope_id == "scope-b" and not self.failed:
            self.failed = True
            raise RuntimeError("roll back this admission page")  # noqa: TRY003
        return result


async def test_failed_count_admission_rolls_back_and_resumes_without_new_input(tmp_path):
    async with _profile(tmp_path, "count-admission-rollback") as profile:
        for scope in ("scope-a", "scope-b", "scope-c"):
            await _request(profile.database, "memory-binding", scope, requested=False)

        async def eligible(_connection, scopes):
            return frozenset(scopes)

        launcher = _Launcher(profile.database)
        async with ArtifactProcessingSupervisor(
            database=profile.database,
            bindings=(
                ArtifactProcessingBinding("memory-binding", "memory", launcher, source_count_scope_filter=eligible),
            ),
            lease_mode="single-process",
            intents=_AdmissionFailure(),
            oceanbase_tick_seconds=0.02,
        ) as supervisor:
            await _wait(lambda: supervisor.family_status["memory"]["completed"] == 3)
            assert [work.scope_id for work in launcher.assignments] == ["scope-a", "scope-b", "scope-c"]
            for scope in ("scope-a", "scope-b", "scope-c"):
                row = await _intent(profile.database, "memory-binding", scope)
                assert row.requested_generation == row.handled_generation == 1
