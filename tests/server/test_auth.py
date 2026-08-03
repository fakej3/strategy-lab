"""Tests for server/auth.py — password hashing, verification, dependency."""
from __future__ import annotations

import os

import pytest

from server.auth import authenticate, hash_password, verify_password


class TestHashPassword:
    def test_returns_hex_string(self):
        h = hash_password("test")
        assert isinstance(h, str)
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_passwords_differ(self):
        assert hash_password("abc") != hash_password("xyz")

    def test_same_password_same_hash(self):
        assert hash_password("hello") == hash_password("hello")

    def test_length_is_64_hex_chars(self):
        # SHA-256 → 32 bytes → 64 hex chars
        assert len(hash_password("anything")) == 64


class TestVerifyPassword:
    def test_correct_hash_verifies(self):
        h = hash_password("mypassword")
        assert verify_password("mypassword", h) is True

    def test_wrong_password_fails(self):
        h = hash_password("correct")
        assert verify_password("wrong", h) is False

    def test_empty_hash_accepts_admin(self):
        # Default: no hash set → accept "admin"
        assert verify_password("admin", "") is True

    def test_empty_hash_rejects_non_admin(self):
        assert verify_password("other", "") is False

    def test_timing_safe(self):
        # Both branches should return bool, not raise
        h = hash_password("x")
        result = verify_password("x", h)
        assert isinstance(result, bool)


class TestAuthenticate:
    def test_correct_credentials(self, monkeypatch):
        h = hash_password("secret")
        monkeypatch.setattr("server.auth._USERNAME",  "alice")
        monkeypatch.setattr("server.auth._PASS_HASH", h)
        assert authenticate("alice", "secret") is True

    def test_wrong_username(self, monkeypatch):
        monkeypatch.setattr("server.auth._USERNAME",  "alice")
        monkeypatch.setattr("server.auth._PASS_HASH", hash_password("secret"))
        assert authenticate("bob", "secret") is False

    def test_wrong_password(self, monkeypatch):
        monkeypatch.setattr("server.auth._USERNAME",  "alice")
        monkeypatch.setattr("server.auth._PASS_HASH", hash_password("secret"))
        assert authenticate("alice", "wrong") is False

    def test_default_admin_login(self, monkeypatch):
        monkeypatch.setattr("server.auth._USERNAME",  "admin")
        monkeypatch.setattr("server.auth._PASS_HASH", "")
        assert authenticate("admin", "admin") is True
