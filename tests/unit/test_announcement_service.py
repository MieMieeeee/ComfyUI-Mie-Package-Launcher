"""
Tests for services.announcement_service module.

Tests the AnnouncementService class that manages announcements fetching,
filtering, caching, and display.
"""

import json
import threading
from datetime import datetime, timedelta
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import MagicMock, patch, Mock

import pytest


class TestAnnouncementServiceInit:
    """Test AnnouncementService initialization."""

    def test_init_assigns_app(self):
        """AnnouncementService should assign the app instance."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        assert service.app is app

    def test_init_sets_built_in_sources(self):
        """AnnouncementService should set built-in source URLs."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        assert hasattr(service, "_built_in_sources")
        assert isinstance(service._built_in_sources, list)
        assert len(service._built_in_sources) > 0
        assert any("gitee.com" in url for url in service._built_in_sources)

    def test_init_sets_last_data_to_none(self):
        """AnnouncementService should initialize _last_data to None."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        assert service._last_data is None


class TestLog:
    """Test the _log method."""

    def test_log_with_valid_logger(self):
        """_log should call the logger's method when logger exists."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.logger = MagicMock()
        service = AnnouncementService(app)

        service._log("info", "test message %s", "arg")

        app.logger.info.assert_called_once_with("test message %s", "arg")

    def test_log_with_missing_logger(self):
        """_log should not raise when app has no logger."""
        from services.announcement_service import AnnouncementService

        app = MagicMock(spec=["config"])
        del app.logger
        service = AnnouncementService(app)

        # Should not raise
        service._log("info", "test message")

    def test_log_with_invalid_level(self):
        """_log should fall back to info when level is invalid."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.logger = MagicMock()
        # Make invalid_level return None so it falls back to info
        del app.logger.invalid_level
        service = AnnouncementService(app)

        service._log("invalid_level", "test message")

        app.logger.info.assert_called_once_with("test message")


class TestGetSources:
    """Test the _get_sources method."""

    def test_get_sources_from_config_source_url(self):
        """_get_sources should return config source_url when set."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {
            "announcement": {"source_url": "https://example.com/announcements"}
        }
        service = AnnouncementService(app)

        sources = service._get_sources()

        assert "https://example.com/announcements" in sources

    def test_get_sources_includes_fallback_urls(self):
        """_get_sources should include fallback_urls from config."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {
            "announcement": {
                "source_url": "https://primary.com/announcements",
                "fallback_urls": ["https://backup1.com/ann", "https://backup2.com/ann"],
            }
        }
        service = AnnouncementService(app)

        sources = service._get_sources()

        assert "https://primary.com/announcements" in sources
        assert "https://backup1.com/ann" in sources
        assert "https://backup2.com/ann" in sources

    def test_get_sources_returns_builtin_when_empty(self):
        """_get_sources should return built-in sources when no config."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {}
        service = AnnouncementService(app)

        sources = service._get_sources()

        for src in service._built_in_sources:
            assert src in sources

    def test_get_sources_filters_empty_strings(self):
        """_get_sources should filter out empty or whitespace-only URLs."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {
            "announcement": {
                "source_url": "   ",
                "fallback_urls": ["", "  ", "https://valid.com/ann"],
            }
        }
        service = AnnouncementService(app)

        sources = service._get_sources()

        assert "https://valid.com/ann" in sources
        assert len(sources) == 1


class TestGetCacheFile:
    """Test the _get_cache_file method."""

    def test_get_cache_file_returns_path_in_launcher_dir(self):
        """_get_cache_file should return path in launcher directory."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        with patch("pathlib.Path.mkdir") as mock_mkdir:
            cache_file = service._get_cache_file()

        assert cache_file.name == "announcement_cache.txt"
        assert "launcher" in str(cache_file)


