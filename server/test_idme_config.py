"""
Unit tests for IDME session routing, focused on IDME_CLASS_SESSION_OVERRIDE.

Classes are normally routed to a submission session by the leading form number
of their class string (`form_of`). A class with no leading number (e.g.
'MENTARI 1') maps to no session and is never submitted. The override pins such
classes to a named session; because it resolves through the single `form_of`
chokepoint, every downstream consumer (cutoff filter, scan gate, Telegram
routing, settings UI) follows automatically. These tests cover the parser, the
form resolution, and the end-to-end form_of/session_of routing.

Pure config logic — no DB or network. Run directly (`python test_idme_config.py`)
or under pytest, from `server/` (e.g. with .venv-idme).
"""

import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.idme import idme_config  # noqa: E402
from src.idme.idme_config import (  # noqa: E402
    IDMEConfig,
    _parse_class_session_override,
    _resolve_form_overrides,
)


class ParseOverrideTests(unittest.TestCase):
    """IDME_CLASS_SESSION_OVERRIDE string -> {class_name: session_name}."""

    def test_empty_and_none(self):
        self.assertEqual(_parse_class_session_override(None), {})
        self.assertEqual(_parse_class_session_override(''), {})
        self.assertEqual(_parse_class_session_override('   '), {})

    def test_basic_pairs(self):
        got = _parse_class_session_override(
            'MENTARI 1=morning, MENTARI 2=morning, MENTARI 3=morning')
        self.assertEqual(got, {
            'MENTARI 1': 'morning',
            'MENTARI 2': 'morning',
            'MENTARI 3': 'morning',
        })

    def test_class_name_verbatim_session_lowercased(self):
        # Class name keeps its exact case/spacing (must match roster verbatim);
        # only the session name is normalised.
        got = _parse_class_session_override('MENTARI 1 = MORNING')
        self.assertEqual(got, {'MENTARI 1': 'morning'})

    def test_malformed_entries_skipped(self):
        got = _parse_class_session_override(
            'MENTARI 1=morning, no_equals_here, =morning, MENTARI 2=, , '
            'MENTARI 3=evening')
        # Only the two well-formed pairs survive; the rest are logged + dropped.
        self.assertEqual(got, {'MENTARI 1': 'morning', 'MENTARI 3': 'evening'})


class ResolveFormOverrideTests(unittest.TestCase):
    """{class: session} -> {class: representative form} against a session list."""

    SESSIONS = [
        {'name': 'morning', 'forms': [3, 4, 5, 6]},
        {'name': 'evening', 'forms': [1, 2]},
    ]

    def test_lowest_form_is_representative(self):
        got = _resolve_form_overrides(
            {'MENTARI 1': 'morning', 'JUARA 2': 'evening'}, self.SESSIONS)
        self.assertEqual(got, {'MENTARI 1': 3, 'JUARA 2': 1})

    def test_unknown_or_disabled_session_dropped(self):
        # A session that isn't scheduled (disabled cutoff -> absent from
        # SESSIONS) or a typo'd name resolves to nothing, so the class stays
        # unrouted rather than being silently misrouted.
        got = _resolve_form_overrides(
            {'MENTARI 1': 'morning', 'GHOST': 'afternoon'}, self.SESSIONS)
        self.assertEqual(got, {'MENTARI 1': 3})

    def test_single_session_school(self):
        got = _resolve_form_overrides(
            {'MENTARI 1': 'morning'}, [{'name': 'morning', 'forms': [3, 4, 5, 6]}])
        self.assertEqual(got, {'MENTARI 1': 3})


class _ReloadedConfig:
    """Context manager: reload idme_config with a patched environment so the
    import-time class attributes (SESSIONS, CLASS_SESSION_OVERRIDE, ...) are
    recomputed, then restore the original module + env on exit."""

    def __init__(self, **env):
        self._env = env
        self._saved = {}

    def __enter__(self):
        for k, v in self._env.items():
            self._saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(idme_config)
        return idme_config.IDMEConfig

    def __exit__(self, *exc):
        for k, old in self._saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
        importlib.reload(idme_config)
        return False


class RoutingIntegrationTests(unittest.TestCase):
    """form_of / session_of end-to-end with the override active."""

    def test_no_override_unrouted(self):
        # Baseline: without the override, a no-leading-number class is unrouted.
        self.assertIsNone(IDMEConfig.form_of('MENTARI 1'))
        self.assertIsNone(IDMEConfig.session_of('MENTARI 1'))

    def test_leading_number_still_parsed(self):
        self.assertEqual(IDMEConfig.form_of('5 UKM'), 5)
        self.assertEqual(IDMEConfig.form_of('2 UM'), 2)
        self.assertIsNone(IDMEConfig.form_of('PERALIHAN'))

    def test_override_routes_to_morning(self):
        with _ReloadedConfig(
            IDME_CLASS_SESSION_OVERRIDE='MENTARI 1=morning, MENTARI 2=morning, '
                                        'MENTARI 3=morning') as cfg:
            for cn in ('MENTARI 1', 'MENTARI 2', 'MENTARI 3'):
                # form_of returns morning's representative form...
                self.assertEqual(cfg.form_of(cn), 3, cn)
                # ...so session_of places it in the morning session.
                sess = cfg.session_of(cn)
                self.assertIsNotNone(sess, cn)
                self.assertEqual(sess['name'], 'morning', cn)

    def test_override_does_not_disturb_numbered_classes(self):
        with _ReloadedConfig(
            IDME_CLASS_SESSION_OVERRIDE='MENTARI 1=morning') as cfg:
            self.assertEqual(cfg.form_of('5 UKM'), 5)
            self.assertEqual(cfg.session_of('5 UKM')['name'], 'morning')
            self.assertEqual(cfg.session_of('2 UM')['name'], 'evening')

    def test_override_wins_over_leading_number(self):
        # An explicit operator instruction beats the implicit form-number rule:
        # '2 SPECIAL' would be evening by its number, but the override forces it
        # to morning (representative form 3).
        with _ReloadedConfig(
            IDME_CLASS_SESSION_OVERRIDE='2 SPECIAL=morning') as cfg:
            self.assertEqual(cfg.form_of('2 SPECIAL'), 3)
            self.assertEqual(cfg.session_of('2 SPECIAL')['name'], 'morning')

    def test_override_to_evening(self):
        with _ReloadedConfig(
            IDME_CLASS_SESSION_OVERRIDE='PERALIHAN=evening') as cfg:
            self.assertEqual(cfg.form_of('PERALIHAN'), 1)
            self.assertEqual(cfg.session_of('PERALIHAN')['name'], 'evening')


if __name__ == '__main__':
    unittest.main(verbosity=2)
