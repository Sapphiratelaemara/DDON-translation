"""
Source Element Validator - Validates that translations preserve source elements.

This module validates that English translations preserve:
1. Tags from tag_map (e.g., <PAWN_NAME>, <VAL PRICE_INN>)
2. Placeholders (e.g., {0}, {1}, %s, %d)
"""

import re
from typing import List, Dict, Tuple, Set
import threading


class SourceValidator:
    """Validates that translations preserve source elements."""

    def __init__(self):
        """Initialize source validator."""
        self._lock = threading.RLock()
        self.tag_map: Dict[str, int] = {}

    def load_tag_map(self, tag_map: Dict[str, int]):
        """
        Load tag map for validation.

        Args:
            tag_map: Dict mapping tag name to simulated length
        """
        with self._lock:
            self.tag_map = tag_map or {}

    def extract_source_elements(self, text: str) -> Dict[str, List[Tuple[int, int]]]:
        """
        Extract all source elements from text.

        Args:
            text: Source text to analyze

        Returns:
            Dict with keys 'tags' and 'placeholders', each containing list of (start, end) tuples
        """
        elements = {
            'tags': [],
            'placeholders': []
        }

        # Extract tags in angle brackets
        # Pattern matches <TAG_NAME> or <TAG WITH SPACES>
        tag_pattern = re.compile(r'<([^>]+)>')
        for match in tag_pattern.finditer(text):
            tag_name = match.group(1)
            start, end = match.span()
            elements['tags'].append((start, end, tag_name))

        # Extract placeholders
        # Pattern matches {0}, {1}, {name}, %s, %d, %f, etc.
        placeholder_patterns = [
            (r'\{[0-9]+\}', 'numeric_index'),  # {0}, {1}, {2}
            (r'\{[a-zA-Z_][a-zA-Z0-9_]*\}', 'named'),  # {name}, {player_name}
            (r'%[sd]', 'printf'),  # %s, %d
        ]

        for pattern, ptype in placeholder_patterns:
            for match in re.finditer(pattern, text):
                start, end = match.span()
                placeholder = match.group(0)
                elements['placeholders'].append((start, end, placeholder, ptype))

        return elements

    def validate_translation(self, source: str, translation: str) -> Dict[str, List[Dict]]:
        """
        Validate that translation preserves all source elements.

        Args:
            source: Source text (JP)
            translation: Translation text (EN)

        Returns:
            Dict with validation errors:
            {
                'missing_tags': [{'tag': 'PAWN_NAME', 'position': 10}],
                'missing_placeholders': [{'placeholder': '{0}', 'type': 'numeric_index'}],
                'extra_tags': [{'tag': 'EXTRA_TAG', 'position': 5}],
                'extra_placeholders': [{'placeholder': '%s', 'type': 'printf'}]
            }
        """
        errors = {
            'missing_tags': [],
            'missing_placeholders': [],
            'extra_tags': [],
            'extra_placeholders': []
        }

        source_elements = self.extract_source_elements(source)
        translation_elements = self.extract_source_elements(translation)

        # Check for missing tags
        source_tags = {tag[2] for tag in source_elements['tags']}
        translation_tags = {tag[2] for tag in translation_elements['tags']}

        for tag in source_tags:
            if tag not in translation_tags:
                # Find position in source
                for start, end, tag_name in source_elements['tags']:
                    if tag_name == tag:
                        errors['missing_tags'].append({
                            'tag': tag,
                            'position': start
                        })
                        break

        # Check for extra tags
        for tag in translation_tags:
            if tag not in source_tags:
                for start, end, tag_name in translation_elements['tags']:
                    if tag_name == tag:
                        errors['extra_tags'].append({
                            'tag': tag,
                            'position': start
                        })
                        break

        # Check for missing placeholders
        source_placeholders = {(ph[2], ph[3]) for ph in source_elements['placeholders']}
        translation_placeholders = {(ph[2], ph[3]) for ph in translation_elements['placeholders']}

        for placeholder, ptype in source_placeholders:
            if (placeholder, ptype) not in translation_placeholders:
                errors['missing_placeholders'].append({
                    'placeholder': placeholder,
                    'type': ptype
                })

        # Check for extra placeholders
        for placeholder, ptype in translation_placeholders:
            if (placeholder, ptype) not in source_placeholders:
                errors['extra_placeholders'].append({
                    'placeholder': placeholder,
                    'type': ptype
                })

        return errors

    def is_valid(self, source: str, translation: str) -> bool:
        """
        Quick check if translation is valid (no missing elements).

        Args:
            source: Source text
            translation: Translation text

        Returns:
            True if valid, False otherwise
        """
        errors = self.validate_translation(source, translation)
        return (
            len(errors['missing_tags']) == 0 and
            len(errors['missing_placeholders']) == 0
        )


def debug_log(message: str, level: str = 'INFO'):
    """Simple debug log function."""
    print(f"[SourceValidator] [{level}] {message}")
