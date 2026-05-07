"""Integration probe — runtime-side companion to the static main_entry
predicates.

Responsibility: take a project root, look up the stack profile, and
return an ``integration_report.json``-shaped dict with the runtime
``boot_check`` plus best-effort ``data_wiring_check`` /
``action_wiring_check`` annotations. The probe is a *helper* — neither
PhaseExecutor nor any predicate runs it automatically. The developer
agent or qa_engineer agent invokes it via the ``aise integration_probe``
CLI hook (``python -m aise.runtime.integration_probe <project_root>``)
inside the main_entry phase, and writes the result into
``docs/integration_report.json``.

By design:
* Static gates enforce correctness (and never spawn subprocesses).
* The runtime probe is best-effort: it writes ``verdict=skipped`` with
  a precise ``reason`` whenever the stack profile is ``web`` or
  ``unknown`` (no headless browser shipped with the AISE sandbox), or
  whenever a dependency (``run_command``, port, http library) is
  unavailable.

This module is intentionally pure-stdlib — no requests, no playwright,
no docker. Subprocess + urllib + socket only.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import URLError

from .stack_profiles import select_profile

# -- Result types --------------------------------------------------------


@dataclass
class BootCheck:
    ran: bool = False
    verdict: str = "skipped"  # pass | fail | skipped
    exit_code: int | None = None
    duration_s: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # exit_code may be None — drop it from the dict in that case so
        # the schema's `integer` type doesn't trip on null.
        if d.get("exit_code") is None:
            d.pop("exit_code")
        return d


@dataclass
class DataWiring:
    name: str
    static_refs: int
    consumer_module_resolved: str = ""
    runtime_invariant_ok: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d.get("runtime_invariant_ok") is None:
            d.pop("runtime_invariant_ok")
        return d


@dataclass
class ActionWiring:
    name: str
    handler_calls_found: int
    handler_calls_missing: list[str] = field(default_factory=list)
    state_changed: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d.get("state_changed") is None:
            d.pop("state_changed")
        return d


@dataclass
class ProbeResult:
    profile: str
    runtime_kind: str
    verdict: str  # pass | fail | skipped
    boot: BootCheck
    data_wiring: list[DataWiring]
    action_wiring: list[ActionWiring]
    violations: list[str]

    def to_integration_report(self) -> dict[str, Any]:
        """Materialize the integration_report.json shape consumed by
        the schema validator + AUTO_GATE."""
        from datetime import datetime, timezone

        return {
            "phase": "main_entry",
            "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            "verdict": self.verdict,
            "lifecycle_init_check": {"expected": 0, "reached": 0},
            "data_wiring_check": [d.to_dict() for d in self.data_wiring],
            "action_wiring_check": [a.to_dict() for a in self.action_wiring],
            "boot_check": self.boot.to_dict(),
            "violations": list(self.violations),
            "_profile": self.profile,
            "_runtime_kind": self.runtime_kind,
        }


# -- Static-side helpers (mirror predicates.py logic for the report) -----


def _glob_substring_keys(glob: str) -> list[str]:
    cut = glob
    for ch in ("*", "?", "[", "{"):
        idx = cut.find(ch)
        if idx >= 0:
            cut = cut[:idx]
    cut = cut.rstrip("/")
    out: list[str] = []
    if cut:
        out.append(cut)
    if glob and glob not in out:
        out.append(glob)
    return out or [glob]


def _expand(project_root: Path, glob: str) -> list[Path]:
    return sorted(project_root.glob(glob.lstrip("/")))


def _count_data_refs(project_root: Path, dep: dict[str, Any]) -> tuple[int, str]:
    consumer_glob = dep.get("consumer_module") or ""
    files_glob = dep.get("files_glob") or ""
    if not consumer_glob or not files_glob:
        return 0, ""
    consumers = _expand(project_root, consumer_glob)
    if not consumers:
        return 0, consumer_glob
    keys = list(_glob_substring_keys(files_glob))
    for f in _expand(project_root, files_glob):
        try:
            keys.append(str(f.relative_to(project_root)))
        except ValueError:
            keys.append(str(f))
        keys.append(f.name)
    keys = list(dict.fromkeys(keys))
    refs = 0
    matched_consumer = ""
    for c in consumers:
        try:
            body = c.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for k in keys:
            if k and k in body:
                refs += body.count(k)
                if not matched_consumer:
                    try:
                        matched_consumer = str(c.relative_to(project_root))
                    except ValueError:
                        matched_consumer = str(c)
    return refs, matched_consumer


def _count_handler_calls(
    project_root: Path,
    action: dict[str, Any],
    default_handler: str,
) -> tuple[int, list[str]]:
    must_call = action.get("handler_must_call") or []
    if not must_call:
        return 0, []
    handler_rel = action.get("handler_module") or default_handler
    if not handler_rel:
        return 0, list(must_call)
    handler_path = project_root / handler_rel.lstrip("/")
    if not handler_path.is_file():
        return 0, list(must_call)
    try:
        body = handler_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, list(must_call)
    found = 0
    missing: list[str] = []
    for sym in must_call:
        if not isinstance(sym, str) or not sym:
            continue
        tail = sym.rsplit(".", 1)[-1]
        pattern = rf"\b{re.escape(tail)}\s*\("
        if re.search(pattern, body):
            found += 1
        else:
            missing.append(sym)
    return found, missing


# -- Runtime boot helpers ------------------------------------------------


def _alloc_port() -> int:
    """Ask the OS for a free TCP port. Race-prone (someone else could
    grab it before the spawned process binds) but the probe's boot
    window is short enough that this is acceptable for a best-effort."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _format_cmd(
    template: tuple[str, ...],
    *,
    entry_point: str,
    run_command: str,
    port: int,
) -> list[str]:
    """Substitute template placeholders. Missing placeholder raises
    KeyError so we surface a precise error in the report."""
    out: list[str] = []
    for tok in template:
        formatted = tok.format(entry_point=entry_point, run_command=run_command, port=port)
        out.append(formatted)
    return out


