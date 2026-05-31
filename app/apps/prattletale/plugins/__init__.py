"""Prattletale plugin system.

A **plugin** is a backend package under ``app/apps/prattletale/plugins/<id>/``
that registers itself at import (mirroring Blaboratory's action registry), plus
optional **frontend assets** under ``static/apps/prattletale/plugins/<id>/``. A
plugin declares a :class:`~app.apps.prattletale.plugins.base.Plugin` manifest and
zero or more named **actions** — async callables the frontend invokes through one
generic dispatch endpoint.

The :mod:`~app.apps.prattletale.plugins.registry` holds the registered plugins;
``seed_plugins()`` (called once at lifespan) imports every plugin package so its
``register(...)`` runs and seeds any Prompt Pal entries. Summarizer is the first
plugin (see ``docs/apps/prattletale/phase3-plugins-build-plan.md``).
"""
