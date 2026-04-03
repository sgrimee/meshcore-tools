---
name: gen-test
description: Generate pytest tests for a source module following this project's conventions
user-invocable: true
---

Generate pytest tests for the specified module in `src/meshcore_tools/`.

- Mirror existing test structure: create or extend `tests/test_<module>.py`
- Use `pytest.mark.parametrize` for data-driven cases
- Test edge cases: empty input, malformed packets, zero coordinates, missing keys
- Reference `tests/test_decoder.py` and `tests/test_db.py` as style examples
- Keep fixtures minimal and inline unless reuse is obvious
- Do not mock internal modules — test real behavior where possible
