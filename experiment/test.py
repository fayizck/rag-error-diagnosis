"""Run offline tests and bind their pass/fail result to current protected source hashes."""
import subprocess
import sys
from .common import ROOT, atomic_json, now
from .freeze import source_hashes

if __name__=='__main__':
    before=source_hashes()
    result=subprocess.run([sys.executable,'-m','pytest','-q','tests','--junitxml=outputs/test_results.xml'],cwd=ROOT)
    after=source_hashes()
    atomic_json(ROOT/'outputs/test_status.json',{'passed':result.returncode==0 and before==after,
                                              'completed_at':now(),'source_hashes':after})
    raise SystemExit(result.returncode or (0 if before==after else 1))
