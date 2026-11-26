"""``docs/upstream/OBSERVED.md`` as committed: what ESMIS does but never documents.

sdk-core's conventions §3 keep these notes in one file written by hand, and give each note
its evidence: the probe's date, its operation and its sample. Core's family check holds the
file's row in ``FETCHED.md`` and the probe that ends each note; what stays here is the
package's own: a sample recorded as a fixture is named by its path under
``tests/fixtures/``, which must stay there.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OBSERVED = ROOT / "docs" / "upstream" / "OBSERVED.md"
FIXTURES = ROOT / "tests" / "fixtures"
RECORDING = re.compile(r"`([a-z_]+/[A-Za-z0-9_]+\.json)`")


def test_every_recording_a_note_cites_is_a_fixture() -> None:
    cited = set(RECORDING.findall(OBSERVED.read_text(encoding="utf-8")))
    assert cited
    assert sorted(path for path in cited if not (FIXTURES / path).is_file()) == []
