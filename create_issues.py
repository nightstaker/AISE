#!/usr/bin/env python3
"""Create GitHub issues for security and code quality findings.

Run with: GITHUB_TOKEN=<your-token> python3 create_issues.py
Or with gh CLI: gh auth login && python3 create_issues.py --use-gh
"""

from __future__ import annotations

import json
import subprocess
import sys

REPO = "NightStaker/AISE"

ISSUES = [
    {
        "title": "Security: No input sanitization in code generation allows injection via feature names",
        "labels": ["security"],
        "body": """\
## Summary

`src/aise/skills/developer/code_generation.py` generates Python source code by directly interpolating
user-derived feature names into string-based code templates without any sanitization. Malicious or
malformed feature names containing characters like `"`, `\\n`, `\\`, or Python keywords can produce
invalid or exploitable generated code.

## Location

- `src/aise/skills/developer/code_generation.py` — `_generate_python_module()` and `_generate_python_service()`

## Details

Feature names from user-submitted requirements flow through the pipeline into code generation where
they are used as:
- Python class names (`_to_class_name()` only capitalizes words, does not filter special chars)
- Module names (lowercased without sanitization)
- Route path segments

For example, a feature name like `User"; import os; os.system("rm -rf /")#` would be interpolated
directly into generated Python string literals and class definitions.

## Impact

- Generated code could contain syntax errors, or in worst case, embedded code injection
- Since this is an LLM-assisted development tool that produces source code, generated artifacts
  could be copy-pasted or executed by users

## Recommendation

1. Add an `_sanitize_identifier()` method that strips non-alphanumeric characters and ensures
   valid Python identifiers (using `str.isidentifier()`)
2. Validate and escape feature names before use in code templates
3. Consider using a proper templating engine (e.g., Jinja2) with auto-escaping instead of
   string concatenation
""",
    },
    {
        "title": "Security: Webhook server has no request signature verification",
        "labels": ["security"],
        "body": """\
## Summary

The WhatsApp webhook server (`src/aise/whatsapp/webhook.py`) accepts incoming POST requests without
verifying the `X-Hub-Signature-256` header that Meta sends with every webhook payload. This means
any party who discovers the webhook URL can inject fake messages.

## Location

- `src/aise/whatsapp/webhook.py` — `WebhookHandler.do_POST()` (line 57)
- `src/aise/whatsapp/client.py` — `process_webhook_payload()` (line 145)

## Details

Meta's WhatsApp Business API sends an HMAC-SHA256 signature in the `X-Hub-Signature-256` header for
every webhook POST request. The server should:

1. Read the `X-Hub-Signature-256` header
2. Compute HMAC-SHA256 of the raw request body using the app secret
3. Compare the computed signature against the header value
4. Reject requests where the signature does not match

Currently, the `do_POST` handler reads `Content-Length` and body, parses JSON, and passes directly
to `process_webhook_payload()` with no signature check.

The GET verification (`verify_webhook`) checks the `verify_token` parameter, but this only protects
the subscription handshake, not ongoing message delivery.

## Impact

- **Message injection:** An attacker can send fabricated webhook payloads that appear as if they
  came from legitimate WhatsApp users
- **Spoofed commands:** Fake messages could trigger agent workflows, inject malicious requirements,
  or impersonate group owners
- This is especially dangerous because the server binds to `0.0.0.0` by default (line 118)

## Recommendation

1. Add `app_secret` to `WhatsAppConfig`
2. In `do_POST`, verify the `X-Hub-Signature-256` header before processing
3. Return 403 for requests with invalid or missing signatures
4. Consider adding IP allowlisting for Meta's webhook IP ranges as defense-in-depth
""",
    },
    {
        "title": "Security: Webhook server binds to 0.0.0.0 by default exposing endpoint to all interfaces",
        "labels": ["security"],
        "body": """\
## Summary

The `WebhookServer` in `src/aise/whatsapp/webhook.py` defaults to binding on `0.0.0.0` (all network
interfaces), exposing the webhook endpoint to the entire network.

## Location

- `src/aise/whatsapp/webhook.py` — `WebhookServer.__init__()` line 118: `host: str = "0.0.0.0"`

## Details

Binding to `0.0.0.0` makes the webhook reachable from any network interface on the host machine,
including public-facing interfaces. For a development/testing tool, this is an overly permissive default.

Combined with the missing webhook signature verification (separate issue), this means any machine on
the network can send arbitrary webhook payloads that will be processed as legitimate WhatsApp messages.

## Recommendation

1. Change the default host to `127.0.0.1` (localhost only)
2. Require explicit opt-in to bind to `0.0.0.0` via configuration
""",
    },
    {
        "title": "Security: API access tokens passed via CLI arguments are visible in process listings",
        "labels": ["security"],
        "body": """\
## Summary

The WhatsApp `--access-token` CLI argument allows API tokens to be passed on the command line, which
exposes them in process listings (`ps aux`), shell history, and process monitoring tools.

## Location

- `src/aise/main.py` — lines 172-175: `wa_parser.add_argument("--access-token", ...)`
- `src/aise/config.py` — `ModelConfig.api_key` field (line 19), `WhatsAppConfig.access_token` (line 48)

## Details

Sensitive tokens are accepted via CLI arguments:
```bash
aise whatsapp --access-token "EAABsbCS..." --verify-token "my-secret"
```

This exposes the tokens in:
- `ps aux` output visible to all users on the system
- `/proc/PID/cmdline` on Linux
- Shell history files (~/.bash_history, ~/.zsh_history)
- Process monitoring and logging tools

## Recommendation

1. Read tokens from environment variables by default: `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_VERIFY_TOKEN`
2. Support reading from a config file with restricted permissions
3. If CLI arguments must be supported, document the security implications
4. Never log or display token values
""",
    },
    {
        "title": "Security: Code review skill gives false sense of security with rudimentary checks",
        "labels": ["security"],
        "body": """\
## Summary

The `CodeReviewSkill` in `src/aise/skills/developer/code_review.py` performs security scanning using
naive string matching that misses most vulnerability categories while producing false positives.

## Location

- `src/aise/skills/developer/code_review.py` — `_check_security()` method

## Details

The security checks consist only of:
1. Checking if `"eval("` or `"exec("` appears in the content string
2. Checking if `"password"` appears in the content

**Missed vulnerability categories:**
- SQL injection / NoSQL injection
- Path traversal
- Server-Side Request Forgery (SSRF)
- Command injection (subprocess, os.system, os.popen)
- Unsafe deserialization (pickle.loads, yaml.load without SafeLoader)
- Hardcoded secrets/API keys
- Cross-site scripting (XSS)
- Insecure cryptography
- Race conditions

**False positive issues:**
- All string matching is done without context — occurrences inside comments, docstrings,
  or string literals are flagged
- Legitimate password handling code (hashing, validation) is flagged

## Impact

Users may trust the code review output and believe their code has been security-audited.
A "0 security issues" result gives a false sense of security.

## Recommendation

1. Clearly document that these checks are heuristic and not a substitute for proper security review
2. Consider using AST-based analysis instead of string matching to avoid false positives
3. Expand the check list to cover at least OWASP Top 10 categories
""",
    },
    {
        "title": "Security: Hardcoded credentials in generated test fixtures",
        "labels": ["security"],
        "body": """\
## Summary

`src/aise/skills/qa/test_automation.py` generates test conftest files containing hardcoded credentials
and URLs.

## Location

- `src/aise/skills/qa/test_automation.py` — `_generate_conftest()` method (lines 108, 113)

## Details

The generated conftest contains:
```python
BASE_URL = "http://localhost:8000/api/v1"
headers = {"Authorization": "Bearer test-token"}
```

While these are placeholders intended for test environments, they present risks:
1. Developers may replace `test-token` with a real token and forget to externalize it
2. The hardcoded localhost URL will fail in CI/CD environments
3. The pattern teaches users to embed credentials in source code

## Recommendation

1. Use environment variables: `os.environ.get("TEST_BASE_URL", "http://localhost:8000/api/v1")`
2. Use environment variables for auth: `os.environ.get("TEST_AUTH_TOKEN", "")`
3. Add a comment in generated code warning against hardcoding real credentials
""",
    },
    {
        "title": "Bug: Task ID format mismatch causes dependency resolution failure",
        "labels": ["bug"],
        "body": """\
## Summary

`src/aise/skills/lead/task_decomposition.py` mixes zero-padded (`TASK-001`) and non-padded (`TASK-4`)
task IDs. Dependencies reference zero-padded IDs while tasks use non-padded IDs, so dependency
resolution will never match.

## Location

- `src/aise/skills/lead/task_decomposition.py` — task ID generation throughout `execute()` method

## Details

Phase 1 goal tasks use zero-padded IDs:
```python
"id": f"TASK-{task_id:03d}"  # produces "TASK-001"
```

But continuation tasks use non-padded IDs:
```python
"id": f"TASK-{task_id}"  # produces "TASK-4"
```

And dependencies reference zero-padded format:
```python
"dependencies": [f"TASK-{i:03d}" for i in ...]
```

This means `TASK-004` (dependency reference) will never match `TASK-4` (actual task ID), breaking
the dependency graph.

## Recommendation

Use consistent ID formatting throughout — either always zero-padded or always plain integers.
""",
    },
    {
        "title": "Bug: Dead code in test_case_design.py — computed value is discarded",
        "labels": ["bug"],
        "body": """\
## Summary

In `src/aise/skills/qa/test_case_design.py`, line 34 computes a value from an API endpoint path
that is never assigned to a variable or used.

## Location

- `src/aise/skills/qa/test_case_design.py` — line 34

## Details

The expression:
```python
path.split("/")[-1].rstrip("s").replace("{id}", "")
```

computes what appears to be a resource name derived from the endpoint path (e.g., `/api/v1/users`
→ `user`), but the result is discarded — it is not assigned to any variable.

This is likely intended to derive a resource name for use in test case generation but was accidentally
left as a bare expression.

## Impact

Test cases may be generated with less descriptive or generic names instead of resource-specific ones.

## Recommendation

Assign the computed value to a variable and use it in test case naming/descriptions.
""",
    },
    {
        "title": "Code smell: Test automation generates tests that always pass (assert True)",
        "labels": ["code-quality"],
        "body": """\
## Summary

The test automation skill generates automated test scripts where every test ends with `assert True`,
meaning all tests will pass regardless of actual system behavior.

## Location

- `src/aise/skills/qa/test_automation.py` — generated test method bodies (line 96)
- `src/aise/skills/developer/unit_test_writing.py` — generated tests only check return types

## Details

The generated test automation code produces methods like:
```python
def test_get_users_success(self, client):
    response = client.get("/api/v1/users")
    assert True  # placeholder
```

Similarly, the unit test writing skill generates tests that only verify return types:
```python
def test_list_returns_list(self):
    result = service.list()
    assert isinstance(result, list)
```

These tests provide no actual validation of business logic, edge cases, error conditions, or
boundary values.

## Impact

- Test automation produces tests that cannot catch regressions
- Unit tests give false confidence in code correctness
- The testing phase of the SDLC workflow becomes essentially a no-op

## Recommendation

Generate meaningful test assertions based on the API contract and expected behavior, or clearly
document that generated tests are scaffolding that must be completed by the developer.
""",
    },
    {
        "title": "Code smell: Bug fix skill marks bugs as 'fixed' without producing code changes",
        "labels": ["code-quality"],
        "body": """\
## Summary

The `BugFixSkill` in `src/aise/skills/developer/bug_fix.py` claims to diagnose and fix bugs but
only generates metadata describing the bugs. No actual code modifications are produced, yet bugs
are marked with `"status": "fixed"`.

## Location

- `src/aise/skills/developer/bug_fix.py` — `execute()` method (lines 43, 67)

## Details

The skill iterates over bug reports and for each one:
1. Generates a `fix_description` string
2. Assigns a `related_module` based on weak substring matching
3. Sets `"status": "fixed"`

But no actual code patch, diff, or modified source is produced. The artifact content contains only
metadata about the bugs, not fixes.

## Impact

- The session's `bug` command tells users "Fixed: N" which is misleading
- The workflow pipeline believes bugs have been addressed when they haven't
- Users relying on the tool for bug fixing get no actionable output

## Recommendation

Either:
1. Rename to `BugTriageSkill` and set status to `"triaged"` instead of `"fixed"`
2. Or integrate with LLM to generate actual code patches as part of the artifact
""",
    },
    {
        "title": "Code smell: Multiple review skills directly mutate artifact status as side effect",
        "labels": ["code-quality"],
        "body": """\
## Summary

Several review skills directly mutate the `.status` field of artifacts retrieved from the
`ArtifactStore`, creating hidden side effects that bypass the store's management.

## Location

- `src/aise/skills/pm/product_review.py` — line 77: `prd.status = ArtifactStatus.APPROVED`
- `src/aise/skills/architect/architecture_review.py` — line 95 (similar pattern)
- `src/aise/skills/developer/code_review.py` — similar pattern
- `src/aise/skills/qa/test_review.py` — line 123 (similar pattern)

## Details

The pattern across all review skills is:
```python
artifact = context.artifact_store.get_latest(ArtifactType.SOME_TYPE)
# ... review logic ...
artifact.status = ArtifactStatus.APPROVED  # direct mutation!
```

This is problematic because:
1. The `ArtifactStore` has no awareness that the artifact's status changed
2. Any indexing, caching, or notification logic in the store would be bypassed
3. It creates an implicit contract between skills and the store that is easy to violate

## Recommendation

Add a `update_status(artifact_id, new_status)` method to `ArtifactStore` and use it instead of
direct mutation. This centralizes status transitions and allows for validation or event hooks.
""",
    },
    {
        "title": "Code smell: Tech stack selection always recommends Python testing tools for Go projects",
        "labels": ["code-quality"],
        "body": """\
## Summary

The `TechStackSelectionSkill` always recommends Python testing tools (`pytest`, `Playwright`) even
when Go is selected as the backend language.

## Location

- `src/aise/skills/architect/tech_stack_selection.py` — testing section (lines 89-94)

## Details

When Go is selected as the backend language based on NFR keywords, the testing recommendations
still include:
```python
"testing": {
    "unit": "pytest",
    "integration": "pytest + testcontainers",
    "e2e": "Playwright",
    "justification": "Comprehensive Python testing ecosystem",
}
```

The justification explicitly says "Python testing ecosystem" for a Go project.

## Recommendation

Select testing tools appropriate to the chosen backend language. For Go, recommend `testing` package,
`testify`, and Go-compatible E2E tools.
""",
    },
    {
        "title": "Code smell: API design skill produces non-standard OpenAPI output",
        "labels": ["code-quality"],
        "body": """\
## Summary

The `APIDesignSkill` in `src/aise/skills/architect/api_design.py` claims to produce OpenAPI 3.0
contracts but uses non-standard top-level keys (`endpoints`, `schemas`) instead of the standard
OpenAPI structure (`paths`, `components.schemas`).

## Location

- `src/aise/skills/architect/api_design.py` — `execute()` method

## Details

The generated contract uses:
```python
{
    "openapi_version": "3.0.0",
    "endpoints": [...],
    "schemas": [...]
}
```

Standard OpenAPI 3.0 uses:
```yaml
openapi: "3.0.0"
paths:
  /users:
    get: ...
components:
  schemas:
    User: ...
```

Additionally:
- Generated schemas have empty `properties` and `required` arrays, providing no validation guidance
- Naive pluralization (`resource + "s"`) fails for words like "status" → "statuss"

## Impact

- Generated API contracts cannot be consumed by OpenAPI tooling (Swagger UI, code generators, etc.)
- Empty schemas provide no validation guidance for downstream code generation

## Recommendation

Either produce valid OpenAPI 3.0 output or rename the format to avoid confusion with the standard.
""",
    },
]