class TestGetSeenFile:
    """Test the _get_seen_file method."""

    def test_get_seen_file_returns_path_in_launcher_dir(self):
        """_get_seen_file should return path in launcher directory."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        with patch("pathlib.Path.mkdir") as mock_mkdir:
            seen_file = service._get_seen_file()

        assert seen_file.name == "announcement_seen.json"
        assert "launcher" in str(seen_file)


class TestLoadSeen:
    """Test the _load_seen method."""

    def test_load_seen_returns_empty_set_when_file_missing(self):
        """_load_seen should return empty set when seen file doesn't exist."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        with patch.object(service, "_get_seen_file") as mock_get_seen:
            mock_file = MagicMock()
            mock_file.exists.return_value = False
            mock_get_seen.return_value = mock_file

            result = service._load_seen()

        assert result == set()

    def test_load_seen_returns_set_from_json_file(self):
        """_load_seen should return set of IDs from seen file."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        with patch.object(service, "_get_seen_file") as mock_get_seen:
            mock_file = MagicMock()
            mock_file.exists.return_value = True
            mock_file.read_text.return_value = json.dumps(["id1", "id2", "id3"])
            mock_get_seen.return_value = mock_file

            result = service._load_seen()

        assert result == {"id1", "id2", "id3"}

    def test_load_seen_handles_invalid_json(self):
        """_load_seen should return empty set on invalid JSON."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        with patch.object(service, "_get_seen_file") as mock_get_seen:
            mock_file = MagicMock()
            mock_file.exists.return_value = True
            mock_file.read_text.side_effect = json.JSONDecodeError("error", "", 0)
            mock_get_seen.return_value = mock_file

            result = service._load_seen()

        assert result == set()


class TestMarkSeen:
    """Test the _mark_seen method."""

    def test_mark_seen_appends_new_id(self):
        """_mark_seen should append new ID to seen list."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        with patch.object(service, "_get_seen_file") as mock_get_seen:
            mock_file = MagicMock()
            mock_file.exists.return_value = True
            mock_file.read_text.return_value = json.dumps(["existing_id"])
            mock_get_seen.return_value = mock_file

            service._mark_seen("new_id")

            mock_file.write_text.assert_called_once()
            written_content = json.loads(mock_file.write_text.call_args[0][0])
            assert "existing_id" in written_content
            assert "new_id" in written_content

    def test_mark_seen_does_not_duplicate_id(self):
        """_mark_seen should not duplicate an already seen ID."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        with patch.object(service, "_get_seen_file") as mock_get_seen:
            mock_file = MagicMock()
            mock_file.exists.return_value = True
            mock_file.read_text.return_value = json.dumps(["existing_id"])
            mock_get_seen.return_value = mock_file

            service._mark_seen("existing_id")

            # write_text should NOT be called because ID is already in list
            mock_file.write_text.assert_not_called()


