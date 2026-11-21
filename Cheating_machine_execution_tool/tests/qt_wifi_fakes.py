"""Real WiFi batch/single/core code with dictionary-backed UBUS and fake time."""
from types import SimpleNamespace
import threading
import test_dut_wifi_config as core_fixtures
from qt_dut_fakes import DutHarness
from src.services.dut_advanced_config_service import run_dut_advanced_config_batch, run_single_dut_advanced_config
from src.services.dut_status_query_service import run_dut_status_query_batch, run_single_dut_status_query


class WifiHarness(DutHarness):
    def __init__(self):
        super().__init__()
        self.states={}
        self.events=[]
        self.sessions=[]
        self.shared=[]
        self.mapping_count=8
        self.settle_entered=threading.Event()
        self.release_settle=threading.Event();self.release_settle.set()
        self.mismatch=False
        self.lock=threading.RLock()

    def state(self,channel):
        with self.lock:
            return self.states.setdefault(channel,core_fixtures._FakeWifiClient())

    def client(self,request):
        state=self.state(request.channel)
        session=SimpleNamespace(closed=False)
        def get(sid,path,optional=None):
            if path in ('Device.WiFi.X_SDMC_Mapping_2G','Device.WiFi.X_SDMC_Mapping_5G'):
                band='2G' if path.endswith('2G') else '5G'
                state.calls.append(('get',sid,path,optional))
                return [0,{'X_SDMC_Mapping_'+band:'@'.join(['1,1,1' if band=='2G' else '2,2,2']*self.mapping_count)}]
            return state.bbfdm_get(sid,path,optional)
        def close():session.closed=True
        session.login=lambda *a:'fixture-session'
        session.logout=lambda *a:None
        session.close=close
        session.bbfdm_get=get
        session.call=state.call
        self.sessions.append(session)
        return session

    def pause(self,seconds,stop,channel):
        with self.lock:self.events.append(('wait',channel,seconds))
        if seconds==60:
            self.settle_entered.set()
            while not self.release_settle.wait(.01):
                if stop.is_set():self.stop_seen.set()
            if self.mismatch:
                for state in self.states.values():
                    for ssid in state.ssids.values():ssid['SSID']='fixture-mismatched-readback'

    def configure(self,request,**kwargs):
        self._wait(request,kwargs['stop_event'])
        with self.lock:self.events.append((kwargs.get('wifi_phase','configure'),request.channel,request.settings.ssid))
        if kwargs.get('wifi_phase')=='verify' and self.mismatch:
            for ssid in self.state(request.channel).ssids.values():ssid['SSID']='fixture-mismatched-readback'
        return run_single_dut_advanced_config(request,**kwargs,network_prepare_fn=self._prepare,
            bind_waiter=lambda *a:True,client_factory=lambda *a,**kw:self.client(request),
            sleep_fn=lambda seconds:self.pause(seconds,kwargs['stop_event'],request.channel))

    def configure_batch(self,requests,**kwargs):
        self.workers.append(kwargs['max_workers']);self.shared.append(kwargs.get('shared_wifi_settle',False))
        return run_dut_advanced_config_batch(requests,single_runner=self.configure,
            sleep_fn=lambda seconds:self.pause(seconds,kwargs['stop_event'],'batch'),**kwargs)

    def query(self,request,feature,**kwargs):
        self._wait(request,kwargs['stop_event'])
        return run_single_dut_status_query(request,feature,**kwargs,network_prepare_fn=self._prepare,
            bind_waiter=lambda *a:True,client_factory=lambda *a,**kw:self.client(request),sleep_fn=lambda seconds:None)

    def query_batch(self,requests,feature,**kwargs):
        self.workers.append(kwargs['max_workers'])
        return run_dut_status_query_batch(requests,feature,single_runner=self.query,**kwargs)
