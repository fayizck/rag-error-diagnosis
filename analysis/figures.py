"""Scientific plots and tables from saved main summaries only."""
import os
import tempfile
os.environ.setdefault('MPLCONFIGDIR', tempfile.mkdtemp(prefix='c2-matplotlib-'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from experiment.common import ROOT, read_json, require

def create_exhibits(summary, out):
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False})
    rows=summary['condition_results']; cs=[r for r in summary['contrasts'] if r['outcome']=='EM']
    fig,(ax,bx)=plt.subplots(1,2,figsize=(10,3.8),layout='constrained')
    estimates=np.array([r['estimate'] for r in rows])*100
    ax.errorbar(range(4),estimates,yerr=[estimates-np.array([r['ci_low'] for r in rows])*100,
                np.array([r['ci_high'] for r in rows])*100-estimates],fmt='o',capsize=4,color='#176b87')
    ax.set(xticks=range(4),xticklabels=['00\nNeither','10\nA only','01\nB only','11\nBoth'],ylabel='Answer EM (%)',ylim=(-2,102),yticks=range(0,101,20),title='Accuracy by condition')
    estimates=np.array([r['estimate'] for r in cs])*100
    bx.errorbar(estimates,range(4),xerr=[estimates-np.array([r['ci_low'] for r in cs])*100,
                 np.array([r['ci_high'] for r in cs])*100-estimates],fmt='o',capsize=4,color='#78478c')
    bx.axvline(0,color='0.6',linewidth=.8);bx.set(yticks=range(4),yticklabels=['Partial - none','Both - partial','Both - none','Interaction'],xlabel='Paired difference (percentage points)',title='Paired contrasts (95% bootstrap CI)');bx.invert_yaxis()
    for ext in ('pdf','png'):fig.savefig(out/f'figure_1_accuracy.{ext}',dpi=300)
    plt.close(fig)
    t=summary['transitions']; fig,ax=plt.subplots(figsize=(6.4,3.6),layout='constrained')
    x=np.arange(3);ax.bar(x-.18,[r['repair'] for r in t],.36,label='Repairs',color='#176b87');ax.bar(x+.18,[r['harm'] for r in t],.36,label='Harms',color='#b85450')
    ax.set(xticks=x,xticklabels=['Partial: A (10)','Partial: B (01)','Complete (11)'],ylabel='Number of questions',title=f'Answer transitions versus 00 (n={summary["n_complete"]})');ax.legend(frameon=False)
    from matplotlib.ticker import MaxNLocator
    ax.set_ylim(bottom=0, top=max(1, max(r[k] for r in t for k in ('repair','harm')) * 1.15))
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    for ext in ('pdf','png'):fig.savefig(out/f'figure_2_transitions.{ext}',dpi=300)
    plt.close(fig)
    text=['# Tables generated from frozen main outputs\n','## Table 1. Conditions and controls\n',
          '| Condition | A support focus | B support focus | Other sentences |\n|---|---|---|---|',
          '| 00 | 0 | 0 | 0 |\n| 10 | 1 | 0 | 0 |\n| 01 | 0 | 1 | 0 |\n| 11 | 1 | 1 | 0 |',
          '\nQuestion, titles, paragraph/sentence order and raw text are fixed.\n',
          '## Table 2. Per-condition outcomes\n', '| Condition | n complete | EM | F1 | Valid outputs | Technical failures |\n|---|---|---|---|---|---|']
    for r in rows:text.append(f'| {r["condition"]} | {r["n"]} | {r["estimate"]:.3f} | {r["mean_f1"]:.3f} | {r["valid_outputs"]} | {r["technical_failures"]} |')
    text+=['\n## Table 3. Paired EM contrasts\n','| Contrast | Estimate | 95% CI |\n|---|---|---|']
    for r in cs:text.append(f'| {r["contrast"]} | {r["estimate"]:.3f} | [{r["ci_low"]:.3f}, {r["ci_high"]:.3f}] |')
    (out/'tables.md').write_text('\n'.join(text)+'\n')

if __name__=='__main__':
    from experiment.freeze import verify_freeze
    from .reconcile import reconcile
    frozen=verify_freeze();summary=read_json(ROOT/'outputs/analysis/summary.json');seal=read_json(ROOT/'outputs/main/sealed_outputs.json')
    require(summary['split']=='main' and summary['freeze_sha256']==frozen['freeze_sha256'], 'Not frozen main summary')
    require(summary['sealed_outputs_sha256']==seal['logical_outputs_sha256']==reconcile()['logical_outputs_sha256'], 'Main snapshot changed')
    create_exhibits(summary,ROOT/'outputs/analysis')
