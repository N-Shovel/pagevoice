"""Chapter tidy-up shared by the readers."""

from pagevoice.document import Chapter, Paragraph, Reason


def finish_chapters(
    chapters: list[Chapter], front: list[Paragraph], title: str, rules
) -> list[Chapter]:
    """Tidy heading-only chapters and put text before the first heading in front matter.

    A run of three or more heading-only chapters is a table of contents: it joins the
    front matter. A lone heading-only chapter ("BOOK II" before "CHAPTER I") is folded
    into the chapter after it.
    """
    out: list[Chapter] = []
    run: list[Chapter] = []

    def flush_run(next_chapter: Chapter | None) -> None:
        if len(run) >= 3 or next_chapter is None:
            target = out[-1].paragraphs if out else front
            for empty in run:
                if len(run) >= 3:  # a list of chapter names: kept, not read
                    for paragraph in empty.paragraphs:
                        for span in paragraph.spans:
                            span.reason = span.reason or Reason.CONTENTS
                target.extend(empty.paragraphs)
        elif next_chapter is not None:
            heads = [p for empty in run for p in empty.paragraphs]
            next_chapter.paragraphs[:0] = heads
            next_chapter.title = " ".join([*(e.title for e in run), next_chapter.title])
        run.clear()

    for chapter in chapters:
        # Only headings, plus perhaps removals (a picture marker): nothing to read yet.
        if all(p.kind == "heading" or not p.text for p in chapter.paragraphs):
            run.append(chapter)
            continue
        flush_run(chapter)
        out.append(chapter)
    flush_run(None)

    if not out:
        return [Chapter(title=title, paragraphs=front)]
    if any(p.text for p in front):
        out.insert(0, Chapter(title=rules.FRONT_MATTER_TITLE, paragraphs=front))
    elif front:
        out[0].paragraphs[:0] = front  # only removals (e.g. boilerplate): keep them
    return out
