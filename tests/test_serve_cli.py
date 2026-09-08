"""Tests for the optional HTTP server command line."""

import unittest

from synapsectrl.serve_cli import _is_loopback, build_serve_parser


class ServeCliTests(unittest.TestCase):
    def test_defaults_are_loopback_and_separate_from_inspector_port(self):
        args = build_serve_parser().parse_args([])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8765)
        self.assertEqual(args.inspector_port, 9229)
        self.assertEqual(args.connect_timeout, 8.0)
        self.assertEqual(args.poll_interval, 0.75)
        self.assertEqual(args.unavailable_interval, 2.0)

    def test_loopback_detection(self):
        for host in ("127.0.0.1", "127.12.34.56", "::1", "localhost"):
            with self.subTest(host=host):
                self.assertTrue(_is_loopback(host))
        for host in ("0.0.0.0", "192.168.1.10", "example.test"):
            with self.subTest(host=host):
                self.assertFalse(_is_loopback(host))

    def test_rejects_invalid_ports_and_intervals(self):
        for arguments in (
            ["--port", "0"],
            ["--port", "65536"],
            ["--inspector-port", "0"],
            ["--poll-interval", "0"],
            ["--unavailable-interval", "nan"],
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(SystemExit):
                    build_serve_parser().parse_args(arguments)


if __name__ == "__main__":
    unittest.main()
