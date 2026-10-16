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

"""Optional child-process observations supplied by an embedding application."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

from powercontext.builtin.runtime.protocols import RuntimeTracing

if TYPE_CHECKING:
    from pydantic_ai.models.instrumented import InstrumentationSettings


@dataclass(frozen=True)
class WorkerObservability:
    tracing: RuntimeTracing
    instrumentation: InstrumentationSettings | None


worker_observability: ContextVar[WorkerObservability | None] = ContextVar("worker_observability", default=None)
