"""``docs/upstream/OBSERVED.md`` as committed: what ESMIS does but never documents.

sdk-core's conventions §3 keep these notes in one file written by hand, and give each note
its evidence: the probe's date, its operation and its sample. Core's family check holds the
file's row in ``FETCHED.md`` and the probe that ends each note; what stays here is the
package's own: a sample recorded as a fixture is named by its path under
``tests/fixtures/``, which must stay there, and no probe stands outside the file. The
package's own text, ``CLAUDE.md``, ``README.md``, every module under
``src/xippios/usda/esmis/``, and the docstrings and comments of its two scripts and of every
test module but this one, keeps what its reader needs and cites a note by its heading: the
probes, and the lists of ESMIS dated by the day they were read, stand in ``OBSERVED.md``
alone (conventions §3; sdk-core ADR-0044, decision 3).
"""

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OBSERVED = ROOT / "docs" / "upstream" / "OBSERVED.md"
FIXTURES = ROOT / "tests" / "fixtures"
PACKAGE = ROOT / "src" / "xippios" / "usda" / "esmis"
RECORDING = re.compile(r"`([a-z_]+/[A-Za-z0-9_]+\.json)`")
DATE = r"\b(?:19|20)\d\d-\d\d-\d\d\b"
WITHIN = r"(?:(?!\. ).){0,80}?"
"""Up to 80 characters of one sentence."""
PROBE = re.compile(
    r"\bprobed\b"
    r"|\bprobes? (?:of|on|kept|saw|showed|found|read|sent)\b"
    rf"|\b(?:list|lists|page|pages|walk|walks|catalog|table)(?: \d+(?: (?:to|and) \d+)?)?"
    rf" (?:of|on|as of) {DATE}"
    rf"|\b\d[\d,]* (?:releases|publications|agencies|pages|items) (?:of|on|as of) {DATE}"
    rf"|\b(?:walk|matched|counted|answered|listed|held|found|showed|saw)\b{WITHIN}\bon {DATE}"
    rf"|\bas of {DATE}",
    re.IGNORECASE,
)
"""A probe in prose: the word ``probed``, a probe of or on something, a list, page, walk,
catalog or table of ESMIS dated by the day it was read, a count of that day, or what ESMIS
matched, counted, answered, listed or held on a day. A fixture's provenance, the day a
recording or the packaged table was made, follows ``recorded`` or ``fetched``, which the
pattern never reads as a probe, and a date of a release, ``95866 of 1995-01-31`` or ``the WASDE
of 2026-10-09``, follows no word of the pattern."""
RULES = [ROOT / "CLAUDE.md", ROOT / "README.md"]
"""The package's documents, read whole."""
SCRIPTS = [ROOT / "scripts" / "refresh_reference.py", ROOT / "scripts" / "refresh_upstream.py"]
"""The package's own scripts, whose docstrings and comments are read."""
TESTS = sorted(path for path in (ROOT / "tests").glob("*.py") if path.name != Path(__file__).name)
"""The test modules but this one, which names the probes' words: their docstrings and comments
are read, while a value a test sends or compares is no text of the package."""


def prose(path: Path) -> str:
    """The docstrings and comments of a Python file, each joined to the next by a line.

    A docstring is a string standing alone as a statement: a module's, a class's or a
    function's, and the one under a name it documents.
    """
    source = path.read_text(encoding="utf-8")
    docstrings = [
        node.value.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]
    comments = [
        token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]
    return "\n".join([*docstrings, *comments])


def texts() -> dict[str, str]:
    """Each text the rule reads, by its path from the repository's root, its lines joined."""
    whole = [*RULES, *sorted(PACKAGE.rglob("*.py"))]
    read = {path: path.read_text(encoding="utf-8") for path in whole}
    read |= {path: prose(path) for path in [*SCRIPTS, *TESTS]}
    return {str(path.relative_to(ROOT)): " ".join(text.split()) for path, text in read.items()}


def test_every_recording_a_note_cites_is_a_fixture() -> None:
    cited = set(RECORDING.findall(OBSERVED.read_text(encoding="utf-8")))
    assert cited
    assert sorted(path for path in cited if not (FIXTURES / path).is_file()) == []


@pytest.mark.parametrize(
    ("text", "probe"),
    [
        ("A raw slash is no route either: probed on 2026-10-27, Drupal answered", True),
        ("from the WASDE recordings, not probed, and the live test", True),
        ("read once each by a probe of the whole list", True),
        ("as the probe of 2026-11-27 counted them", True),
        ("WASDE's page 3 of 2026-11-27 lists 95866 of 1995-01-31", True),
        ("Page 0 of 2026-10-27 holds three", True),
        ("pages 0 to 7 of 2026-11-27", True),
        ("as WASDE's list of 2026-11-27 has it", True),
        ("WASDE's 703 releases of 2026-10-27 filling 29 pages", True),
        ("101 publication pages as of 2026-10-27", True),
        ("The walk of 2026-10-27 counted 2033 Active", True),
        ("A walk of every page of esmis_api_publication_findAll on 2026-10-27", True),
        ('"wasde" matched 7 publications on 2026-10-27', True),
        ("recorded on 2026-10-27, and release_find_by_id/95621.json on 2026-10-28", False),
        ("(``release_find_all/page0.json``, 2026-10-27)", False),
        ("the table of 2522 publications packaged with this version, fetched on 2026-10-27", False),
        ("Nine agencies as recorded on 2026-10-27", False),
        ("release 95866 of 1995-01-31 among releases of 2019", False),
        ("``796099`` (the WASDE of 2026-10-09)", False),
        ("each note with the probe that showed it", False),
        ("since: The earliest release date to keep, e.g. ``2026-01-01``", False),
    ],
)
def test_a_probe_in_prose_is_told_from_a_date(text: str, probe: bool) -> None:
    """The wordings a probe took in the package's texts, and the dates that stand in them as
    a recording's or a table's provenance, a release's date, a pointer to the notes or a
    value."""
    assert bool(PROBE.search(text)) is probe


def test_no_probe_stands_outside_the_notes() -> None:
    """A probe, kept or not, and a list of ESMIS dated by its day stand in ``OBSERVED.md``
    alone; the rule each backs stays where it is, citing its note by the note's heading."""
    found = {path: [match[0] for match in PROBE.finditer(text)] for path, text in texts().items()}
    assert {path: probes for path, probes in found.items() if probes} == {}
