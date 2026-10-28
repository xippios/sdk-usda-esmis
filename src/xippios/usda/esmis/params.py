"""The packaged reference lists, read from ``reference/`` without a call (conventions §3).

``/refresh-reference-data`` writes them; ``PackagedList.load(PACKAGE, name)`` reads one.

ESMIS packages no value list: its two packaged files, ``reference/publication.json`` and
``reference/agency.json``, are tables in core's ``PackagedList`` shape, which ``tasks.py``
reads with ``PackagedList.load``, the reader that builds an answer's ``meta`` (ADR-0022),
so ``PACKAGED_LISTS`` stays empty (queue row 101). ``scripts/refresh_reference.py`` writes
the files and ``reference/README.md`` carries their provenance.
"""

__all__ = ["PACKAGED_LISTS"]

PACKAGE = "xippios.usda.esmis"

PACKAGED_LISTS: tuple[str, ...] = ()
"""Names of the value lists that ship inside the package: none; the two packaged tables
are ``PackagedList`` files, read in ``tasks.py``."""
