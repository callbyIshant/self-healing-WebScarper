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
        def extract_structure(text: str) -> set[str]:
            return set(re.findall(r'[a-zA-Z]+', text.lower()))
            
        proposed_struct = extract_structure(proposed_ax)
        lkg_struct = extract_structure(lkg_ax)
        
        if not proposed_struct and not lkg_struct:
            return 1.0
        if not proposed_struct or not lkg_struct:
            return 0.5
            
        intersection = len(proposed_struct.intersection(lkg_struct))
        union = len(proposed_struct.union(lkg_struct))
        return intersection / union if union > 0 else 0.5

    def semantic_similarity(self, proposed_text: str, lkg_text: str) -> float:
        def get_words(text: str) -> list[str]:
            return re.findall(r'\w+', text.lower())
            
        words1 = get_words(proposed_text)
        words2 = get_words(lkg_text)
        
        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.5
            
        counter1 = Counter(words1)
        counter2 = Counter(words2)
        
        terms = set(counter1.keys()).union(set(counter2.keys()))
        dot_product = sum(counter1.get(t, 0) * counter2.get(t, 0) for t in terms)
        
        mag1 = math.sqrt(sum(v**2 for v in counter1.values()))
        mag2 = math.sqrt(sum(v**2 for v in counter2.values()))
        
        if mag1 == 0 or mag2 == 0:
            return 0.5
            
        return dot_product / (mag1 * mag2)

    def role_match_score(self, proposed_role: Optional[str], lkg_role: Optional[str]) -> float:
        if proposed_role is None and lkg_role is None:
            return 1.0
        if proposed_role is None or lkg_role is None:
            return 0.8
            
        p_role = proposed_role.strip().lower()
        l_role = lkg_role.strip().lower()
        
        if p_role == l_role:
            return 1.0
        if p_role in l_role or l_role in p_role:
            return 0.7
        return 0.5

    def value_format_match(self, proposed_value: str, lkg_sample: str) -> float:
        def get_type(val: str) -> str:
            val_clean = val.strip()
            if re.search(r'[\$£€]?\s*\d+(\.\d+)?', val_clean):
                return 'currency_or_number'
            if re.match(r'^\d{4}-\d{2}-\d{2}', val_clean) or re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}', val_clean):
                return 'date'
            if '@' in val_clean and '.' in val_clean:
                return 'email'
            return 'string'
            
        if not lkg_sample:
            # If no LKG sample, check if proposed value has a recognizable non-empty format
            return 1.0 if proposed_value.strip() else 0.5
            
        if get_type(proposed_value) == get_type(lkg_sample):
            return 1.0
        return 0.4

    def compute_confidence(
        self,
        proposed_ax_tree: str,
        proposed_text: str,
        proposed_role: Optional[str],
        proposed_value: str,
        lkg_snapshot: Optional[LKGSnapshot]
    ) -> float:
        w_struct = 0.3
        w_sem = 0.3
        w_role = 0.25
        w_val = 0.15
        
        if not lkg_snapshot:
            # No prior LKG baseline exists — base confidence on format and text presence
            format_score = self.value_format_match(proposed_value or proposed_text, "")
            return 0.85 * format_score
        
        lkg_ax = lkg_snapshot.ax_tree_neighborhood or ""
        lkg_text = lkg_snapshot.text_signature or ""
        lkg_role = lkg_snapshot.strategy.value if lkg_snapshot.strategy else None
        lkg_sample = str(lkg_snapshot.sample_value or "")
        
        score = 0.0
        score += w_struct * self.structural_similarity(proposed_ax_tree, lkg_ax)
        score += w_sem * self.semantic_similarity(proposed_text or proposed_ax_tree, lkg_text)
        score += w_role * self.role_match_score(proposed_role, lkg_role)
        score += w_val * self.value_format_match(proposed_value or proposed_text, lkg_sample)
        
        return min(max(score, 0.0), 1.0)
