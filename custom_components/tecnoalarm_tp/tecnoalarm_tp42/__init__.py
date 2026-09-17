"""Client Python per centrali Tecnoalarm serie TP (TP4/8/10/42) via IP.

    from tecnoalarm_tp42 import TP42Panel
    with TP42Panel("192.168.1.50", 10001, code="1234", passphrase="miapass") as panel:
        for p in panel.get_programs():
            print(p.n, p.name, p.armed)
        panel.arm(1)

Vendorizzato in questa integrazione da https://github.com/ (tecnoalarm-tp42),
con una sola aggiunta: la proprieta' TP42Panel.connected (vedi client.py).
"""
from .client import (TP42Panel, Program, Zone, Telecommand, PanelStatus,
                     TP42Error, DEFAULT_KEY)

__all__ = ["TP42Panel", "Program", "Zone", "Telecommand", "PanelStatus",
           "TP42Error", "DEFAULT_KEY"]
__version__ = "1.4.0"
