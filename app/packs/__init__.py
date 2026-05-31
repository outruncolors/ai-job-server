"""Packs — curated bundles of Cruddable envelopes.

A pack is a JSON document ``{id, name, description, tags, items:[envelope...]}``
shipped in the repo (``packs/<type>/<pack_id>.json``) or authored by the user
(``config/packs/<type>/<pack_id>.json``). Applying a pack is byte-for-byte the
same as extending a cruddable type with the pack's ``items`` — each item is a
fully-formed envelope whose id already ends ``_pack_<pack_id>`` and whose tags
already include ``"Pack"``.
"""
