"""Version metadata contract tests."""

from __future__ import annotations

import re
import unittest

from synapsectrl.metadata import (
    BACKEND_VERSION,
    HOOK_PROTOCOL_VERSION,
    HOOK_VERSION,
    expected_hook_fingerprint,
    expected_hook_metadata,
    hook_build_id,
)


class MetadataTests(unittest.TestCase):
    def test_expected_hook_fingerprint_is_stable_sha256(self):
        fingerprint = expected_hook_fingerprint()
        self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(fingerprint, expected_hook_fingerprint())

    def test_build_id_combines_revision_and_exact_hook_fingerprint(self):
        fingerprint = expected_hook_fingerprint()
        self.assertEqual(
            hook_build_id(HOOK_VERSION, fingerprint),
            f"v{HOOK_VERSION}+{fingerprint[:12]}",
        )
        self.assertIsNone(hook_build_id(None, fingerprint))
        self.assertIsNone(hook_build_id(HOOK_VERSION, None))

    def test_expected_hook_metadata_reports_backend_revision_protocol_and_build(self):
        metadata = expected_hook_metadata()
        self.assertEqual(metadata["backendVersion"], BACKEND_VERSION)
        self.assertEqual(metadata["hookVersion"], HOOK_VERSION)
        self.assertEqual(metadata["hookProtocolVersion"], HOOK_PROTOCOL_VERSION)
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", metadata["hookFingerprint"]))
        self.assertEqual(
            metadata["hookBuildId"],
            hook_build_id(HOOK_VERSION, metadata["hookFingerprint"]),
        )


if __name__ == "__main__":
    unittest.main()
