"""Fail-closed Comfy dependency gate. Billing and GPU savings are not implied."""
import hashlib
from pathlib import Path


def permitted(envelope, stage_id):
    if not isinstance(envelope, dict) or not isinstance(stage_id, str) or not stage_id:
        return False
    report=envelope.get('report', {});context=envelope.get('stage_context', {})
    if not isinstance(report,dict) or not isinstance(context,dict):return False
    if (report.get('schema_version') not in ('mg-report-2','mg-report-3') or report.get('verdict')!='PASS'
            or report.get('failures')!=[] or report.get('uncertain_reasons')!=[]
            or not isinstance(report.get('metrics'),dict) or not report['metrics']
            or context.get('stage_id')!=stage_id):return False
    sources=report.get('sources')
    if not isinstance(sources,dict) or set(sources)!={'reference','generated','gt'} or context.get('sources')!=sources:return False
    try:
        return all(hashlib.sha256(Path(v['path']).read_bytes()).hexdigest()==v['sha256'] for v in sources.values())
    except (OSError,KeyError,TypeError):return False


class MG_StageGate:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'report':('MG_REPORT',),'stage_id':('STRING',),'latent':('LATENT',{'lazy':True})}}
    RETURN_TYPES=('LATENT',);FUNCTION='gate';CATEGORY='MotionGuard'
    def check_lazy_status(self,report,stage_id,latent=None):
        return ['latent'] if permitted(report,stage_id) and latent is None else []
    def gate(self,report,stage_id,latent=None):
        from comfy_execution.graph import ExecutionBlocker
        if (not permitted(report,stage_id) or not isinstance(latent,dict)
                or latent.get('motion_guard_stage_id')!=stage_id):
            return (ExecutionBlocker(None),)
        return (latent,)
