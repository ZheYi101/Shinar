"""Incremental sentence boundaries and a conservative spoken-text projection."""

import re


class SpeechTextBuffer:
    def __init__(self, limit: int = 4096) -> None:
        self.limit = limit
        self.text = ""
        self.done = False

    def append(self, delta: str) -> None:
        if len(self.text) + len(delta) > self.limit:
            raise ValueError("speech_text_buffer_full")
        self.text += delta

    def pop_sentence(self) -> str | None:
        parentheses, brackets, inline_code = 0, 0, False
        for index, char in enumerate(self.text):
            if char == "`":
                inline_code = not inline_code
            elif not inline_code:
                parentheses += (char == "(") - (char == ")" and parentheses > 0)
                brackets += (char == "[") - (char == "]" and brackets > 0)
            if char not in ".!?。！？\n":
                continue
            if char != "\n" and (parentheses or brackets or inline_code):
                continue
            if char == ".":
                # Wait for lookahead: '3.' may become '3.14' in the next delta.
                if index + 1 == len(self.text) and not self.done:
                    continue
                if (
                    index
                    and index + 1 < len(self.text)
                    and self.text[index - 1].isdigit()
                    and self.text[index + 1].isdigit()
                ):
                    continue
                prefix = self.text[: index + 1]
                if re.search(
                    r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|vs|etc|e\.g|i\.e)\.$|\b(?:[A-Za-z]\.)+$",
                    prefix,
                    re.I,
                ):
                    continue
            end = index + 1
            while end < len(self.text) and self.text[end] in "\"'”’」』)]":
                end += 1
            value, self.text = self.text[:end], self.text[end:]
            return value
        if self.done and self.text:
            value, self.text = self.text, ""
            return value
        return None


class SpokenTextProjection:
    """Exclude fenced code, metadata and Markdown syntax without rewriting facts."""

    def __init__(self) -> None:
        self.in_code = False

    def project(self, text: str, *, final: bool = False) -> str:
        lines = text.splitlines(keepends=True)
        result = []
        for line in lines:
            if line.lstrip().startswith(("```", "~~~")):
                self.in_code = not self.in_code
            elif not self.in_code:
                line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
                line = re.sub(r"^\s*(?:#{1,6}\s+|>\s*)", "", line)
                result.append(line.replace("**", "").replace("__", "").replace("`", ""))
        spoken = "".join(result).strip()
        return spoken if re.search(r"\w", spoken) else ""
