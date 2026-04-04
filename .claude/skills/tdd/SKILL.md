---
name: tdd
description: Test-driven development workflow for DocAI components. Use before implementing any component. Enters plan mode to build a scenario list, gets confirmation, writes tests, then verifies they fail for the right reasons.
---

You are starting a TDD workflow for a DocAI component. Follow these phases strictly and in order. Never skip ahead to writing code.

## Phase 1 — Enter Plan Mode

Immediately enter plan mode. Do not write any tests yet.

In plan mode, analyze the component under discussion and produce a structured scenario plan covering:

### 1. Inputs and outputs
For each public function/method/class:
- What are the valid inputs and what should be returned?
- What are the boundary cases (empty, None, zero, max, single item)?
- What types are involved?

### 2. Behavior and side effects
- What state changes happen (filesystem writes, dict mutations, internal state)?
- What are the ordering guarantees?
- What is deterministic vs non-deterministic?
- Are there async behaviors to verify?

### 3. Error cases
- What raises a `DocaiError` subclass? With what `code` and `message` pattern?
- What raises standard Python exceptions vs docai errors?
- What happens when dependencies fail?

### 4. Integration points
- Which external dependencies need mocking (LLM client, filesystem, etc.)?
- How do errors from dependencies surface through this component?

### 5. Marker assignments
Propose a marker for each test scenario:
- `unit` — pure function, no I/O, no external dependencies
- `integration` — touches real filesystem (fixture directories)
- `slow` — multi-stage or pipeline-level
- `llm` — uses mock LLM client
- `tree_sitter` — exercises tree-sitter parsing

Present the full scenario list as a numbered checklist. Wait for user confirmation before proceeding.

---

## Phase 2 — User Confirms Scenarios

Do not proceed until the user explicitly confirms the scenario list or requests changes. If they request changes, update the plan and re-present it. Only continue when they say the plan looks good.

---

## Phase 3 — Write the Tests

Exit plan mode and write the tests. Follow these conventions strictly:

### Structure
- Group tests in classes by behavior, not by function name: `TestHappyPath`, `TestErrorCases`, `TestEdgeCases`
- Class name describes what is being tested behaviorally
- Test method names describe the specific scenario: `test_returns_empty_list_when_no_files_found`

### Assertions
- **Always use exact string matching** — never check if a substring appears
- For `DocaiError`: assert exact `.code` and exact `.message`
- For error chains: assert `.__cause__` type and its `.code`
- Prefer `assert x == expected` over `assert x in container` unless membership is the actual behavior

### Markers
Apply the marker agreed in the plan to every test method:
```python
@pytest.mark.unit
def test_something(self) -> None:
    ...
```

### Async tests
No `@pytest.mark.asyncio` decorator needed — `asyncio_mode = auto` handles it:
```python
async def test_async_behavior(self) -> None:
    result = await some_async_function()
    assert result == expected
```

### Fixtures
Define fixtures in the test file unless they will be reused across multiple test files (then use `conftest.py`). Always use `yield` for fixtures that require teardown:
```python
@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    return tmp_path
```

Use `tmp_path` (pytest built-in) for filesystem fixtures — never hardcode `/tmp/`.

### Parametrize
Use `@pytest.mark.parametrize` when the same logic applies to 3+ input/output pairs. Use separate test methods when the scenarios have meaningfully different setups or assertions:
```python
@pytest.mark.parametrize("input_val,expected", [
    ("case_one", "result_one"),
    ("case_two", "result_two"),
    ("case_three", "result_three"),
])
def test_behavior_across_inputs(self, input_val: str, expected: str) -> None:
    assert transform(input_val) == expected
```

### Mocking LLM calls
Mock at the LiteLLM wrapper interface (`llm/client.py`), never deeper. Use `unittest.mock.patch` or pass a mock directly via dependency injection when the component accepts the client as a parameter:
```python
from unittest.mock import AsyncMock, patch

@pytest.mark.llm
async def test_llm_call_fails_gracefully(self) -> None:
    with patch("docai.llm.client.LLMClient.send") as mock_send:
        mock_send.side_effect = LLMError(message="rate limit", code="LLM_RATE_LIMIT")
        with pytest.raises(ExtractionError) as exc_info:
            await extractor.extract(file_path="src/foo.py")
        assert exc_info.value.code == "EXTRACTION_LLM_FAILED"
        assert exc_info.value.__cause__.code == "LLM_RATE_LIMIT"
```

### DocaiError assertions
```python
with pytest.raises(SomeDocaiError) as exc_info:
    function_under_test(bad_input)
assert exc_info.value.code == "EXPECTED_CODE"
assert exc_info.value.message == "exact expected message"
```

---

## Phase 4 — Verify Failures

After writing the tests, run them:

```bash
uv run pytest <test_file> -v
```

Check that every test:
1. **Fails** (not passes, not errors on import)
2. Fails for the **right reason** — `AttributeError: module has no attribute` or `TypeError` on construction means the implementation doesn't exist yet, which is correct. An `AssertionError` on a wrong value is also correct. An `ImportError` is a problem — fix the import before proceeding.

Report which tests fail and why. If any test passes unexpectedly, flag it — either the test is wrong or there is already an implementation.

---

## Phase 5 — Handoff Summary

Present a concise implementation checklist: what the tests require the implementation to provide, with no extra detail. This is the spec the implementation must satisfy.

Example:
```
Implementation must:
- [ ] Accept `file_path: str` and `manifest: dict[str, ManifestEntry]`
- [ ] Return `FileAnalysis` with `file_type`, `entities`, `dependencies`
- [ ] Raise `ExtractionError(code="EXTRACTION_PARSE_FAILED")` when tree-sitter produces ERROR nodes after retries
- [ ] Preserve the original `LLMError` as `__cause__` on any raised `ExtractionError`
```
