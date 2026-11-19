"""Input limits for every ledger tool, in one place. Over-limit input is refused, never cut."""

from typing import Annotated
from uuid import UUID

from pydantic import Field

TITLE_MAX = 200  # topic titles, agenda facets, core questions and other one-line items
TEXT_MAX = 1000  # claim text, charter done_when
SUMMARY_MAX = 2000  # session summaries, answer summaries, evidence excerpt summaries
NOTE_MAX = 500  # bookmark notes
URL_MAX = 2048
DOI_MAX = 256
MARKDOWN_MAX = 50000  # a saved recap
KIND_MAX = 64
LIST_MAX = 50  # items in a list argument: facets, charter lists, source ids
TIER_MAX = 9  # tiers are 1 (most trusted) and up; the domain pack uses 1 to 3
PAGE_SIZE = 10  # top-level topics per /topics page

Limit = Annotated[int, Field(ge=1, le=25)]  # results per search
Id = UUID  # JSON schema format uuid; anything else is refused before the tool runs
Version = Annotated[int, Field(ge=1)]
Page = Annotated[int, Field(ge=1)]
Title = Annotated[str, Field(min_length=1, max_length=TITLE_MAX)]
Text = Annotated[str, Field(min_length=1, max_length=TEXT_MAX)]
Summary = Annotated[str, Field(min_length=1, max_length=SUMMARY_MAX)]
Markdown = Annotated[str, Field(min_length=1, max_length=MARKDOWN_MAX)]
Note = Annotated[str, Field(max_length=NOTE_MAX)]
Items = Annotated[list[Title], Field(max_length=LIST_MAX)]
Facets = Annotated[list[Title], Field(min_length=1, max_length=LIST_MAX)]
SourceIds = Annotated[list[Id], Field(min_length=1, max_length=LIST_MAX)]
Tier = Annotated[int, Field(ge=1, le=TIER_MAX)]
Kind = Annotated[str, Field(min_length=1, max_length=KIND_MAX)]
Url = Annotated[str, Field(min_length=1, max_length=URL_MAX)]
Doi = Annotated[str, Field(min_length=1, max_length=DOI_MAX)]