class TestComputeId:
    """Test the _compute_id method."""

    def test_compute_id_returns_consistent_hash(self):
        """_compute_id should return consistent SHA256 hash for same data."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        data = {"title": "Test", "content": "Content", "source": "https://example.com"}

        id1 = service._compute_id(data)
        id2 = service._compute_id(data)

        assert id1 == id2
        assert len(id1) == 64  # SHA256 hex length

    def test_compute_id_different_for_different_data(self):
        """_compute_id should return different hash for different data."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        data1 = {
            "title": "Test1",
            "content": "Content",
            "source": "https://example.com",
        }
        data2 = {
            "title": "Test2",
            "content": "Content",
            "source": "https://example.com",
        }

        id1 = service._compute_id(data1)
        id2 = service._compute_id(data2)

        assert id1 != id2

    def test_compute_id_handles_missing_fields(self):
        """_compute_id should handle missing fields gracefully."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        data = {}

        result = service._compute_id(data)

        assert isinstance(result, str)
        assert len(result) == 64


class TestFetch:
    """Test the fetch method."""

    def test_fetch_returns_none_when_all_sources_fail(self):
        """fetch should return None when all URL sources fail."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {}
        service = AnnouncementService(app)

        with patch.object(service, "_get_sources", return_value=["https://fail.com"]):
            with patch(
                "services.announcement_service.urlopen",
                side_effect=Exception("Network error"),
            ):
                result = service.fetch()

        assert result is None

    def test_fetch_parses_json_index_with_items(self):
        """fetch should parse JSON index with items array."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {}
        service = AnnouncementService(app)

        index_data = {
            "items": [
                {"title": "Ann1", "content": "Content1"},
                {"title": "Ann2", "content": "Content2"},
            ]
        }

        with patch.object(
            service, "_get_sources", return_value=["https://example.com"]
        ):
            with patch("services.announcement_service.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.read.return_value = json.dumps(index_data).encode("utf-8")
                mock_response.__enter__ = MagicMock(return_value=mock_response)
                mock_response.__exit__ = MagicMock(return_value=False)
                mock_urlopen.return_value = mock_response

                with patch.object(service, "_is_allowed", return_value=True):
                    with patch.object(service, "_in_time_window", return_value=True):
                        result = service.fetch()

        assert result is not None
        assert "公告" in result["title"]
        assert len(result["content"]) > 0

    def test_fetch_returns_none_for_empty_response(self):
        """fetch should skip empty responses and continue to next source."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {}
        service = AnnouncementService(app)

        with patch.object(
            service,
            "_get_sources",
            return_value=["https://empty.com", "https://valid.com"],
        ):
            with patch("services.announcement_service.urlopen") as mock_urlopen:
                # First response empty
                mock_response1 = MagicMock()
                mock_response1.read.return_value = b""
                mock_response1.__enter__ = MagicMock(return_value=mock_response1)
                mock_response1.__exit__ = MagicMock(return_value=False)

                # Second response valid
                mock_response2 = MagicMock()
                mock_response2.read.return_value = json.dumps(
                    {"title": "Test", "content": "Test content"}
                ).encode("utf-8")
                mock_response2.__enter__ = MagicMock(return_value=mock_response2)
                mock_response2.__exit__ = MagicMock(return_value=False)

                mock_urlopen.side_effect = [mock_response1, mock_response2]

                with patch.object(service, "_is_allowed", return_value=True):
                    with patch.object(service, "_in_time_window", return_value=True):
                        result = service.fetch()

        assert result is not None
        assert result["title"] == "Test"

    def test_fetch_handles_plain_text_response(self):
        """fetch should handle plain text (non-JSON) responses."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {}
        service = AnnouncementService(app)

        with patch.object(service, "_get_sources", return_value=["https://text.com"]):
            with patch("services.announcement_service.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.read.return_value = b"Just plain text announcement"
                mock_response.__enter__ = MagicMock(return_value=mock_response)
                mock_response.__exit__ = MagicMock(return_value=False)
                mock_urlopen.return_value = mock_response

                result = service.fetch()

        assert result is not None
        assert result["title"] == "公告"
        assert result["content"] == "Just plain text announcement"

    def test_fetch_returns_none_for_empty_payload_when_all_sources_empty(self):
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {}
        app.logger = MagicMock()
        service = AnnouncementService(app)

        with patch.object(service, "_get_sources", return_value=["https://empty.com"]):
            with patch("services.announcement_service.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.read.return_value = b""
                mock_response.__enter__ = MagicMock(return_value=mock_response)
                mock_response.__exit__ = MagicMock(return_value=False)
                mock_urlopen.return_value = mock_response

                result = service.fetch()

        assert result is None
        app.logger.warning.assert_called()

    def test_fetch_returns_none_for_malformed_json_payload(self):
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {}
        app.logger = MagicMock()
        service = AnnouncementService(app)

        with patch.object(
            service, "_get_sources", return_value=["https://bad-json.com"]
        ):
            with patch("services.announcement_service.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.read.return_value = b'{"title":'
                mock_response.__enter__ = MagicMock(return_value=mock_response)
                mock_response.__exit__ = MagicMock(return_value=False)
                mock_urlopen.return_value = mock_response

                result = service.fetch()

        assert result is None
        app.logger.warning.assert_called()

    def test_fetch_returns_none_for_http_error(self):
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {}
        service = AnnouncementService(app)

        with patch.object(service, "_get_sources", return_value=["https://fail.com"]):
            with patch(
                "services.announcement_service.urlopen",
                side_effect=HTTPError(
                    "https://fail.com", 500, "server error", Message(), None
                ),
            ):
                result = service.fetch()

        assert result is None


class TestLoadBuildParams:
    """Test the _load_build_params method."""

    def test_load_build_params_returns_dict(self):
        """_load_build_params should return a dict with version and mode."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        with patch("sys._MEIPASS", "", create=True):
            with patch("sys.executable", "/usr/bin/python"):
                with patch("builtins.open", side_effect=FileNotFoundError()):
                    result = service._load_build_params()

        assert isinstance(result, dict)
        assert "version" in result
        assert "mode" in result


