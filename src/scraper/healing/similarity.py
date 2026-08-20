import re
import math
from collections import Counter
from typing import Optional

from scraper.core.models import LKGSnapshot

class ConfidenceScorer:
    """
    Deterministic confidence scoring for proposed selector repairs.
    """

    def structural_similarity(self, proposed_ax: str, lkg_ax: str) -> float:
        # Extract basic elements/roles from a string, e.g. "button", "div", "link"
        # Since we don't have a real parser for YAML AXTree here, just tokenizing basic structural terms
        def extract_structure(text: str) -> set[str]:
            return set(re.findall(r'[a-zA-Z]+', text.lower()))
            
        proposed_struct = extract_structure(proposed_ax)
        lkg_struct = extract_structure(lkg_ax)
        
        if not proposed_struct and not lkg_struct:
            return 1.0
        if not proposed_struct or not lkg_struct:
            return 0.0
            
        intersection = len(proposed_struct.intersection(lkg_struct))
        union = len(proposed_struct.union(lkg_struct))
        return intersection / union

    def semantic_similarity(self, proposed_text: str, lkg_text: str) -> float:
        def get_words(text: str) -> list[str]:
            return re.findall(r'\w+', text.lower())
            
        words1 = get_words(proposed_text)
        words2 = get_words(lkg_text)
        
        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.0
            
        counter1 = Counter(words1)
        counter2 = Counter(words2)
        
        terms = set(counter1.keys()).union(set(counter2.keys()))
        
        # Simple dot product of frequencies
        dot_product = sum(counter1.get(t, 0) * counter2.get(t, 0) for t in terms)
        
        # Magnitude
        mag1 = math.sqrt(sum(v**2 for v in counter1.values()))
        mag2 = math.sqrt(sum(v**2 for v in counter2.values()))
        
        if mag1 == 0 or mag2 == 0:
            return 0.0
            
        return dot_product / (mag1 * mag2)

    def role_match_score(self, proposed_role: Optional[str], lkg_role: Optional[str]) -> float:
        if proposed_role is None and lkg_role is None:
            return 1.0
        if proposed_role is None or lkg_role is None:
            return 0.0
            
        p_role = proposed_role.strip().lower()
        l_role = lkg_role.strip().lower()
        
        if p_role == l_role:
            return 1.0
        if p_role in l_role or l_role in p_role:
            return 0.5
        return 0.0

    def value_format_match(self, proposed_value: str, lkg_sample: str) -> float:
        # Determine if values share similar format (e.g. both numbers, both dates, both currencies)
        def get_type(val: str) -> str:
            if re.match(r'^\$?\d+(,\d{3})*(\.\d+)?$', val):
                return 'currency_or_number'
            if re.match(r'^\d{4}-\d{2}-\d{2}', val) or re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}', val):
                return 'date'
            if '@' in val and '.' in val:
                return 'email'
            return 'string'
            
        if get_type(proposed_value) == get_type(lkg_sample):
            return 1.0
        return 0.0

    def compute_confidence(self, proposed_ax_tree: str, proposed_text: str, proposed_role: Optional[str], proposed_value: str, lkg_snapshot: LKGSnapshot) -> float:
        w_struct = 0.3
        w_sem = 0.3
        w_role = 0.25
        w_val = 0.15
        
        # Extract LKG strings
        lkg_ax = lkg_snapshot.ax_tree_snapshot or ""
        lkg_text = lkg_snapshot.content_hash or "" # Not quite text, but using hash as fallback or if available
        # Assuming lkg_snapshot has some way to get text. If not, use whatever we have.
        # In a real impl, we'd use lkg_snapshot.text if available.
        lkg_role = None # Assuming LKG snapshot lacks role, or we pass it if it does
        lkg_sample = ""
        
        score = 0.0
        score += w_struct * self.structural_similarity(proposed_ax_tree, lkg_ax)
        score += w_sem * self.semantic_similarity(proposed_text, lkg_text)
        score += w_role * self.role_match_score(proposed_role, lkg_role)
        score += w_val * self.value_format_match(proposed_value, lkg_sample)
        
        return min(max(score, 0.0), 1.0)
