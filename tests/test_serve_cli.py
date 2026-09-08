"""Tests for the optional HTTP server command line."""

import os
import unittest
from unittest.mock import patch

from synapsectrl.serve_cli import (
    _HTTP_TOKEN_ENV,
    _is_loopback,
    _resolve_token,
    build_serve_parser,
)


class ServeCliTests(unittest.TestCase):
    def test_defaults_are_loopback_and_separate_from_inspector_port(self):
        args = build_serve_parser().parse_args([])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8765)
        self.assertEqual(args.inspector_port, 9229)
        self.assertEqual(args.connect_timeout, 8.0)
        self.assertEqual(args.poll_interval, 0.75)
        self.assertEqual(args.unavailable_interval, 2.0)
        self.assertIsNone(args.token)
        self.assertFalse(args.generate_token)

    def test_loopback_detection(self):
        for host in ("127.0.0.1", "127.12.34.56", "::1", "localhost"):
            with self.subTest(host=host):
                self.assertTrue(_is_loopback(host))
        for host in ("0.0.0.0", "192.168.1.10", "example.test"):
            with self.subTest(host=host):
                self.assertFalse(_is_loopback(host))

    def test_rejects_invalid_ports_intervals_and_tokens(self):
        for arguments in (
            ["--port", "0"],
            ["--port", "65536"],
            ["--inspector-port", "0"],
            ["--poll-interval", "0"],
            ["--unavailable-interval", "nan"],
            ["--token", "bad token"],
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(SystemExit):
                    build_serve_parser().parse_args(arguments)

    def test_token_and_generate_token_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            build_serve_parser().parse_args(["--token", "abc", "--generate-token"])

    def test_resolve_token_uses_cli_then_environment(self):
        args = build_serve_parser().parse_args(["--token", "cli-token"])
        with patch.dict(os.environ, {_HTTP_TOKEN_ENV: "env-token"}):
            self.assertEqual(_resolve_token(args), "cli-token")

        args = build_serve_parser().parse_args([])
        with patch.dict(os.environ, {_HTTP_TOKEN_ENV: "env-token"}):
            self.assertEqual(_resolve_token(args), "env-token")

    def test_resolve_token_rejects_invalid_environment_value(self):
        args = build_serve_parser().parse_args([])
        with patch.dict(os.environ, {_HTTP_TOKEN_ENV: "bad token"}):
            with self.assertRaises(ValueError):
                _resolve_token(args)

    def test_generate_token_uses_strong_random_token(self):
        args = build_serve_parser().parse_args(["--generate-token"])
        with patch("synapsectrl.serve_cli.secrets.token_urlsafe", return_value="generated-token") as generate:
            self.assertEqual(_resolve_token(args), "generated-token")
        generate.assert_called_once_with(32)


if __name__ == "__main__":
    unittest.main()
