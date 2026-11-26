"""The packaged reference lists, read from ``reference/`` without a call (conventions §3).

``/refresh-reference-data`` writes them; ``PackagedList.load(PACKAGE, name)`` reads one.

ESMIS packages two tables in core's ``PackagedList`` shape, ``reference/agency.json`` and
``reference/publication.json``, the records of ``esmis_api_agency_findAll`` and of every page
of ``esmis_api_publication_findAll``, which ``scripts/refresh_reference.py`` declares in its
one ``LISTS`` and writes, never by hand; ``reference/README.md`` carries their provenance.
Neither makes an enum: the document's enumerations are written by hand in ``models.py``, so
the package has no ``enums.py``. ``AGENCIES`` declares the agency table's codes once, the
acronyms with their titles (sdk-core ADR-0045): ``list_publications`` checks its
``agency_acronym`` by it, and every answer that holds a release or a publication names its
agencies by it in ``meta.names`` (sdk-core ADR-0067).
"""

from xippios.core import PackagedCodes, PackagedList

from xippios.usda.esmis._client import SOURCE

__all__ = ["AGENCIES", "PACKAGE", "PACKAGED_LISTS"]

PACKAGE = "xippios.usda.esmis"
"""The package whose ``reference/`` holds the packaged tables, for ``PackagedList.load``."""

PACKAGED_LISTS: tuple[str, ...] = ("agency", "publication")
"""The lists that ship inside the package, ``reference/<name>.json``; the refresh script
declares exactly these in its one ``LISTS``, and ``tests/test_live.py`` names each in
``LIVE_LISTS`` or ``NO_LIVE_LIST``."""

AGENCIES: PackagedCodes = PackagedList.load(PACKAGE, "agency").codes(
    "acronym", "title", source=SOURCE
)
"""The agency table's acronyms, each named by its title, compared exactly as ESMIS spells
them: ``"ERS"`` is the Economic Research Service, and ``"ers"`` is no acronym."""
