"""One bounded restart observation, no video generation or automatic retry."""
import time
import uuid
from app import ROOT, LEDGER, read, save
from run_platform_once import main
from run_guarded_platform import settle
import storage_lease


def run(gpu_class='rtx-pro-6000-server',deadline_seconds=600):
    if gpu_class not in ('rtx-pro-6000-server','h100-sxm'):
        raise ValueError('Unsupported probe GPU')
    if deadline_seconds not in (450,600) or (deadline_seconds==450 and gpu_class!='h100-sxm'):
        raise ValueError('Unsupported probe duration')
    config=read(ROOT/'config/guarded-runtime.json')
    folder=ROOT/'data/gen'/('t3-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    save(folder/'execution-plan.json',{'purpose':'model_reuse_probe','execution_id':str(uuid.uuid4()),
         'approved_release_id':config['release_id'],'deadline_seconds':deadline_seconds,
         'gpu_class':gpu_class,'max_credits_reservation':(280 if deadline_seconds==600 else 210) if gpu_class=='h100-sxm' else 202})
    print(str(folder),flush=True)
    try:
        main(config['release_id'],folder,True)
        settle(folder)
    finally:
        if (folder/'storage-lease.json').exists():
            original=read(folder/'storage-lease.json')
            with storage_lease.accounting_lock():
                lease=read(storage_lease.lease_path())
                if lease['id']==original['id']:
                    lease['expires_at']=min(lease['expires_at'],time.time())
                    ledger=read(LEDGER);ledger['storage_leases'][lease['id']]['expires_at']=lease['expires_at'];save(LEDGER,ledger)
                    save(storage_lease.lease_path(),lease)
            while read(storage_lease.lease_path()).get('status')!='deleted':
                time.sleep(3)
    print('Verified storage cleanup: '+str(folder),flush=True)
    if (folder/'execution-error.json').exists():
        raise RuntimeError('Reuse verification failed; cleanup confirmed: '+read(folder/'execution-error.json')['message'])


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--gpu',choices=['rtx-pro-6000-server','h100-sxm'],default='rtx-pro-6000-server')
    parser.add_argument('--deadline-seconds',type=int,choices=[450,600],default=600)
    args=parser.parse_args()
    run(args.gpu,args.deadline_seconds)
