from pathlib import Path

import pytest

from docai.discovery.datatypes import FileOverride
from docai.discovery.ignore_rules import IgnoreRules


@pytest.mark.unit
class TestIgnoreRulesConstruction:
    def test_constructs_with_empty_list(self) -> None:
        rules = IgnoreRules([])
        assert isinstance(rules, IgnoreRules)

    def test_constructs_with_comment_only_lines(self) -> None:
        rules = IgnoreRules(["# this is a comment", "# another comment"])
        assert isinstance(rules, IgnoreRules)

    def test_constructs_with_blank_lines_only(self) -> None:
        rules = IgnoreRules(["", "   ", ""])
        assert isinstance(rules, IgnoreRules)

    def test_constructs_with_valid_patterns(self) -> None:
        rules = IgnoreRules(["node_modules/", "*.pyc", "dist/", ".env"])
        assert isinstance(rules, IgnoreRules)

    def test_constructs_with_mixed_comments_blanks_and_patterns(self) -> None:
        rules = IgnoreRules([
            "# Dependency directories",
            "node_modules/",
            "",
            "# Build output",
            "dist/",
            "*.pyc",
            "",
        ])
        assert isinstance(rules, IgnoreRules)


@pytest.mark.unit
class TestShouldPruneDirectory:
    def test_no_patterns_never_prunes(self) -> None:
        rules = IgnoreRules([])
        assert rules.should_prune_directory(Path("node_modules")) is False

    @pytest.mark.parametrize("pattern,directory", [
        ("node_modules/", "node_modules"),
        ("dist/",         "dist"),
        (".git/",         ".git"),
        ("__pycache__/",  "__pycache__"),
        ("build/",        "build"),
    ])
    def test_matching_directory_pattern_returns_true(
        self, pattern: str, directory: str
    ) -> None:
        rules = IgnoreRules([pattern])
        assert rules.should_prune_directory(Path(directory)) is True

    def test_non_matching_directory_returns_false(self) -> None:
        rules = IgnoreRules(["node_modules/", "dist/"])
        assert rules.should_prune_directory(Path("src")) is False

    def test_directory_specific_pattern_matches_directory(self) -> None:
        rules = IgnoreRules(["node_modules/"])
        assert rules.should_prune_directory(Path("node_modules")) is True

    def test_wildcard_pattern_matches_directory(self) -> None:
        rules = IgnoreRules(["build*/"])
        assert rules.should_prune_directory(Path("build-output")) is True

    def test_nested_path_matches_pattern(self) -> None:
        rules = IgnoreRules(["vendor/"])
        assert rules.should_prune_directory(Path("src/vendor")) is True

    def test_deeply_nested_path_matches_pattern(self) -> None:
        rules = IgnoreRules(["node_modules/"])
        assert rules.should_prune_directory(Path("a/b/c/node_modules")) is True

    def test_negation_unexcludes_directory(self) -> None:
        rules = IgnoreRules(["build/", "!build/"])
        assert rules.should_prune_directory(Path("build")) is False

    def test_file_extension_pattern_does_not_prune_directory(self) -> None:
        rules = IgnoreRules(["*.pyc"])
        assert rules.should_prune_directory(Path("foo.pyc")) is False

    def test_multiple_patterns_first_match_excludes(self) -> None:
        rules = IgnoreRules(["dist/", "node_modules/", "build/"])
        assert rules.should_prune_directory(Path("dist")) is True

    def test_multiple_patterns_no_match_returns_false(self) -> None:
        rules = IgnoreRules(["dist/", "node_modules/", "build/"])
        assert rules.should_prune_directory(Path("src")) is False


