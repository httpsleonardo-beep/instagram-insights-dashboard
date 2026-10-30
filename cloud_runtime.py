"""Coleta compartilhada; seleções e exportações isoladas por filtros."""
from __future__ import annotations
import copy
import json
import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote
from scraper import TZ, collect
from extra_scraper import collect_extra
from filters import selection, snapshot_selection
from views import apply_view
from settings import AppError, DEFAULTS
from storage import Store, export_names

def account_from_session(secret):
    if not isinstance(secret,str) or not secret.strip():
        raise AppError('session_missing','Configure INSTAGRAM_SESSIONID nos Secrets do Streamlit.')
    account=unquote(secret.strip()).split(':',1)[0]
    if not account.isdigit():
        raise AppError('session_invalid','INSTAGRAM_SESSIONID não contém um cookie sessionid válido.')
    return account

class Runtime:
    def __init__(self,account_id,folder:Path,collector=None,cooldown=120):
        self.account_id=account_id;self.store=Store(folder);self.collector=collector
        self.cooldown=cooldown;self.lock=threading.RLock();self.worker=None;self.busy=False
        self.last_started=None;self.message='Escolha os filtros e clique em Atualizar dados.';self.error=None
        self.exports=OrderedDict()

    def progress(self,message):
        with self.lock:self.message=message

    def state(self,selected=None,view=None):
        selected=selection(selected)
        with self.lock:
            seconds=max(0,int(self.cooldown-(time.monotonic()-self.last_started))+1) if self.last_started is not None else 0
            snapshot=self.store.latest_for(self.account_id,selected)
            snapshot=apply_view(snapshot,view or {}) if snapshot else None
            downloads=None
            if snapshot:
                key=json.dumps([selected,view or {},snapshot['collected_at']],sort_keys=True)
                if key not in self.exports:
                    self.store.export(snapshot)
                    excel_name,json_name=export_names(snapshot)
                    self.exports[key]={'excel':(self.store.folder/excel_name).read_bytes(),'json':(self.store.folder/json_name).read_bytes(),'excel_name':excel_name,'json_name':json_name}
                    if len(self.exports)>24:self.exports.popitem(last=False)
                downloads=self.exports[key]
            return {'busy':self.busy,'message':self.message,'error':self.error,'cooldown':seconds,'snapshot':copy.deepcopy(snapshot),'downloads':downloads}

    def start(self,secret,selected=None):
        if account_from_session(secret)!=self.account_id:
            raise AppError('account_mismatch','A conta configurada mudou. Recarregue a página.')
        selected=selection(selected)
        with self.lock:
            if self.busy:return False,'Uma coleta já está em andamento.'
            if self.last_started is not None and time.monotonic()-self.last_started<self.cooldown:
                return False,'Aguarde o intervalo mínimo de dois minutos entre coletas.'
            self.busy=True;self.error=None;self.message='Iniciando coleta…';self.last_started=time.monotonic()
            self.worker=threading.Thread(target=self._run,args=(secret.strip(),selected),daemon=True,name='instagram-insights-collector')
            self.worker.start()
            return True,self.message

    def _run(self,secret,selected):
        timestamp=datetime.now(TZ).isoformat(timespec='seconds')
        try:
            cfg=DEFAULTS|{'sessionid':secret,'headless':True,'data_path':self.store.folder,'selection':selected}
            collector=self.collector or (collect if selected['scope']=='account' else collect_extra)
            result=collector(cfg,self.progress)
            if result['account']['id']!=self.account_id or snapshot_selection(result)!=selected:
                raise AppError('selection_mismatch','A fonte retornou outra conta ou outros filtros. Os dados não foram salvos.')
            with self.lock:
                self.store.save(result);self.exports.clear()
                self.message='Coleta concluída.' if result['status']=='complete' else 'Coleta parcial: alguns dados não foram retornados.'
        except Exception as error:
            code=error.code if isinstance(error,AppError) else 'collection_failed'
            message=str(error) if isinstance(error,AppError) else 'Não foi possível concluir a coleta. O último resultado válido desta seleção foi preservado.'
            message=message.replace(secret,'[OCULTO]').replace(unquote(secret),'[OCULTO]')
            with self.lock:
                self.error=message;self.message='A atualização não foi concluída.';self.exports.clear()
                try:self.store.failure(timestamp,code,message,self.account_id)
                except Exception:pass
            logging.getLogger('insights').warning('Coleta encerrada com código %s',code)
        finally:
            secret=None
            with self.lock:self.busy=False
