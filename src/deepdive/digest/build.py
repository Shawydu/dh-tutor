"""The morning digest: unread discoveries by topic and new cross-topic connections, as markdown."""

from datetime import UTC, date, datetime
from itertools import groupby
from pathlib import Path
from urllib.parse import urlparse

from deepdive.store.repos import Store

NOTHING_NEW = "Nothing new since the last digest."


def _one_line(text: str) -> str:
    return " ".join(text.split())


class DigestBuilder:
    def __init__(self, store: Store, folder: Path) -> None:
        self.store = store
        self.folder = folder

    def path(self, day: date) -> Path:
        return self.folder / f"{day.isoformat()}.md"

    def read(self, day: date) -> str | None:
        file = self.path(day)
        return file.read_text("utf-8") if file.exists() else None

    def write(self, day: date) -> Path:
        file = self.path(day)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(self.build(day), "utf-8")
        return file

    def _since(self, day: date) -> datetime | None:
        """Cutoff for "new": midnight UTC of the latest earlier digest's day, else None (all)."""
        days = []
        for f in self.folder.glob("*.md"):
            try:
                earlier = date.fromisoformat(f.stem)
            except ValueError:
                continue  # not a digest file
            if earlier < day:
                days.append(earlier)
        # shortcut: items made on that day after its digest was built repeat once; store a built-at
        return datetime.combine(max(days), datetime.min.time(), UTC) if days else None

    def build(self, day: date) -> str:
        since = self._since(day)
        titles = {t.id: t.title for n in self.store.topics.list_all() for t in (n, *n.children)}
        findings = sorted(
            (
                self.store.discoveries.finding(d)
                for d in self.store.discoveries.list_unread(since=since)
            ),
            key=lambda f: (titles[f.topic_id], str(f.topic_id), -f.relevance, str(f.id)),
        )
        lines = [f"# Digest — {day.isoformat()}", ""]
        for topic_id, group in groupby(findings, key=lambda f: f.topic_id):
            lines += [f"## {titles[topic_id]}", ""]
            for f in group:
                host = urlparse(f.source_url).hostname or f.source_url
                url = f.source_url.replace(" ", "%20").replace(")", "%29")  # keeps the link whole
                lines += [
                    f"- **{f.effect.value}** {f.target_type.value}: {_one_line(f.summary)}",
                    f'  Why it matters: "{_one_line(f.target_text)}". Source: [{host}]({url}).',
                    f"  Resume: `/resume {titles[topic_id]} --item {f.id}`",
                ]
            lines.append("")
        pairs = []
        for e in self.store.edges.list_cross_topic(since):
            a, b = self.store.questions.require(e.from_id), self.store.questions.require(e.to_id)
            pairs.append(
                f'- {titles[a.topic_id]}: "{_one_line(a.clean_text)}" ↔ {titles[b.topic_id]}:'
                f' "{_one_line(b.clean_text)}" ({e.relation.value})'
            )
        if pairs:
            lines += ["## Connections across topics", "", *sorted(pairs), ""]
        if not findings and not pairs:
            lines += [NOTHING_NEW, ""]
        # Recaps due: omitted until v2 adds recap scheduling
        return "\n".join(lines)