def _run_cli_probe(
    cmd: list[str],
    cwd: Path,
    timeout_s: int,
) -> BootCheck:
    """Spawn the cli binary, wait for exit, capture stdio. Verdict is
    pass when exit_code is 0 and stdout is non-empty (something happened);
    fail otherwise."""
    started = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 — cmd is from architect's stack_contract
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return BootCheck(
            ran=True,
            verdict="fail",
            exit_code=None,
            duration_s=time.monotonic() - started,
            reason=f"cli probe timed out after {timeout_s}s",
        )
    except OSError as exc:
        return BootCheck(
            ran=False,
            verdict="skipped",
            duration_s=time.monotonic() - started,
            reason=f"spawn failed: {type(exc).__name__}: {exc}",
        )
    duration = time.monotonic() - started
    if proc.returncode != 0:
        return BootCheck(
            ran=True,
            verdict="fail",
            exit_code=proc.returncode,
            duration_s=duration,
            reason=f"non-zero exit; stderr head: {(proc.stderr or '')[:200]!r}",
        )
    stdout_head = (proc.stdout or "").strip()
    if not stdout_head:
        return BootCheck(
            ran=True,
            verdict="fail",
            exit_code=0,
            duration_s=duration,
            reason="exit 0 but empty stdout — no observable behaviour",
        )
    return BootCheck(
        ran=True,
        verdict="pass",
        exit_code=0,
        duration_s=duration,
        reason=f"stdout head: {stdout_head[:120]!r}",
    )