@pytest.mark.unit
class TestFileOverride:
    def test_no_patterns_returns_none(self) -> None:
        rules = IgnoreRules([])
        assert rules.file_override(Path("src/main.py")) is None

    @pytest.mark.parametrize("pattern,path", [
        ("*.log",       "app.log"),
        ("*.pyc",       "src/module.pyc"),
        ("secrets.env", "secrets.env"),
        (".env",        ".env"),
    ])
    def test_matched_exclusion_pattern_returns_exclude(
        self, pattern: str, path: str
    ) -> None:
        rules = IgnoreRules([pattern])
        assert rules.file_override(Path(path)) == FileOverride.exclude

    @pytest.mark.parametrize("pattern,path", [
        ("*.log",       "src/main.py"),
        ("*.pyc",       "README.md"),
        ("secrets.env", "config.yaml"),
    ])
    def test_unmatched_path_returns_none(self, pattern: str, path: str) -> None:
        rules = IgnoreRules([pattern])
        assert rules.file_override(Path(path)) is None

    def test_excluded_then_negated_returns_include(self) -> None:
        rules = IgnoreRules(["*.py", "!src/main.py"])
        assert rules.file_override(Path("src/main.py")) == FileOverride.include

    def test_negation_only_with_no_prior_exclusion_returns_none(self) -> None:
        rules = IgnoreRules(["!src/main.py"])
        assert rules.file_override(Path("src/main.py")) is None

    def test_last_pattern_wins_negation_then_exclusion_returns_exclude(self) -> None:
        rules = IgnoreRules(["!*.py", "*.py"])
        assert rules.file_override(Path("src/main.py")) == FileOverride.exclude

    def test_last_pattern_wins_exclusion_then_negation_returns_include(self) -> None:
        rules = IgnoreRules(["*.py", "!src/main.py"])
        assert rules.file_override(Path("src/main.py")) == FileOverride.include

    def test_multiple_exclusion_patterns_matching_one_returns_exclude(self) -> None:
        rules = IgnoreRules(["*.log", "*.tmp", "*.pyc"])
        assert rules.file_override(Path("debug.log")) == FileOverride.exclude

    def test_multiple_exclusion_patterns_matching_none_returns_none(self) -> None:
        rules = IgnoreRules(["*.log", "*.tmp", "*.pyc"])
        assert rules.file_override(Path("src/main.py")) is None

    def test_directory_pruning_pattern_does_not_affect_file_inside(self) -> None:
        rules = IgnoreRules(["node_modules/"])
        assert rules.file_override(Path("node_modules/lodash/index.js")) is None


@pytest.mark.unit
class TestFileOverrideSilencedNegationWarning:
    def test_silenced_negation_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        rules = IgnoreRules(["tests/", "!tests/test_this.py"])
        import logging
        with caplog.at_level(logging.WARNING, logger="docai.discovery.ignore_rules"):
            rules.file_override(Path("tests/test_this.py"))
        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "WARNING"
        assert caplog.records[0].message == (
            "Negation pattern has no effect: parent directory 'tests' is excluded. "
            "'tests/test_this.py' will not be force-included."
        )

    def test_silenced_negation_warning_contains_correct_parent_and_path(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        rules = IgnoreRules(["src/generated/", "!src/generated/types.py"])
        import logging
        with caplog.at_level(logging.WARNING, logger="docai.discovery.ignore_rules"):
            rules.file_override(Path("src/generated/types.py"))
        assert caplog.records[0].message == (
            "Negation pattern has no effect: parent directory 'src/generated' is excluded. "
            "'src/generated/types.py' will not be force-included."
        )

    def test_pruned_parent_exclude_result_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # path would be FileOverride.exclude (not a silenced negation)
        rules = IgnoreRules(["tests/", "*.py"])
        import logging
        with caplog.at_level(logging.WARNING, logger="docai.discovery.ignore_rules"):
            rules.file_override(Path("tests/test_this.py"))
        assert len(caplog.records) == 0

    def test_pruned_parent_no_match_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # path matches neither spec
        rules = IgnoreRules(["tests/"])
        import logging
        with caplog.at_level(logging.WARNING, logger="docai.discovery.ignore_rules"):
            rules.file_override(Path("tests/test_this.py"))
        assert len(caplog.records) == 0

    def test_same_path_warned_only_once(self, caplog: pytest.LogCaptureFixture) -> None:
        rules = IgnoreRules(["tests/", "!tests/test_this.py"])
        import logging
        with caplog.at_level(logging.WARNING, logger="docai.discovery.ignore_rules"):
            rules.file_override(Path("tests/test_this.py"))
            rules.file_override(Path("tests/test_this.py"))
        assert len(caplog.records) == 1

    def test_different_silenced_paths_each_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        rules = IgnoreRules(["tests/", "!tests/test_a.py", "!tests/test_b.py"])
        import logging
        with caplog.at_level(logging.WARNING, logger="docai.discovery.ignore_rules"):
            rules.file_override(Path("tests/test_a.py"))
            rules.file_override(Path("tests/test_b.py"))
        assert len(caplog.records) == 2
        assert caplog.records[0].message == (
            "Negation pattern has no effect: parent directory 'tests' is excluded. "
            "'tests/test_a.py' will not be force-included."
        )
        assert caplog.records[1].message == (
            "Negation pattern has no effect: parent directory 'tests' is excluded. "
            "'tests/test_b.py' will not be force-included."
        )

    def test_no_pruned_parent_exclude_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        rules = IgnoreRules(["*.py"])
        import logging
        with caplog.at_level(logging.WARNING, logger="docai.discovery.ignore_rules"):
            rules.file_override(Path("src/main.py"))
        assert len(caplog.records) == 0

    def test_no_pruned_parent_include_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        rules = IgnoreRules(["*.py", "!src/main.py"])
        import logging
        with caplog.at_level(logging.WARNING, logger="docai.discovery.ignore_rules"):
            rules.file_override(Path("src/main.py"))
        assert len(caplog.records) == 0