class TestVersionTuple:
    """Test the _version_tuple method."""

    def test_version_tuple_parses_simple_version(self):
        """_version_tuple should parse simple semver string."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        result = service._version_tuple("1.2.3")

        assert result == (1, 2, 3)

    def test_version_tuple_strips_v_prefix(self):
        """_version_tuple should strip 'v' or 'V' prefix."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        result = service._version_tuple("v1.2.3")

        assert result == (1, 2, 3)

    def test_version_tuple_handles_partial_version(self):
        """_version_tuple should pad partial versions with zeros."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        result = service._version_tuple("1.2")

        assert result == (1, 2, 0)

    def test_version_tuple_handles_non_numeric_parts(self):
        """_version_tuple should handle non-numeric version parts."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        # "beta" has no digits, becomes 0
        result = service._version_tuple("1.2.beta")

        assert result == (1, 2, 0)


class TestMatchVersionExpr:
    """Test the _match_version_expr method."""

    def test_match_version_expr_wildcard(self):
        """_match_version_expr should return True for '*'."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        assert service._match_version_expr("*", (1, 2, 3)) is True

    def test_match_version_expr_exact_match(self):
        """_match_version_expr should match exact version with == ."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        assert service._match_version_expr("1.2.3", (1, 2, 3)) is True
        assert service._match_version_expr("==1.2.3", (1, 2, 3)) is True
        assert service._match_version_expr("==1.2.3", (1, 2, 4)) is False

    def test_match_version_expr_greater_than(self):
        """_match_version_expr should match > operator."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        assert service._match_version_expr(">1.2.3", (1, 2, 4)) is True
        assert service._match_version_expr(">1.2.3", (1, 2, 3)) is False
        assert service._match_version_expr(">1.2.3", (1, 2, 2)) is False

    def test_match_version_expr_less_than(self):
        """_match_version_expr should match < operator."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        assert service._match_version_expr("<1.2.4", (1, 2, 3)) is True
        assert service._match_version_expr("<1.2.4", (1, 2, 4)) is False

    def test_match_version_expr_greater_than_or_equal(self):
        """_match_version_expr should match >= operator."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        assert service._match_version_expr(">=1.2.3", (1, 2, 3)) is True
        assert service._match_version_expr(">=1.2.3", (1, 2, 4)) is True
        assert service._match_version_expr(">=1.2.3", (1, 2, 2)) is False

    def test_match_version_expr_less_than_or_equal(self):
        """_match_version_expr should match <= operator."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        assert service._match_version_expr("<=1.2.3", (1, 2, 3)) is True
        assert service._match_version_expr("<=1.2.3", (1, 2, 2)) is True
        assert service._match_version_expr("<=1.2.3", (1, 2, 4)) is False

    def test_match_version_expr_multiple_conditions(self):
        """_match_version_expr should support multiple conditions with spaces."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        # Should be >= 1.2.0 AND <= 1.3.0
        assert service._match_version_expr(">=1.2.0 <=1.3.0", (1, 2, 5)) is True
        assert service._match_version_expr(">=1.2.0 <=1.3.0", (1, 4, 0)) is False


class TestIsAllowed:
    """Test the _is_allowed method."""

    def test_is_allowed_returns_true_when_no_rules(self):
        """_is_allowed should return True when rules dict is empty."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        with patch.object(
            service, "_load_build_params", return_value={"version": "1.0.0", "mode": ""}
        ):
            result = service._is_allowed({})

        assert result is True

    def test_is_allowed_blocks_by_min_version(self):
        """_is_allowed should block when current version is below min_version."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        with patch.object(
            service, "_load_build_params", return_value={"version": "1.0.0", "mode": ""}
        ):
            result = service._is_allowed({"min_version": "2.0.0"})

        assert result is False

    def test_is_allowed_allows_within_min_max_range(self):
        """_is_allowed should allow when version is within range."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        with patch.object(
            service, "_load_build_params", return_value={"version": "1.5.0", "mode": ""}
        ):
            result = service._is_allowed(
                {"min_version": "1.0.0", "max_version": "2.0.0"}
            )

        assert result is True

    def test_is_allowed_blocks_denied_version(self):
        """_is_allowed should block when version is in deny_versions list."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        with patch.object(
            service, "_load_build_params", return_value={"version": "1.0.0", "mode": ""}
        ):
            result = service._is_allowed({"deny_versions": ["1.0.0", "1.1.0"]})

        assert result is False

    def test_is_allowed_allows_allowed_version(self):
        """_is_allowed should allow when version is in allow_versions list."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        with patch.object(
            service, "_load_build_params", return_value={"version": "1.0.0", "mode": ""}
        ):
            result = service._is_allowed({"allow_versions": ["1.0.0", "2.0.0"]})

        assert result is True

    def test_is_allowed_blocks_version_not_in_allow_list(self):
        """_is_allowed should block when version is not in allow_versions list."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        with patch.object(
            service, "_load_build_params", return_value={"version": "1.5.0", "mode": ""}
        ):
            result = service._is_allowed({"allow_versions": ["1.0.0", "2.0.0"]})

        assert result is False


class TestInTimeWindow:
    """Test the _in_time_window method."""

    def test_in_time_window_returns_true_when_no_times_set(self):
        """_in_time_window should return True when start_at and end_at are not set."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        result = service._in_time_window({})

        assert result is True

    def test_in_time_window_returns_true_when_within_window(self):
        """_in_time_window should return True when current time is within window."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        past = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        future = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")

        result = service._in_time_window({"start_at": past, "end_at": future})

        assert result is True

    def test_in_time_window_returns_false_when_before_start(self):
        """_in_time_window should return False when before start_at."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        future = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")

        result = service._in_time_window({"start_at": future})

        assert result is False

    def test_in_time_window_returns_false_when_after_end(self):
        """_in_time_window should return False when after end_at."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        past = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

        result = service._in_time_window({"end_at": past})

        assert result is False


class TestShowIfAvailable:
    """Test the show_if_available method."""

    def test_show_if_available_skips_when_disabled(self):
        """show_if_available should return early when announcements are disabled."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {"announcement": {"enabled": False}}
        service = AnnouncementService(app)

        with patch.object(service, "fetch") as mock_fetch:
            service.show_if_available()
            mock_fetch.assert_not_called()

    def test_show_if_available_fetches_and_shows_popup(self):
        """show_if_available should fetch data and show popup when available."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {"announcement": {"enabled": True}}
        app.ui_post = MagicMock()
        service = AnnouncementService(app)

        fetched_data = {
            "title": "Test Announcement",
            "content": "Test content",
            "source": "https://example.com",
            "rules": {},
        }

        with patch.object(service, "fetch", return_value=fetched_data):
            with patch.object(service, "_is_allowed", return_value=True):
                with patch.object(service, "_load_seen", return_value=set()):
                    with patch.object(service, "_get_seen_file") as mock_get_seen:
                        mock_file = MagicMock()
                        mock_file.parent = MagicMock()
                        mock_get_seen.return_value = mock_file

                        with patch("pathlib.Path.exists", return_value=False):
                            with patch("threading.Thread") as mock_thread:
                                service.show_if_available()

                                # Verify thread was started
                                mock_thread.assert_called_once()
                                # Start the worker function that was passed to Thread
                                worker_func = mock_thread.call_args[1]["target"]
                                worker_func()

                        # ui_post should be called to show popup
                        app.ui_post.assert_called()

    def test_show_if_available_uses_cache_when_fetch_returns_none(self):
        """show_if_available should use cache when fetch returns None."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {"announcement": {"enabled": True}}
        app.ui_post = MagicMock()
        service = AnnouncementService(app)

        with patch.object(service, "fetch", return_value=None):
            with patch.object(service, "_get_cache_file") as mock_cache:
                mock_cache_file = MagicMock()
                mock_cache_file.exists.return_value = True
                mock_cache_file.read_text.return_value = "Cached announcement content"
                mock_cache.return_value = mock_cache_file

                service.show_if_available()

                # Should use ui_post to show cache
                app.ui_post.assert_called()

    def test_show_if_available_preserves_existing_cache_on_empty_payload(
        self, tmp_path
    ):
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {"announcement": {"enabled": True}}
        app.ui_post = MagicMock()
        app.logger = MagicMock()
        service = AnnouncementService(app)

        cache_file = tmp_path / "announcement_cache.txt"
        cache_file.write_text("Cached announcement content", encoding="utf-8")

        with patch.object(service, "_get_cache_file", return_value=cache_file):
            with patch.object(
                service, "_get_sources", return_value=["https://empty.com"]
            ):
                with patch("services.announcement_service.urlopen") as mock_urlopen:
                    mock_response = MagicMock()
                    mock_response.read.return_value = b""
                    mock_response.__enter__ = MagicMock(return_value=mock_response)
                    mock_response.__exit__ = MagicMock(return_value=False)
                    mock_urlopen.return_value = mock_response

                    with patch("threading.Thread") as mock_thread:
                        service.show_if_available()
                        worker_func = mock_thread.call_args[1]["target"]
                        worker_func()

        assert cache_file.read_text(encoding="utf-8") == "Cached announcement content"
        app.ui_post.assert_called()

    def test_show_if_available_preserves_existing_cache_on_malformed_json(
        self, tmp_path
    ):
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {"announcement": {"enabled": True}}
        app.ui_post = MagicMock()
        app.logger = MagicMock()
        service = AnnouncementService(app)

        cache_file = tmp_path / "announcement_cache.txt"
        cache_file.write_text("Cached announcement content", encoding="utf-8")

        with patch.object(service, "_get_cache_file", return_value=cache_file):
            with patch.object(
                service, "_get_sources", return_value=["https://bad-json.com"]
            ):
                with patch("services.announcement_service.urlopen") as mock_urlopen:
                    mock_response = MagicMock()
                    mock_response.read.return_value = b'{"title":'
                    mock_response.__enter__ = MagicMock(return_value=mock_response)
                    mock_response.__exit__ = MagicMock(return_value=False)
                    mock_urlopen.return_value = mock_response

                    with patch("threading.Thread") as mock_thread:
                        service.show_if_available()
                        worker_func = mock_thread.call_args[1]["target"]
                        worker_func()

        assert cache_file.read_text(encoding="utf-8") == "Cached announcement content"
        app.ui_post.assert_called()

    def test_show_if_available_preserves_existing_cache_on_timeout(self, tmp_path):
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {"announcement": {"enabled": True}}
        app.ui_post = MagicMock()
        service = AnnouncementService(app)

        cache_file = tmp_path / "announcement_cache.txt"
        cache_file.write_text("Cached announcement content", encoding="utf-8")

        with patch.object(service, "_get_cache_file", return_value=cache_file):
            with patch.object(service, "fetch", return_value=None):
                with patch("threading.Thread") as mock_thread:
                    service.show_if_available()
                    worker_func = mock_thread.call_args[1]["target"]
                    worker_func()

        assert cache_file.read_text(encoding="utf-8") == "Cached announcement content"
        app.ui_post.assert_called()

    def test_show_if_available_skips_already_seen(self):
        """show_if_available should skip already-seen announcements."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {"announcement": {"enabled": True}}
        service = AnnouncementService(app)

        fetched_data = {
            "title": "Test",
            "content": "Test content",
            "source": "https://example.com",
            "rules": {},
        }

        with patch.object(service, "fetch", return_value=fetched_data):
            with patch.object(service, "_compute_id", return_value="already_seen_id"):
                with patch.object(service, "_is_allowed", return_value=True):
                    with patch.object(
                        service, "_load_seen", return_value={"already_seen_id"}
                    ):
                        service.show_if_available()

    def test_show_if_available_skips_muted(self):
        """show_if_available should skip muted announcements."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.config = {"announcement": {"enabled": True}}
        service = AnnouncementService(app)

        fetched_data = {
            "title": "Test",
            "content": "Test content",
            "source": "https://example.com",
            "rules": {},
        }

        with patch.object(service, "fetch", return_value=fetched_data):
            with patch.object(service, "_compute_id", return_value="muted_id"):
                with patch.object(service, "_is_allowed", return_value=True):
                    with patch.object(service, "_load_seen", return_value=set()):
                        with patch.object(service, "_get_seen_file") as mock_get_seen:
                            mock_seen_file = MagicMock()
                            mock_seen_file.parent = MagicMock()
                            mock_seen_file.exists.return_value = True
                            mock_muted_file = MagicMock()
                            mock_muted_file.exists.return_value = True
                            mock_muted_file.read_text.return_value = json.dumps(
                                ["muted_id"]
                            )
                            mock_seen_file.parent.__truediv__ = MagicMock(
                                return_value=mock_muted_file
                            )
                            mock_get_seen.return_value = mock_seen_file

                            service.show_if_available()

    def test_show_if_available_uses_root_after_when_ui_post_missing(self):
        from services.announcement_service import AnnouncementService

        app = MagicMock(spec=["config", "root", "logger"])
        app.config = {"announcement": {"enabled": True}}
        app.root = MagicMock()
        app.logger = MagicMock()
        service = AnnouncementService(app)

        fetched_data = {
            "title": "Test",
            "content": "Test content",
            "source": "https://example.com",
            "rules": {},
        }

        with patch.object(service, "fetch", return_value=fetched_data):
            with patch.object(service, "_is_allowed", return_value=True):
                with patch.object(service, "_load_seen", return_value=set()):
                    with patch.object(service, "_get_seen_file") as mock_get_seen:
                        mock_seen_file = MagicMock()
                        mock_seen_file.parent = MagicMock()
                        mock_get_seen.return_value = mock_seen_file

                        with patch("pathlib.Path.exists", return_value=False):
                            with patch("threading.Thread") as mock_thread:
                                service.show_if_available()
                                worker_func = mock_thread.call_args[1]["target"]
                                worker_func()

        app.root.after.assert_called()
        after_args = app.root.after.call_args[0]
        assert after_args[0] == 0
        assert callable(after_args[1])
        assert (
            not hasattr(app.root, "after_idle") or app.root.after_idle.call_count == 0
        )


