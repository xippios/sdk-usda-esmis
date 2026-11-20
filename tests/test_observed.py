"""``docs/upstream/OBSERVED.md`` as committed: what ESMIS does but never documents.

sdk-core's conventions §3 keep these notes in one file written by hand, which
``FETCHED.md`` lists in a row of its own, and give each note its evidence: the probe's
date, its operation and its sample. A note here is a ``###`` section, and its last
paragraph, ``Probe:``, names the probe; a sample recorded as a fixture is named by its
path under ``tests/fixtures/``, which must stay there.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "docs" / "upstream"
OBSERVED = UPSTREAM / "OBSERVED.md"
FIXTURES = ROOT / "tests" / "fixtures"
HAND = "written by hand: what upstream does but never documents; not fetched or checked"
DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
RECORDING = re.compile(r"`([a-z_]+/[A-Za-z0-9_]+\.json)`")


def notes() -> dict[str, list[str]]:
    """Each note's heading and its paragraphs, each paragraph's lines joined by a space.

    A ``##`` heading groups notes and is none itself.
    """
    text = OBSERVED.read_text(encoding="utf-8")
    parts = re.split(r"^(##|###) (.+)$", text, flags=re.MULTILINE)
    return {
        heading: [" ".join(block.split()) for block in body.split("\n\n") if block.strip()]
        for level, heading, body in zip(parts[1::3], parts[2::3], parts[3::3], strict=True)
        if level == "###"
    }


def test_fetched_md_lists_observed_md_in_a_row_of_its_own() -> None:
    rows = (UPSTREAM / "FETCHED.md").read_text(encoding="utf-8").splitlines()
    assert f"| OBSERVED.md | - | - | - | - | - | - | - | {HAND} |" in rows


def test_every_note_ends_with_its_probe_and_its_date() -> None:
    found = notes()
    assert found
    for heading, paragraphs in found.items():
        probe = paragraphs[-1]
        assert probe.startswith("Probe: "), heading
        assert DATE.search(probe), heading


def test_every_recording_a_note_cites_is_a_fixture() -> None:
    cited = set(RECORDING.findall(OBSERVED.read_text(encoding="utf-8")))
    assert cited
    assert sorted(path for path in cited if not (FIXTURES / path).is_file()) == []
