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

"""Read-only admission of retained exact-version evidence."""

from powercontext.builtin.persistence.atomic_memory_readiness import assert_atomic_memory_migration_ready
from powercontext.builtin.persistence.migrations.pinned import finish, pinned


def preflight(connection, *, configuration):
    pass


def apply(connection, *, configuration):
    pass


def verify(connection, *, configuration):
    validate(connection, configuration=configuration)


def validate(connection, *, configuration):
    finish(assert_atomic_memory_migration_ready(pinned(connection)))