class TestShowCachedPopup:
    """Test the show_cached_popup method."""

    def test_show_cached_popup_uses_last_data_if_available(self):
        """show_cached_popup should use _last_data if available."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)

        setattr(
            service,
            "_last_data",
            {
                "title": "Cached",
                "content": "Cached content",
                "source": "cache",
            },
        )

        with patch("ui_qt.widgets.announcement_dialog.AnnouncementDialog"):
            with patch.object(service, "_get_main_window", return_value=None):
                service.show_cached_popup()

    def test_show_cached_popup_reads_from_cache_file(self):
        """show_cached_popup should read from cache file if no _last_data."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)
        service._last_data = None

        with patch.object(service, "_get_cache_file") as mock_cache:
            mock_cache_file = MagicMock()
            mock_cache_file.exists.return_value = True
            mock_cache_file.read_text.return_value = "File cached content"
            mock_cache.return_value = mock_cache_file

            with patch("ui_qt.widgets.announcement_dialog.AnnouncementDialog"):
                with patch.object(service, "_get_main_window", return_value=None):
                    service.show_cached_popup()

    def test_show_cached_popup_shows_info_when_no_cache(self):
        """show_cached_popup should show info dialog when no cache available."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        service = AnnouncementService(app)
        service._last_data = None

        with patch.object(service, "_get_cache_file") as mock_cache:
            mock_cache_file = MagicMock()
            mock_cache_file.exists.return_value = False
            mock_cache.return_value = mock_cache_file

            with patch(
                "ui_qt.widgets.dialog_helper.DialogHelper.show_info"
            ) as mock_show_info:
                with patch.object(service, "_get_main_window", return_value=None):
                    service.show_cached_popup()

                mock_show_info.assert_called_once()


class TestGetMainWindow:
    """Test the _get_main_window method."""

    def test_get_main_window_returns_self_if_qmainwindow(self):
        """_get_main_window should return self if app is QMainWindow."""
        from services.announcement_service import AnnouncementService
        from PyQt5 import QtWidgets

        app = MagicMock(spec=QtWidgets.QMainWindow)
        service = AnnouncementService(app)

        result = service._get_main_window()

        assert result is app

    def test_get_main_window_returns_window_attribute(self):
        """_get_main_window should return window attribute if available."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        app.window = "main_window_instance"
        service = AnnouncementService(app)

        result = service._get_main_window()

        assert result == "main_window_instance"

    def test_get_main_window_returns_none_when_not_available(self):
        """_get_main_window should return None when no window available."""
        from services.announcement_service import AnnouncementService

        app = MagicMock()
        del app.window
        service = AnnouncementService(app)

        result = service._get_main_window()

        assert result is None
