import re

# Punctuation after which a manual line break is considered intentional and preserved.
# Also includes > so lines ending with a tag are never merged forward.
_BREAK_PUNCT = r'[.!?;:,\—\"\'」』\)\]>]'

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
        """Remove line breaks NOT directly preceded by punctuation or a closing tag,
        and not directly followed by an opening tag.
        Intentional breaks are preserved; erroneous ones are merged."""
        lines = text.split('\n')
        if len(lines) <= 1:
            return text
        i = 0
        while i < len(lines) - 1:
            stripped = lines[i].rstrip()
            # Preserve if this line ends with a closing tag >
            if stripped.endswith('>'):
                i += 1
                continue
            # Preserve if the next line starts with an opening tag <
            next_stripped = lines[i + 1].lstrip()
            if next_stripped.startswith('<'):
                i += 1
                continue
            bare = re.sub(r'<[^>]*>', '', stripped).rstrip()
            if bare and re.search(_BREAK_PUNCT + r'$', bare):
                lines[i] = stripped          # intentional — keep break, just trim trailing space
                i += 1
            else:
                # Erroneous — merge into next line
                lines[i + 1] = stripped + (' ' if stripped and next_stripped else '') + next_stripped
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
        segment_ends = set()
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            # If this segment is already within the limit, don't re-wrap it
            if self.get_simulated_len(seg) <= limit:
                result_lines.append(seg)
            else:
                result_lines.extend(self._wrap_segment(seg, limit))
            segment_ends.add(len(result_lines) - 1)

        # Step 3: stub balancing — but never across segment boundaries
        result_lines = self._balance_stubs(result_lines, limit, segment_ends)

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

    def _balance_stubs(self, lines, limit, segment_ends=None, stub_ratio=0.40):
        """Eliminate stub lines by pulling words from the preceding line.
        Never crosses segment boundaries (intentional breaks from the source text).
        segment_ends: set of line indices that are the last line of their segment."""
        if len(lines) < 2:
            return lines
        if segment_ends is None:
            segment_ends = {len(lines) - 1}
        lines = list(lines)
        changed = True
        max_passes = len(lines)
        passes = 0
        while changed and passes < max_passes:
            changed = False
            passes += 1
            for i in range(len(lines) - 1, 0, -1):
                # Don't pull across a segment boundary —
                # if line i-1 is the last line of its segment, skip
                if (i - 1) in segment_ends:
                    continue
                line_len = self.get_simulated_len(lines[i])
                if line_len >= limit * stub_ratio:
                    continue
                visible = [t for t in self._tokenise(lines[i]) if t.strip()]
                if not visible:
                    continue
                prev_tokens = self._tokenise(lines[i - 1])
                word_tokens = [(idx, t) for idx, t in enumerate(prev_tokens) if t.strip()]
                if not word_tokens:
                    continue
                last_word_idx, last_word = word_tokens[-1]
                candidate_prev = ''.join(prev_tokens[:last_word_idx]).rstrip()
                candidate_curr = last_word.lstrip() + (' ' if lines[i].strip() else '') + lines[i]
                if (candidate_prev and
                        self.get_simulated_len(candidate_prev) >= 1 and
                        self.get_simulated_len(candidate_curr) <= limit):
                    lines[i - 1] = candidate_prev
                    lines[i]     = candidate_curr.lstrip()
                    changed = True
        return [l for l in lines if l]

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
