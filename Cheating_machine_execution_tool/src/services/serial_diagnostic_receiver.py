"""Data-only passive diagnostic subscriber, independent of service/UI graphs."""


class SerialDiagnosticReceiver:
    def __init__(self, lock, shutdown, trigger, redactor):
        self.lock, self.shutdown = lock, shutdown
        self.trigger, self.redactor = trigger, redactor
        self.targets = {}
        self.pending = {}

    def __call__(self, vlan, event):
        if self.shutdown.is_set() or event.direction != 'RX':
            return
        with self.lock:
            key = vlan.casefold(), event.port.upper()
            pending = self.pending.get(key, '') + event.text
            lines = pending.replace('\r\n', '\n').replace('\r', '\n').split('\n')
            self.pending[key] = lines[-1] if len(lines[-1]) <= 8192 else ''
            for target in tuple(self.targets.values()):
                if target.port.upper() == event.port.upper() and target.vlan.casefold() == vlan.casefold():
                    for line in lines[:-1]:
                        self.trigger.append(target.channel, '[串口RX] ' + self.redactor.text(line))