def create_issues_gh():
    """Create issues using the gh CLI."""
    for issue in ISSUES:
        label_args = []
        for label in issue.get("labels", []):
            label_args.extend(["--label", label])

        cmd = [
            "gh", "issue", "create",
            "--repo", REPO,
            "--title", issue["title"],
            "--body", issue["body"],
            *label_args,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Created: {issue['title']}")
            print(f"  URL: {result.stdout.strip()}")
        else:
            print(f"FAILED: {issue['title']}")
            print(f"  Error: {result.stderr.strip()}")


def create_issues_api(token: str):
    """Create issues using the GitHub REST API."""
    import urllib.request

    for issue in ISSUES:
        payload = {
            "title": issue["title"],
            "body": issue["body"],
            "labels": issue.get("labels", []),
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/issues",
            data=data,
            headers={
                "Authorization": f"token {token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github.v3+json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                print(f"Created: {issue['title']}")
                print(f"  URL: {result['html_url']}")
        except Exception as e:
            print(f"FAILED: {issue['title']}")
            print(f"  Error: {e}")


def main():
    import os

    if "--use-gh" in sys.argv:
        create_issues_gh()
    else:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            print("Set GITHUB_TOKEN env var or use --use-gh flag")
            print(f"\nTotal issues to create: {len(ISSUES)}")
            for i, issue in enumerate(ISSUES, 1):
                labels = ", ".join(issue.get("labels", []))
                print(f"  {i}. [{labels}] {issue['title']}")
            sys.exit(1)
        create_issues_api(token)


if __name__ == "__main__":
    main()
