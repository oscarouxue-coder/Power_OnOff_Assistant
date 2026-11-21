"""WAN final checks, sequential original-resource admission and UTF-8 receipts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import argparse


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirmation-only',action='store_true',help='Verify the final confirmation-text-only delta without repeating full baseline')
    options=parser.parse_args()
    output=Path(__file__).resolve().parent
    root=output.parents[1]
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    native_output='qt_wan_ports_verified' if options.confirmation_only else 'qt_wan_verified'
    prefix='wan_confirmation' if options.confirmation_only else 'wan'
    steps=[
        ('unit',['scripts/run_tests.py','test_qt_dut_wan','test_qt_dut_configuration','test_qt_execution_adapter','-v']),
        ('source',['validation/pyside6_migration_20261118/verify_wan.py']),
        ('native',['scripts/verify_qt_migration.py','--output','validation/pyside6_migration_20261118/'+native_output]),
    ]
    if not options.confirmation_only: steps.append(('baseline',['scripts/verify_baseline.py']))
    results=[]
    for name,args in steps:
        print('START',name,flush=True)
        start=time.monotonic()
        result=subprocess.run([sys.executable,*args],cwd=str(root),env=env,
            capture_output=True,text=True,encoding='utf-8',timeout=1800)
        path=output/(prefix+'_'+name+'.txt')
        path.write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        results.append(dict(name=name,passed=result.returncode==0,exit_code=result.returncode,
            seconds=round(time.monotonic()-start,3),output=path.name))
        (output/(prefix+'_checks.json' if options.confirmation_only else 'wan_delivery_checks.json')).write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
        print('FINISH',name,result.returncode,flush=True)
        if result.returncode:
            print((result.stdout+'\n'+result.stderr)[-5000:],flush=True)
            return result.returncode
    return 0


if __name__=='__main__':
    raise SystemExit(main())
