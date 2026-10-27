"""StrEnums for packaged value lists (conventions, section 3): none.

ESMIS packages no value list, so nothing is generated here: the enumerations of the OpenAPI
document (``Status``, ``Subscribable``, ``ResourceType``) are hand-written in ``models.py``.
A value list packaged later renders here through core's ``render_enums``, called by
``scripts/refresh_reference.py``.
"""

__all__ = []
