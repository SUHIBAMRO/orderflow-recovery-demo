"""Run after docker compose up. Fails unless the real Temporal-backed stack works."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid

root = Path(__file__).resolve().parent.parent
for line in (root / '.env').read_text().splitlines():
    if line and not line.startswith('#') and '=' in line:
        key, value = line.split('=', 1)
        os.environ.setdefault(key, value)
base = 'http://127.0.0.1:8080'


def call(path, body=None, role='operator', key=None):
    headers = {'Authorization':'Bearer '+os.environ[role.upper()+'_TOKEN'],
               'Content-Type':'application/json','Idempotency-Key':key or uuid.uuid4().hex}
    request = urllib.request.Request(base+path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with urllib.request.urlopen(request, timeout=8) as r:
        return json.load(r)


def wait(ident, target, seconds=90):
    deadline = time.time()+seconds
    while time.time()<deadline:
        value = call('/api/orders/'+ident)['order']
        if value['status'] == target:
            return value
        time.sleep(.5)
    raise AssertionError('Workflow failed to reach '+target)


for _ in range(180):
    try:
        urllib.request.urlopen(base+'/healthz', timeout=2).close()
        break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit('API did not become healthy')

targets={'success':'COMPLETED','missing_photos':'WAITING_PHOTOS','owner_mismatch':'WAITING_CORRECTION',
         'blacklist':'REFUND_REQUIRED','insurer_timeout':'COMPLETED','timeout_after_issue':'COMPLETED',
         'persistent_outage':'MANUAL_REVIEW'}
created={}
for scenario,target in targets.items():
    key=uuid.uuid4().hex
    a=call('/api/orders',{'scenario':scenario},key=key)
    b=call('/api/orders',{'scenario':scenario},key=key)
    assert a['id']==b['id'], 'Duplicate order created'
    created[scenario]=wait(a['id'],target)
    print('PASS',scenario,target)

for scenario,action in [('missing_photos','confirm_photos'),('owner_mismatch','correct_owner'),('blacklist','approve_refund')]:
    order=created[scenario]
    payload={'note':'Smoke test: synthetic evidence reviewed','expected_version':order['version']}
    if action=='correct_owner':payload['owner_last4']='5678'
    if action=='approve_refund':
        try:
            call(f"/api/orders/{order['id']}/actions/{action}",payload)
            raise AssertionError('Operator was able to approve a refund')
        except urllib.error.HTTPError as e:
            assert e.code==403
    key=uuid.uuid4().hex
    role='supervisor' if action=='approve_refund' else 'operator'
    a=call(f"/api/orders/{order['id']}/actions/{action}",payload,role,key)
    b=call(f"/api/orders/{order['id']}/actions/{action}",payload,role,key)
    assert a==b
    final=wait(order['id'],'ROADTAX_REFUNDED' if action=='approve_refund' else 'COMPLETED')
    if order['policy_ref']:assert order['policy_ref']==final['policy_ref']
    print('PASS',action,'idempotent and resumed')

# Restart the real worker with a waiting workflow, then resolve the same order.
order=call('/api/orders',{'scenario':'owner_mismatch'})
waiting=wait(order['id'],'WAITING_CORRECTION')
subprocess.run(['docker','compose','restart','worker'],cwd=root,check=True)
call(f"/api/orders/{order['id']}/actions/correct_owner",{'note':'Corrected after worker restart',
     'expected_version':waiting['version'],'owner_last4':'5678'})
wait(order['id'],'COMPLETED')
print('PASS real worker restart and workflow continuation')
print('Deployment smoke checks completed; no real external transactions were performed.')
