"""The SFX plugin — optional emote/sound-effect after-cues for Prattletale.

For each eligible ``action``/``narration`` item the plugin rolls a chance, then
(on a pass) asks the platform SFX resolver (:mod:`app.sfx.resolver`) to choose one
clip from the character's emote identity and any conversation-enabled global
domains, validates it with a guard, and persists a compact ``sfx`` descriptor on
the item. The frontend plays the cue after the item's normal audio.

Modules:
- :mod:`.plugin` — the :class:`~app.apps.prattletale.plugins.base.Plugin`
  registration + the resolve/reroll/clear actions.
"""

from . import plugin  # noqa: F401 — registers the plugin on import
