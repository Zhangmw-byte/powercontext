# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Measure a declared local scenario; this is not the hidden competition sequence."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
from pathlib import Path

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, CaptureSource, PrepareContextRequest, open_builtin_runtime
from powercontext.builtin.runtime.context_pack import ContextPack, ContextPackDelta, apply_context_pack_delta
from powercontext.builtin.scope import ScopeDraft
from powercontext.builtin.sources import ContentSource


class EvidencePipeline:
    async def extract(self, request, /):
        return tuple(
            MemoryEntryInput(kind="conversation-turn", text=source.content, sources=(source,))
            for source in request.sources
            if isinstance(source, ContentSource)
        )


def _savings(transmitted: int, total: int) -> float | None:
    return 1 - transmitted / total if total else None


def _receive(base: ContextPack | None, wire: bytes) -> ContextPack:
    if base is None:
        return ContextPack.from_bytes(wire)
    return apply_context_pack_delta(base, ContextPackDelta.from_bytes(wire))


async def measure(sample: dict) -> dict:
    raw_total = full_total = gzip_total = incremental_total = nonempty = 0
    contexts = set()
    per_round = []
    sender_base = receiver_base = None
    initial = sample["initial_turns"]
    appended = 0
    async with open_builtin_runtime(
        BuiltinConfig(database=SQLiteConfig()), candidate_pipeline=EvidencePipeline()
    ) as runtime:
        scope = await runtime.scopes.create(
            ScopeDraft(title="Pack cost", summary="Local cost", idempotency_key="pack-cost")
        )
        sources = runtime.sources.for_scope(scope.scope_id)
        memory = runtime.memory.for_scope(scope.scope_id)
        context = runtime.context.for_scope(scope.scope_id)

        async def capture(turn):
            await sources.capture(
                CaptureSource(
                    source_id=f"meeting-turn-{turn['turn_index']}", content=turn["text"], metadata={"origin": "qmsum"}
                )
            )

        async def flush():
            while (await memory.flush()).processed:
                pass

        for turn in sample["turns"][:initial]:
            await capture(turn)
        await flush()
        for round_index in range(sample["rounds"]):
            if round_index in sample["append_before_round"]:
                await capture(sample["turns"][initial + appended])
                appended += 1
                await flush()
            query_index = round_index * len(sample["queries"]) // sample["rounds"]
            request = PrepareContextRequest(query=sample["queries"][query_index], max_bytes=8000)
            ordinary = await context.prepare(request)
            raw = (ordinary.content or "").encode("utf-8")
            transfer = await context.prepare_incremental(request, base_pack=sender_base)
            wire = transfer.to_bytes()
            receiver_base = _receive(receiver_base, wire)
            target = ContextPack.from_content(ordinary.content)
            if receiver_base.to_bytes() != target.to_bytes() or b"".join(receiver_base.items) != raw:
                raise RuntimeError("Serialized receiver disagrees with ordinary prepare")  # noqa: TRY003
            sender_base = target
            raw_total += len(raw)
            full_total += target.byte_count
            gzip_total += len(gzip.compress(raw, compresslevel=9, mtime=0))
            incremental_total += len(wire)
            nonempty += bool(raw)
            contexts.add(hashlib.sha256(raw).hexdigest())
            per_round.append({"round": round_index, "raw_bytes": len(raw), "wire_bytes": len(wire)})
    raw_savings = _savings(incremental_total, raw_total)
    return {
        "scenario": sample["description"],
        "formal_competition_acceptance": False,
        "meeting_id": sample["meeting_id"],
        "upstream_commit": sample["upstream_commit"],
        "initial_turns": initial,
        "rounds": sample["rounds"],
        "nonempty_rounds": nonempty,
        "distinct_contexts": len(contexts),
        "raw_full_bytes": raw_total,
        "full_v1_pack_bytes": full_total,
        "per_request_gzip_bytes": gzip_total,
        "incremental_bytes": incremental_total,
        "savings_vs_raw": raw_savings,
        "savings_vs_full_pack": _savings(incremental_total, full_total),
        "savings_vs_gzip": _savings(incremental_total, gzip_total),
        "local_cost_gate_passed": nonempty == 40
        and len(contexts) >= 4
        and raw_savings is not None
        and raw_savings >= 0.45,
        "per_round": per_round,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=Path(__file__).parent / "data/qmsum-sample.json")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    sample = json.loads(arguments.sample.read_text(encoding="utf-8"))
    result = asyncio.run(measure(sample))
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
