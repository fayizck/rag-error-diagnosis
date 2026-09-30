"""Answer-only HotpotQA convention. Source: hotpotqa/hotpot, hotpot_evaluate_v1.py.
The special yes/no/noanswer F1 rule and empty-normalized-answer behavior are preserved.
The downloaded upstream source and its SHA256 are retained for differential tests.
"""
import re
import string
from collections import Counter

def normalize_answer(s):
    text = ''.join(ch for ch in s.lower() if ch not in string.punctuation)
    return ' '.join(re.sub(r'\b(a|an|the)\b', ' ', text).split())

def score(prediction, gold):
    p, g = normalize_answer(prediction), normalize_answer(gold)
    common = sum((Counter(p.split()) & Counter(g.split())).values())
    incompatible = (p in ('yes', 'no', 'noanswer') or g in ('yes', 'no', 'noanswer')) and p != g
    f1 = 0.0
    if common and not incompatible:
        precision, recall = common / len(p.split()), common / len(g.split())
        f1 = 2 * precision * recall / (precision + recall)
    return {'normalized_prediction': p, 'normalized_gold': g, 'em': int(p == g), 'f1': f1}
