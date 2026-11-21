"""Sequential WiFi gates; collect failures without bypassing native isolation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    output=Path(__file__).resolve().parent
    root=output.parents[1]
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    steps=[
        ('unit',['scripts/run_tests.py','test_qt_dut_wifi','test_qt_dut_wan','test_qt_dut_configuration','test_qt_execution_adapter','-v']),
        ('source',['validation/pyside6_migration_20261118/verify_wifi.py']),
        ('native',['scripts/verify_qt_migration.py','--output','validation/pyside6_migration_20261118/qt_wifi_verified']),
        ('baseline',['scripts/verify_baseline.py']),
    ]
    results=[]
    for name,args in steps:
        print('START',name,flush=True)
        start=time.monotonic()
        result=subprocess.run([sys.executable,*args],cwd=str(root),env=env,
            capture_output=True,text=True,encoding='utf-8',timeout=1800)
        path=output/('wifi_'+name+'.txt')
        path.write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        results.append(dict(name=name,passed=result.returncode==0,exit_code=result.returncode,
            seconds=round(time.monotonic()-start,3),output=path.name))
        (output/'wifi_delivery_checks.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
        print('FINISH',name,result.returncode,flush=True)
        if result.returncode:print((result.stdout+'\n'+result.stderr)[-1200:],flush=True)
        # A source/unit failure is a code gate; do not bury it in later runs.
        if result.returncode and name in ('unit','source'):return result.returncode
    return 0 if all(r['passed'] for r in results) else 1


if __name__=='__main__':
    raise SystemExit(main())
