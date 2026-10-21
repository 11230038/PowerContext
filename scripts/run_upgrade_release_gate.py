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

"""Select the built wheel and run the same upgrade gate locally and in CI."""

import argparse
import json
import tempfile
from pathlib import Path

from upgrade_release_gate import ROOT, GateError, gate, require


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--release", action="store_true")
    notes = parser.add_mutually_exclusive_group()
    notes.add_argument("--release-event", type=Path)
    notes.add_argument("--release-notes", type=Path)
    args = parser.parse_args()
    try:
        wheels = list(args.dist.glob("*.whl"))
        require(len(wheels) == 1, "Build exactly one release wheel before running upgrade acceptance")
        release_notes = None
        if args.release_event:
            release_notes = json.loads(args.release_event.read_text(encoding="utf-8"))["release"]["body"] or ""
        elif args.release_notes:
            release_notes = args.release_notes.read_text(encoding="utf-8")
        output = args.output or Path(tempfile.mkdtemp(prefix="pc-upgrade-evidence-")) / "report"
        gate(ROOT, wheels[0].resolve(), output.resolve(), release=args.release, release_notes=release_notes)
        result = json.loads((output / "result.json").read_text(encoding="utf-8"))
        print(
            f"Upgrade gate passed: {result['mode']}; {len(result['cases'])} accepted upgrade combinations. "
            f"Evidence: {output / 'result.json'}"
        )
    except (GateError, OSError, ValueError) as error:
        raise SystemExit(f"Upgrade gate failed: {error}") from error  # noqa: TRY003 -- operator diagnostic


if __name__ == "__main__":
    main()
