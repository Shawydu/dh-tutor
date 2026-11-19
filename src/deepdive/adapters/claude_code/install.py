"""Generate the Claude Code runtime workspace (.mcp.json, settings, agents, skills, CLAUDE.md).

Formats checked against the Claude Code docs and the installed CLI (2.1.311), November 2026:
  https://code.claude.com/docs/en/settings.md   permissions and hooks in .claude/settings.json
  https://code.claude.com/docs/en/sub-agents.md agent frontmatter: name, description, tools,
                                                disallowedTools
  https://code.claude.com/docs/en/skills.md     skill frontmatter: description, argument-hint,
                                                $ARGUMENTS
  https://code.claude.com/docs/en/mcp.md        .mcp.json stdio entry
"""

import json
from importlib import resources
from pathlib import Path

MARKER = ".deepdive-generated"
REPO = Path(__file__).resolve().parents[4]  # shortcut: assumes a checkout, not a wheel install
LOCKED = ["WebSearch", "WebFetch", "Bash", "Edit", "Write", "Read", "Glob", "Grep", "NotebookEdit"]

SKILLS = {
    "dive": (
        "Start a deep dive on a topic",
        "<topic>",
        "Start a new deep dive. The topic is: $ARGUMENTS\n\n"
        "Follow the guide's intake: call `topic_create`, then `session_start`, then begin scoping.",
    ),
    "topics": (
        "List your topics",
        "",
        "Call `topic_overview` and show each topic on one line: status, charter version, agenda "
        "done/total, open and parked question counts, last session date and a pin marker. Indent "
        "child topics under their parent. Do not start teaching.",
    ),
    "resume": (
        "Resume a topic where you left off",
        "[topic]",
        "Resume the topic named: $ARGUMENTS\n\nCall `topic_overview` and pick the topic whose "
        "title best matches (ask which if none is named or several match). Call `resume_brief` "
        "with its id, then `session_start`, then present the brief as the guide's 'Resuming' "
        "section says.",
    ),
    "sumup": (
        "Sum up a topic as a retrospective",
        "[topic]",
        "Sum up the topic named: $ARGUMENTS\n\nCall `topic_overview` and pick the topic whose "
        "title best matches (ask which if none is named or several match). Call `topic_recap` "
        "with its id and write the retrospective as the guide's 'Summing up' section says.",
    ),
    "charter": (
        "Show a topic's charter and its versions",
        "[topic]",
        "Show the charter of the topic named: $ARGUMENTS\n\nCall `topic_overview` and pick the "
        "best title match (ask which if none is named or several match). Call `charter_get` for "
        "the latest charter and show it with its version number. The version number is also the "
        "count of versions: call `charter_get` with an earlier `version` only if asked.",
    ),
    "parked": (
        "Show parked questions for a topic",
        "[topic]",
        "Call `parked_list` for the topic named: $ARGUMENTS (ask which if none is named) "
        "and list the parked questions. If $ARGUMENTS is a phrase rather than a topic, use "
        "`parked_search` with it instead.",
    ),
}


class InstallError(Exception):
    pass


def _split(text: str) -> tuple[dict[str, str], str]:
    """Split a persona file into its flat front matter and body."""
    _, head, body = text.split("---\n", 2)
    meta = dict(line.split(": ", 1) for line in head.splitlines())
    return meta, body.strip()


def _persona(name: str) -> tuple[dict[str, str], str]:
    return _split(resources.files("deepdive.personas").joinpath(f"{name}.md").read_text("utf-8"))


def render(repo: Path = REPO) -> dict[str, str]:
    """Every generated file, keyed by its path relative to the workspace."""
    files: dict[str, str] = {}
    server = {"command": "uv", "args": ["run", "--project", str(repo), "deepdive", "mcp", "serve"]}
    files[".mcp.json"] = _json({"mcpServers": {"deepdive": server}})
    # Hook entries arrive with the hook commands (V0-10, v1).
    files[".claude/settings.json"] = _json(
        {"permissions": {"allow": ["mcp__deepdive__*"], "deny": LOCKED}}
    )
    files["CLAUDE.md"] = f"{_persona('_shared')[1]}\n\n{_persona('guide')[1]}\n"
    for pid in ("curious", "skeptic", "poc_builder"):
        meta, body = _persona(pid)
        name = pid.replace("_", "-") + ("-student" if meta["role"] == "student" else "")
        tools = ", ".join(f"mcp__deepdive__{t}" for t in meta["tools"].strip("[]").split(", "))
        files[f".claude/agents/{name}.md"] = (
            f"---\nname: {name}\ndescription: {meta['description']}\ntools: {tools}\n"
            f"disallowedTools: WebSearch, WebFetch\n---\n{body}\n"
        )
    for name, (desc, hint, body) in SKILLS.items():
        hint_line = f"argument-hint: {hint}\n" if hint else ""
        files[f".claude/skills/{name}/SKILL.md"] = (
            f"---\ndescription: {desc}\n{hint_line}disable-model-invocation: true\n---\n{body}\n"
        )
    return files


def _json(data: object) -> str:
    return json.dumps(data, indent=2) + "\n"


def install(workspace: Path) -> list[str]:
    """Write the workspace; returns the files whose content changed. Refuses foreign files."""
    files = render()
    if not (workspace / MARKER).exists():
        clash = [rel for rel in files if (workspace / rel).exists()]
        if clash:
            raise InstallError(f"{workspace} has no {MARKER}; refusing to overwrite: {clash}")
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / MARKER).write_text(
        "Generated by `deepdive init`; edits are overwritten.\n", "utf-8"
    )
    changed = drift(workspace)
    for rel in changed:
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(files[rel], "utf-8")
    return changed


def drift(workspace: Path) -> list[str]:
    """Generated files that are missing or differ from what init would write."""
    return [
        rel
        for rel, text in render().items()
        if not (workspace / rel).is_file() or (workspace / rel).read_text("utf-8") != text
    ]
