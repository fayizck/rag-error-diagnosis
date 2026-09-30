import numpy as np

CONTRASTS = {
    'partial_vs_none_primary': [-1, .5, .5, 0],
    'complete_vs_partial': [0, -.5, -.5, 1],
    'complete_vs_none': [-1, 0, 0, 1],
    'cue_interaction_exploratory': [1, -1, -1, 1],
}

def paired_summary(matrix, seed, resamples=10000):
    y = np.asarray(matrix, dtype=float)
    if y.ndim != 2 or y.shape[1] != 4 or len(y) < 2 or not np.isfinite(y).all():
        raise ValueError('Need at least two complete question blocks with four finite outcomes each')
    rng = np.random.default_rng(seed)
    boot = np.empty((resamples, 4))
    for start in range(0, resamples, 250):
        n = min(250, resamples-start)
        indices = rng.integers(0, len(y), size=(n, len(y)))
        boot[start:start+n] = y[indices].mean(axis=1)
    def interval(values): return [float(x) for x in np.quantile(values, [.025, .975], method='linear')]
    conditions = [{'condition': c, 'n': len(y), 'estimate': float(y[:,j].mean()),
                   'ci_low': interval(boot[:,j])[0], 'ci_high': interval(boot[:,j])[1]}
                  for j,c in enumerate(('00','10','01','11'))]
    contrasts = []
    for name, weights in CONTRASTS.items():
        w = np.asarray(weights)
        lo, hi = interval(boot @ w)
        contrasts.append({'contrast': name, 'n': len(y), 'estimate': float((y@w).mean()), 'ci_low': lo, 'ci_high': hi,
                          'status': 'primary' if name.endswith('primary') else 'exploratory_secondary'})
    return conditions, contrasts
