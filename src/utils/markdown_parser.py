# src/utils/markdown_parser.py
"""Utility functions for parsing agent/skill markdown files.

The markdown files are expected to contain a YAML front‑matter block at the top,
 delimited by triple dashes (---). Example:

```yaml
---
name: my_agent
description: A sample agent
full_name: my_namespace/my_agent
operations:
  chat:
    - litellm_model: gpt-3.5-turbo
      api_key_env: OPENAI_API_KEY
restrictions:
  tpm: 50000
  rpm: 60
---
```

The rest of the file may contain documentation, which is ignored for the
runtime configuration.
"""

import re
from typing import Tuple, Dict, List

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_FRONTMATTER_RE = re.compile(r"^---\s*$", re.MULTILINE)


def extract_frontmatter(md_text: str) -> Tuple[Dict, str]:
    """Extract YAML front‑matter from a markdown string.

    Returns a tuple ``(metadata_dict, remaining_content)``. If no front‑matter is
    found, an empty dict is returned and the original text is considered the
    remaining content.
    """
    lines = md_text.splitlines()
    if not lines:
        return {}, ""
    if lines[0].strip() != "---":
        return {}, md_text
    # Find the closing delimiter
    try:
        end_idx = lines[1:].index("---") + 1
    except ValueError:
        # No closing delimiter – treat whole file as content
        return {}, md_text
    front_lines = lines[1:end_idx]
    front_text = "\n".join(front_lines)
    remaining = "\n".join(lines[end_idx + 1 :])
    if yaml is None:
        raise RuntimeError("PyYAML is required for markdown parsing")
    data = yaml.safe_load(front_text) or {}
    return data, remaining


def validate_agent_schema(data: Dict) -> Tuple[bool, List[str]]:
    """Very lightweight validation of the required fields.

    Returns ``(is_valid, error_list)``.
    Required keys for an agent configuration are:
    - ``full_name`` (str)
    - ``operations`` (dict) with at least one operation containing a list of
      model specifications.
    """
    errors: List[str] = []
    if not isinstance(data, dict):
        errors.append("Front‑matter must be a mapping")
        return False, errors
    if "full_name" not in data or not isinstance(data["full_name"], str):
        errors.append("Missing or invalid 'full_name' (required string)")
    if "operations" not in data or not isinstance(data["operations"], dict):
        errors.append("Missing or invalid 'operations' (required dict)")
    else:
        # Ensure at least one operation with a non‑empty model list
        has_models = any(
            isinstance(models, list) and len(models) > 0
            for models in data["operations"].values()
        )
        if not has_models:
            errors.append("'operations' must contain at least one operation with model definitions")
    return (len(errors) == 0), errors
