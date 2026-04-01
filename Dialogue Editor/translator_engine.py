import re

# Punctuation after which a manual line break is considered intentional and preserved.
_BREAK_PUNCT = r'[.!?;:,\—\…\"\'」』\)\]]'

class TranslationEngine:
    def __init__(self, tag_map=None):
        self.tag_map = tag_map or {}

    def get_simulated_len(self, text):
        working_text = text
        found_tags = re.findall(r'<([^>]+)>', working_text)
        for tag_content in found_tags:
            sim_len = self.tag_map.get(tag_content, 0)
            working_text = working_text.replace(f"<{tag_content}>", "X" * sim_len)
        clean_text = re.sub(r'<[^>]*>', '', working_text)
        return len(clean_text)

    def strip_erroneous_breaks(self, text):
        """Remove line breaks NOT directly preceded by punctuation.
        Trailing spaces before the break are consumed. Intentional breaks
        (after . ! ? ; : , — … quotes/brackets) are preserved."""
        lines = text.split('\n')
        if len(lines) <= 1:
            return text
        i = 0
        while i < len(lines) - 1:
            stripped = lines[i].rstrip()
            bare = re.sub(r'<[^>]*>', '', stripped).rstrip()
            if bare and re.search(_BREAK_PUNCT + r'$', bare):
                lines[i] = stripped          # intentional — keep break, just trim trailing space
                i += 1
            else:
                # Erroneous — merge into next line
                next_line = lines[i + 1].lstrip()
                lines[i + 1] = stripped + (' ' if stripped and next_line else '') + next_line
                lines.pop(i)                 # remove current line (don't advance i)
        return '\n'.join(lines)

    def master_tag_wrap(self, text, limit):
        if not text:
            return ""

        # Step 1: strip erroneous manual line breaks, preserving intentional ones
        cleaned = self.strip_erroneous_breaks(text)

        # Step 2: wrap each intentional segment independently
        segments = cleaned.split('\n')
        result_lines = []
        for seg in segments:
            result_lines.extend(self._wrap_segment(seg.strip(), limit))

        # Step 3: stub balancing
        result_lines = self._balance_stubs(result_lines, limit)

        return "\n".join(result_lines)

    def _tokenise(self, text):
        """Split text into word-level tokens where complete <tags> are always atomic.
        Spaces inside angle brackets are never treated as split points."""
        parts = re.split(r'(<[^>]+>)', text)   # alternates: text, tag, text, tag, ...
        tokens = []
        for part in parts:
            if part.startswith('<') and part.endswith('>'):
                tokens.append(part)             # whole tag — never split
            elif part:
                tokens.extend(re.split(r'(\s+)', part))   # normal text — split on whitespace
        return tokens

    def _wrap_segment(self, text, limit):
        """Wrap a single flat string into lines within limit."""
        if not text:
            return []
        lines = []
        current_line = ""
        for word in self._tokenise(text):
            test_line = current_line + word
            if self.get_simulated_len(test_line) <= limit:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line.rstrip())
                    current_line = word.lstrip()
                else:
                    current_line = word   # word alone exceeds limit — accept it
        if current_line:
            lines.append(current_line.rstrip())
        return lines

    def _balance_stubs(self, lines, limit, stub_ratio=0.40):
        """If the last line is a stub (< stub_ratio * limit), try pulling the
        last word from the previous line onto it."""
        if len(lines) < 2:
            return lines
        lines = list(lines)
        last_len = self.get_simulated_len(lines[-1])
        if last_len >= limit * stub_ratio:
            return lines
        tokens = self._tokenise(lines[-2])
        word_tokens = [(idx, t) for idx, t in enumerate(tokens) if t.strip()]
        if not word_tokens:
            return lines
        last_word_idx, last_word = word_tokens[-1]
        candidate_prev = ''.join(tokens[:last_word_idx]).rstrip()
        candidate_last = last_word.lstrip() + (' ' if lines[-1].strip() else '') + lines[-1]
        if (candidate_prev and
                self.get_simulated_len(candidate_prev) >= 1 and
                self.get_simulated_len(candidate_last) <= limit):
            lines[-2] = candidate_prev
            lines[-1] = candidate_last.lstrip()
        return lines

    def apply_in_universe(self, text, replacements):
        """Apply modern->archaic replacements (whole-word, case-insensitive)."""
        for modern, archaic in replacements.items():
            text = re.sub(r'\b' + re.escape(modern) + r'\b', archaic, text)
        return text

    def has_complex_tags(self, text):
        return any(not t.upper().startswith('COL') for t in re.findall(r'<([^>]+)>', text))

    def has_non_col_tags(self, text):
        return self.has_complex_tags(text)

    def clean_and_wrap(self, text, limit):
        return self.master_tag_wrap(text, limit)