def _run_server_probe(
    cmd: list[str],
    cwd: Path,
    url: str,
    timeout_s: int,
) -> BootCheck:
    """Spawn server, poll URL until 2xx (or timeout), then terminate."""
    started = time.monotonic()
    try:
        proc = subprocess.Popen(  # noqa: S603 — cmd is from architect's stack_contract
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        return BootCheck(
            ran=False,
            verdict="skipped",
            duration_s=time.monotonic() - started,
            reason=f"spawn failed: {type(exc).__name__}: {exc}",
        )
    deadline = started + timeout_s
    last_err = ""
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                # Server exited before responding — collect output.
                tail = (proc.stderr.read() if proc.stderr else "") or ""
                return BootCheck(
                    ran=True,
                    verdict="fail",
                    exit_code=proc.returncode,
                    duration_s=time.monotonic() - started,
                    reason=f"server exited early: stderr head: {tail[:200]!r}",
                )
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 — local probe
                    status = resp.status if hasattr(resp, "status") else resp.getcode()
                    if 200 <= status < 400:
                        return BootCheck(
                            ran=True,
                            verdict="pass",
                            exit_code=None,
                            duration_s=time.monotonic() - started,
                            reason=f"http {status} from {url}",
                        )
                    last_err = f"http {status}"
            except (URLError, OSError, ConnectionError) as exc:
                last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(0.25)
        return BootCheck(
            ran=True,
            verdict="fail",
            exit_code=None,
            duration_s=time.monotonic() - started,
            reason=f"server did not respond at {url} within {timeout_s}s; last err: {last_err}",
        )
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass


def _run_web_probe(reason_extra: str = "") -> BootCheck:
    """Web probe is intentionally a stub. A real implementation would
    require puppeteer/playwright, which we don't ship with the AISE
    sandbox. The static gates (data_dependency_wiring_static and
    action_contract_wiring_static) cover the assembly correctness; the
    runtime probe in this profile contributes only an audit-log
    attestation that we *tried*."""
    base = "web runtime probe requires headless browser; not available in sandbox"
    if reason_extra:
        base = f"{base}; {reason_extra}"
    return BootCheck(ran=False, verdict="skipped", reason=base)


# -- Top-level entry point ------------------------------------------------


def run_probe(
    project_root: Path,
    *,
    stack_contract: dict[str, Any] | None = None,
    data_dependency_contract: dict[str, Any] | None = None,
    action_contract: dict[str, Any] | None = None,
    enable_boot: bool = True,
) -> ProbeResult:
    """End-to-end probe: pick profile, run static + (optional) runtime
    checks, return ProbeResult.

    The static checks always run (they have no external dependencies);
    the runtime boot probe runs only when ``enable_boot=True`` AND the
    profile supports it. ``enable_boot=False`` is the safe default for
    sandboxes / CI environments that don't want subprocess spawn.
    """
    profile = select_profile(project_root, stack_contract)

    # Static checks first — these are always run, regardless of profile.
    deps = (data_dependency_contract or {}).get("data_dependencies") or []
    actions = (action_contract or {}).get("actions") or []
    default_handler = (stack_contract or {}).get("entry_point") or ""

    data_wiring: list[DataWiring] = []
    violations: list[str] = []
    for dep in deps:
        if not isinstance(dep, dict):
            continue
        name = dep.get("name") or "?"
        refs, consumer_resolved = _count_data_refs(project_root, dep)
        if refs == 0:
            violations.append(f"data_wiring.{name}: 0 source references to {dep.get('files_glob')!r}")
        data_wiring.append(DataWiring(name=name, static_refs=refs, consumer_module_resolved=consumer_resolved))

    action_wiring: list[ActionWiring] = []
    for act in actions:
        if not isinstance(act, dict):
            continue
        name = act.get("name") or "?"
        found, missing = _count_handler_calls(project_root, act, default_handler)
        if missing:
            violations.append(f"action_wiring.{name}: handler missing call sites for {missing}")
        action_wiring.append(ActionWiring(name=name, handler_calls_found=found, handler_calls_missing=missing))

    # Runtime boot. Skipped when disabled or when profile doesn't support it.
    if not enable_boot:
        boot = BootCheck(ran=False, verdict="skipped", reason="boot probe disabled by caller")
    elif profile.runtime_kind == "web":
        boot = _run_web_probe()
    elif profile.runtime_kind == "unknown":
        boot = BootCheck(ran=False, verdict="skipped", reason="no_matching_profile")
    elif not profile.boot_cmd:
        boot = BootCheck(ran=False, verdict="skipped", reason="profile has no boot_cmd template")
    else:
        try:
            port = _alloc_port() if "{port}" in " ".join(profile.boot_cmd) else 0
            cmd = _format_cmd(
                profile.boot_cmd,
                entry_point=(stack_contract or {}).get("entry_point") or "",
                run_command=(stack_contract or {}).get("run_command") or "",
                port=port,
            )
        except KeyError as exc:
            boot = BootCheck(ran=False, verdict="skipped", reason=f"unresolved placeholder: {exc}")
        else:
            if profile.runtime_kind == "cli":
                boot = _run_cli_probe(cmd, project_root, profile.boot_timeout_s)
            elif profile.runtime_kind == "server":
                url = profile.observe_arg.format(port=port) if profile.observe_arg else f"http://127.0.0.1:{port}/"
                boot = _run_server_probe(cmd, project_root, url, profile.boot_timeout_s)
            else:
                boot = BootCheck(ran=False, verdict="skipped", reason=f"unknown runtime_kind={profile.runtime_kind}")

    # Verdict: if any static violation exists OR the boot probe reported
    # fail, the overall verdict is fail. Skipped probes don't count
    # against the verdict (we don't want a missing tool to block a
    # static-clean assembly).
    if violations or boot.verdict == "fail":
        verdict = "fail"
    elif data_wiring or action_wiring or boot.verdict == "pass":
        verdict = "pass"
    else:
        # Nothing to check (no contracts, no boot) → skipped, not pass.
        verdict = "skipped"

    return ProbeResult(
        profile=profile.name,
        runtime_kind=profile.runtime_kind,
        verdict=verdict,
        boot=boot,
        data_wiring=data_wiring,
        action_wiring=action_wiring,
        violations=violations,
    )


# -- CLI hook: python -m aise.runtime.integration_probe <project_root> ----


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main(argv: list[str] | None = None) -> int:
    """CLI wrapper. Reads the project's docs/*.json contracts, runs the
    probe, writes ``docs/integration_report.json``, and prints the
    JSON shape on stdout. Exit 0 on verdict in {pass, skipped}; exit 1
    on verdict=fail.
    """
    args = list(argv if argv is not None else sys.argv[1:])
    enable_boot = True
    if "--no-boot" in args:
        enable_boot = False
        args.remove("--no-boot")
    if not args:
        print("usage: integration_probe <project_root> [--no-boot]", file=sys.stderr)
        return 2
    project_root = Path(args[0]).resolve()
    if not project_root.is_dir():
        print(f"not a directory: {project_root}", file=sys.stderr)
        return 2

    sc = _load_optional_json(project_root / "docs" / "stack_contract.json")
    dd = _load_optional_json(project_root / "docs" / "data_dependency_contract.json")
    ac = _load_optional_json(project_root / "docs" / "action_contract.json")

    result = run_probe(
        project_root,
        stack_contract=sc,
        data_dependency_contract=dd,
        action_contract=ac,
        enable_boot=enable_boot,
    )
    report = result.to_integration_report()
    out = project_root / "docs" / "integration_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if result.verdict in ("pass", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
