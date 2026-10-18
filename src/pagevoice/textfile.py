"""Reading text files people make with ordinary tools (Notepad, Excel, editors)."""


def decode(data: bytes) -> str:
    """UTF-8 (with or without BOM), UTF-16 with BOM, else Windows-1252.

    Excel saves "Text (Tab delimited)" as Windows-1252 and "Unicode Text" as UTF-16, so
    all three turn up in practice."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")
