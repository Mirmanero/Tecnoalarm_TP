# -*- coding: utf-8 -*-
"""Client per centrali Tecnoalarm serie TP (TP4/8/10/42) via IP.

Dipendenza: pycryptodome  (pip install pycryptodome)

Vendorizzato in tecnoalarm_tp da https://github.com/ (tecnoalarm-tp42).
Unica modifica rispetto all'originale: proprieta' TP42Panel.connected,
per permettere al chiamante di distinguere una lettura riuscita da una
in cui la connessione e' effettivamente caduta (i metodi get_* di questo
client, in caso di errore, ritornano valori di default "sicuri" invece di
sollevare un'eccezione: senza .connected il chiamante non potrebbe
accorgersi della disconnessione).
"""

import os
import re
import socket
import time

try:
    from Cryptodome.Cipher import AES
except ImportError:  # pragma: no cover
    from Crypto.Cipher import AES

# Chiave usata quando la porta della centrale non ha una passphrase impostata.
DEFAULT_KEY = bytes.fromhex("5807d29adf204c1a690831e2f371bac9")

_DLE, _STX = 0x10, 0x02
_REC_AUTH, _REC_MKOPER = 2305, 2306
_REC_STATZON, _REC_GRU = 2316, 2317
_REC_PNAME, _REC_ZNAME, _REC_TNAME = 2307, 2310, 2308
_REC_STATUS = 2318
_REC_ZISOLA, _REC_ZREINT = 2320, 2321   # 0x0910 isola / 0x0911 reintegra zona
_OP_INS, _OP_DIS = 3, 4
_OP_TELEC_ON, _OP_TELEC_OFF = 11, 12
# Comandi del protocollo "diretto" (usati dal software Centro) per il GSM.
# Frame: 10 02 | cmd(2) | idx(2) | datalen(2) | dati | crc; risposta 10 0c ...
_CMD_GSM_INFO = 0x9995   # operatore + versione/modello modulo GSM

PROGRAM_STATES = {
    0: "riposo", 1: "pre-uscita", 2: "in uscita", 3: "inserito",
    4: "uscita parziale", 5: "inserito parziale", 6: "fine parziale",
}


class TP42Error(Exception):
    """Errore di comunicazione o autenticazione con la centrale."""


class Program(object):
    """Stato di un programma (gruppo). Attributi: n, name, state, armed."""
    __slots__ = ("n", "name", "state", "armed", "raw")

    def __init__(self, n, name, raw):
        self.n = n
        self.name = name
        self.raw = raw
        st = raw & 0x0F
        self.state = PROGRAM_STATES.get(st, "sconosciuto")
        self.armed = st != 0

    def __repr__(self):
        return "Program(%d, %r, %s%s)" % (
            self.n, self.name, self.state, ", ARMATO" if self.armed else "")


class Zone(object):
    """Stato di una zona. Attributi: n, name, open, excluded, configured."""
    __slots__ = ("n", "name", "open", "excluded", "configured", "raw")

    def __init__(self, n, name, raw4):
        self.n = n
        self.name = name
        self.raw = raw4
        b0 = raw4[0] if raw4 else 0
        self.configured = bool(b0 & 0x80)
        self.excluded = bool(b0 & 0x01)
        self.open = bool(b0 & 0x02)

    def __repr__(self):
        s = "aperta" if self.open else "chiusa"
        if self.excluded:
            s += ", esclusa"
        return "Zone(%d, %r, %s)" % (self.n, self.name, s)


class Telecommand(object):
    """Stato di un'uscita telecomando. Attributi: n, name, active."""
    __slots__ = ("n", "name", "active")

    def __init__(self, n, name, active):
        self.n = n
        self.name = name
        self.active = active

    def __repr__(self):
        return "Telecommand(%d, %r, %s)" % (
            self.n, self.name, "ATTIVO" if self.active else "spento")


class PanelStatus(object):
    """Stati generali della centrale (16 byte).

    Booleani utili: in_alarm, siren_internal, siren_external, panic,
    tamper, battery_low, mains_loss, faults, gsm_present, standby,
    exit_time, maintenance, program_alarm, alarm_memory.
    """
    __slots__ = ("raw", "standby", "faults", "battery_low", "mains_loss",
                 "tamper", "holdup", "program_alarm",
                 "exit_time", "maintenance", "siren_internal",
                 "siren_external", "panic", "alarm_memory", "in_alarm")

    def __init__(self, raw):
        raw = raw or b"\x00" * 16
        self.raw = raw

        def bit(i, b):
            return bool(raw[i] & (1 << b)) if i < len(raw) else False

        # BYTE 9 (idx 8)
        self.standby = bit(8, 0)
        self.faults = bit(8, 1)
        self.battery_low = bit(8, 2)
        self.mains_loss = bit(8, 3)
        self.tamper = bit(8, 4)
        self.holdup = bit(8, 6)
        # BYTE 10 (idx 9)
        self.program_alarm = bit(9, 5)
        # BYTE 12 (idx 11)
        self.exit_time = bit(11, 1)
        self.maintenance = bit(11, 2)
        # BYTE 15 (idx 14)
        self.panic = bit(14, 0)
        self.siren_internal = bit(14, 1)
        self.siren_external = bit(14, 2)
        # BYTE 11 (idx 10): riepilogo allarmi (manomissione, rapina, tecnico...)
        alarms = raw[10] if len(raw) > 10 else 0
        # BYTE 12 (idx 11) bit0: memoria allarme
        self.alarm_memory = bit(11, 0)
        self.in_alarm = bool(self.program_alarm or self.siren_internal
                             or self.siren_external or self.panic or alarms)

    def __repr__(self):
        f = []
        if self.in_alarm:
            f.append("ALLARME")
        if self.siren_internal or self.siren_external:
            f.append("SIRENA")
        if self.mains_loss:
            f.append("manca rete")
        if self.battery_low:
            f.append("batt. bassa")
        if self.tamper:
            f.append("manomissione")
        return "PanelStatus(%s)" % (", ".join(f) or "ok")


def _crc16(data, start=0, length=None):
    if length is None:
        length = len(data) - start
    s = 0xFFFF
    for i in range(length):
        s ^= data[start + i] & 0xFF
        for _ in range(8):
            s = (s >> 1) ^ 0xA001 if (s & 1) else s >> 1
    return s & 0xFFFF


def _dle_encode(data):
    out = bytearray(data[:2])
    for b in data[2:]:
        out.append(b)
        if b == _DLE:
            out.append(_DLE)
    return bytes(out)


def _dle_decode(data):
    if not data or data[0] != _DLE:
        return data
    out = bytearray(data[:2])
    i = 2
    while i < len(data):
        if data[i] == _DLE and i + 1 < len(data) and data[i + 1] == _DLE:
            out.append(_DLE)
            i += 2
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


def _build(utn, rec, idx, payload):
    dl = len(payload)
    m = bytearray(16 + dl)
    m[0] = _DLE
    m[1] = _STX
    m[2] = 0x00
    m[3] = 0x09
    m[4] = utn & 0xFF; m[5] = (utn >> 8) & 0xFF
    tot = dl + 6
    m[6] = tot & 0xFF; m[7] = (tot >> 8) & 0xFF
    m[8] = rec & 0xFF; m[9] = (rec >> 8) & 0xFF
    m[10] = idx & 0xFF; m[11] = (idx >> 8) & 0xFF
    m[12] = dl & 0xFF; m[13] = (dl >> 8) & 0xFF
    m[14:14 + dl] = payload
    crc = _crc16(bytes(m), 2, dl + 12)
    m[14 + dl] = crc & 0xFF; m[15 + dl] = (crc >> 8) & 0xFF
    return bytes(m)


def _parse_appid(s):
    c = s.replace("0x", "").replace("0X", "")
    if len(c) == 4 and all(x in "0123456789abcdefABCDEF" for x in c):
        return int(c[0:2], 16) | (int(c[2:4], 16) << 8)
    return int(c) if c else 0


class _Cipher(object):
    """CFB-128 byte per byte con stato continuo (ive/ivd + posizione).

    Implementazione fedele al sorgente ufficiale Tecnoalarm (AesCfb128):
    lo stato prosegue tra un messaggio e l'altro, per cui gestisce
    lunghezze qualsiasi (anche i comandi non multipli di 16 byte) senza
    desincronizzare. Una sola sessione regge letture e comandi.
    """

    def __init__(self, key, iv):
        self._ecb = AES.new(key, AES.MODE_ECB)
        self.ive = bytearray(iv)
        self.ivd = bytearray(iv)
        self.pe = 0
        self.pd = 0

    def enc(self, data):
        out = bytearray(len(data))
        ive, pe = self.ive, self.pe
        for i in range(len(data)):
            if pe == 0:
                ive = bytearray(self._ecb.encrypt(bytes(ive)))
                pe = 16
            p = 16 - pe
            ive[p] ^= data[i]
            out[i] = ive[p]
            pe -= 1
        self.ive, self.pe = ive, pe
        return bytes(out)

    def dec(self, data):
        out = bytearray(len(data))
        ivd, pd = self.ivd, self.pd
        for i in range(len(data)):
            if pd == 0:
                ivd = bytearray(self._ecb.encrypt(bytes(ivd)))
                pd = 16
            p = 16 - pd
            out[i] = ivd[p] ^ data[i]
            ivd[p] = data[i]
            pd -= 1
        self.ivd, self.pd = ivd, pd
        return bytes(out)


class TP42Panel(object):
    """Client per una centrale Tecnoalarm serie TP via IP.

    Args:
        host: IP della centrale.
        port: porta TCP (10001-10004).
        code: codice utente (PIN).
        passphrase: passphrase della porta; lascia vuoto se la porta non ne ha.
        appid: opzionale; se None usa il codice utente.
        n_programs, n_zones: quanti programmi/zone leggere (default 8 e 42).
        timeout: timeout socket in secondi.

    Mantiene una connessione persistente e riconnette da sola.
    Usare come context manager oppure chiamare close() a fine uso.
    """

    def __init__(self, host, port=10001, code="8383", passphrase="",
                 appid=None, n_programs=8, n_zones=42, n_telecommands=8,
                 timeout=8):
        self.host = host
        self.port = int(port)
        self.code = str(code)
        self.passphrase = passphrase or ""
        self.appid = appid
        self.n_programs = n_programs
        self.n_zones = n_zones
        self.n_telecommands = n_telecommands
        self.timeout = timeout
        self._s = None
        self._cip = None
        self.utn = 0

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *a):
        self.close()

    @property
    def connected(self):
        """True se la sessione TCP verso la centrale e' attualmente aperta."""
        return self._s is not None

    def _key(self):
        if self.passphrase and self.passphrase.strip():
            return self.passphrase.encode("latin-1")[:16].ljust(16, b"\x00")
        return DEFAULT_KEY

    def connect(self):
        """Apre la connessione e autentica (riprova se la centrale e' occupata)."""
        last = None
        for _ in range(5):
            try:
                self._do_connect()
                return
            except Exception as e:  # noqa
                last = e
                time.sleep(0.4)
        raise TP42Error("connessione/autenticazione fallita: %r" % last)

    def _do_connect(self):
        self._s = socket.socket()
        self._s.settimeout(self.timeout)
        self._s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._s.connect((self.host, self.port))
        iv = os.urandom(16)
        self._cip = _Cipher(self._key(), iv)
        time.sleep(0.15)
        self._s.sendall(iv)
        auth = bytearray(48)
        aid = _parse_appid(str(self.appid if self.appid is not None else self.code))
        auth[0] = aid & 0xFF
        auth[1] = (aid >> 8) & 0xFF
        for i, ch in enumerate(self.code):
            if i < 6 and ch.isdigit():
                auth[i + 2] = int(ch) & 0x0F
        auth[8] = 0x01
        d = self._raw(_REC_AUTH, 0, bytes(auth), 0)
        if not (d and len(d) >= 3 and d[0] == 0x06):
            raise TP42Error("autenticazione rifiutata")
        self.utn = d[1] | (d[2] << 8)

    def close(self):
        if self._s:
            try:
                self._s.close()
            except Exception:
                pass
        self._s = None

    def _read_frame(self):
        """Legge un frame completo. Il cifrario ha stato continuo: ogni byte
        ricevuto viene decifrato (mantenendo l'allineamento) e si estrae il
        primo frame DLE. Ritorna None su timeout; su chiusura TCP reale
        chiude il socket (la prossima richiesta riaprira')."""
        dec = b""
        t0 = time.time()
        while time.time() - t0 < self.timeout + 1:
            self._s.settimeout(self.timeout)
            try:
                c = self._s.recv(2048)
            except socket.timeout:
                return None
            if not c:
                self.close()
                return None
            dec += self._cip.dec(c)
            d = _dle_decode(dec)
            if len(d) >= 16 and d[0] == _DLE:
                dl = d[12] | (d[13] << 8)
                if len(d) >= 16 + dl:
                    return d[:16 + dl]
        return None

    def _raw(self, rec, idx, payload, utn):
        self._s.sendall(self._cip.enc(_dle_encode(_build(utn, rec, idx, payload))))
        d = self._read_frame()
        if not d or len(d) < 14 or d[0] != _DLE:
            return None
        dl = d[12] | (d[13] << 8)
        return d[14:14 + dl]

    def _reconnect(self):
        self.close()
        time.sleep(0.2)
        try:
            self._do_connect()
        except Exception:
            pass

    def _get(self, rec, idx=0, payload=b""):
        """Legge un record. Usa la sessione persistente; riapre solo se
        cade davvero (nessuna riconnessione proattiva)."""
        for _ in range(2):
            if self._s is None:
                self.connect()
            try:
                r = self._raw(rec, idx, payload, self.utn)
                if r is not None:
                    return r
            except Exception:
                pass
            self.close()
        return None

    @staticmethod
    def _name(d):
        return d.split(b"\x00")[0].decode("latin-1", "replace").strip() if d else ""

    def program_names(self):
        """Lista dei nomi dei programmi."""
        return [self._name(self._get(_REC_PNAME, i)) for i in range(self.n_programs)]

    def zone_names(self):
        """Lista dei nomi delle zone."""
        return [self._name(self._get(_REC_ZNAME, i)) for i in range(self.n_zones)]

    def get_programs(self, names=None):
        """Lista di Program con stato inserito/disinserito.

        `names`: nomi gia' letti (per non rileggerli ogni volta).
        """
        if names is None:
            names = self.program_names()
        gru = self._get(_REC_GRU) or b""
        pb = gru[4:] if len(gru) > 4 else b""
        return [Program(i + 1, names[i] if i < len(names) else "",
                        pb[i] if i < len(pb) else 0)
                for i in range(self.n_programs)]

    def get_zones(self, names=None):
        """Lista di Zone con stato aperta/chiusa/esclusa.

        `names`: nomi gia' letti (per non rileggerli ogni volta).
        """
        if names is None:
            names = self.zone_names()
        out = []
        for i in range(self.n_zones):
            zs = self._get(_REC_STATZON, i) or b"\x00\x00\x00\x00"
            out.append(Zone(i + 1, names[i] if i < len(names) else "", zs))
        return out

    def isolate_zone(self, zone):
        """Esclude (isola) la zona indicata (1-based). True se ACK.

        Record 0x0910 con indice = zona-1. Vale per TP e serie EV.
        """
        r = self._get(_REC_ZISOLA, int(zone) - 1)
        return r is not None and len(r) > 0 and r[0] == 0x06

    def reintegrate_zone(self, zone):
        """Reintegra (include) la zona indicata (1-based). True se ACK.

        Record 0x0911 con indice = zona-1.
        """
        r = self._get(_REC_ZREINT, int(zone) - 1)
        return r is not None and len(r) > 0 and r[0] == 0x06

    def program_states(self):
        """Solo gli stati dei programmi (veloce, senza nomi)."""
        gru = self._get(_REC_GRU) or b""
        pb = gru[4:] if len(gru) > 4 else b""
        return [Program(i + 1, "", pb[i] if i < len(pb) else 0)
                for i in range(self.n_programs)]

    def get_status(self):
        """Stati generali della centrale (allarme, sirene, guasti, GSM...).

        Restituisce un PanelStatus.
        """
        return PanelStatus(self._get(_REC_STATUS) or b"")

    def in_alarm(self):
        """True se la centrale e' in allarme (sirena in funzione)."""
        return self.get_status().in_alarm

    def _read_direct(self):
        """Legge un frame del protocollo diretto: 10 0c | cmd | flags |
        datalen | dati | crc (header 8 byte)."""
        dec = b""
        t0 = time.time()
        while time.time() - t0 < self.timeout + 1:
            self._s.settimeout(self.timeout)
            try:
                c = self._s.recv(2048)
            except socket.timeout:
                return None
            if not c:
                self.close()
                return None
            dec += self._cip.dec(c)
            d = _dle_decode(dec)
            if len(d) >= 8 and d[0] == _DLE:
                dl = d[6] | (d[7] << 8)
                if len(d) >= 8 + dl + 2:
                    return d[8:8 + dl]
        return None

    def _direct(self, cmd, data=b""):
        """Invia un comando del protocollo diretto sulla sessione persistente
        e restituisce il campo dati della risposta (o None)."""
        body = (bytes([cmd & 0xFF, (cmd >> 8) & 0xFF, 0, 0,
                       len(data) & 0xFF, (len(data) >> 8) & 0xFF]) + data)
        crc = _crc16(body, 0, len(body))
        frame = b"\x10\x02" + body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
        for _ in range(2):
            if self._s is None:
                self.connect()
            try:
                self._s.sendall(self._cip.enc(_dle_encode(frame)))
                r = self._read_direct()
                if r is not None:
                    return r
            except Exception:
                pass
            self.close()
        return None

    def get_gsm(self):
        """Info GSM: operatore e modello/versione del modulo.

        Restituisce un dict {'operator', 'module', 'raw'} oppure None.
        (Il nome operatore viaggia solo sul protocollo diretto del Centro,
        leggibile su porta senza passphrase senza autenticazione.)
        """
        d = self._direct(_CMD_GSM_INFO)
        if not d or len(d) < 2:
            return None
        # dati: [tipo][len][operatore+versione fw]...[modello modulo]
        parts = re.findall(rb"[\x20-\x7e]{3,}", d)
        s = parts[0].decode("latin-1") if parts else ""
        m = re.match(r"([A-Za-z][A-Za-z ]*)(.*)", s)
        operator = m.group(1).strip() if m else s
        fw = m.group(2).strip() if m else ""
        module = parts[1].decode("latin-1") if len(parts) > 1 else ""
        return {"operator": operator, "fw": fw, "module": module,
                "raw": d.hex()}

    def telecommand_names(self):
        """Lista dei nomi delle uscite telecomando."""
        return [self._name(self._get(_REC_TNAME, i))
                for i in range(self.n_telecommands)]

    def get_telecommands(self, names=None):
        """Lista di Telecommand con stato attivo/spento.

        Lo stato e' la bitmask nei primi 4 byte del record programmi.
        `names`: nomi gia' letti (per non rileggerli ogni volta).
        """
        if names is None:
            names = self.telecommand_names()
        gru = self._get(_REC_GRU) or b""
        mask = 0
        if len(gru) >= 4:
            mask = gru[0] | (gru[1] << 8) | (gru[2] << 16) | (gru[3] << 24)
        return [Telecommand(i + 1, names[i] if i < len(names) else "",
                            bool(mask & (1 << i)))
                for i in range(self.n_telecommands)]

    def activate(self, telecommand):
        """Attiva l'uscita telecomando indicata (1-based)."""
        return self._oper(_OP_TELEC_ON, telecommand)

    def deactivate(self, telecommand):
        """Disattiva l'uscita telecomando indicata (1-based)."""
        return self._oper(_OP_TELEC_OFF, telecommand)

    def _oper(self, opcode, number):
        """Invia un comando MKOPER (programma o telecomando) sulla sessione
        persistente. Restituisce True se la centrale risponde ACK (0x06),
        False se NAK/occupata. Il cifrario a stato continuo mantiene la
        sessione allineata: nessuna riconnessione dopo il comando."""
        p = bytearray(60)
        p[0] = opcode
        p[1] = int(number) - 1
        p[4] = self.utn & 0xFF
        p[5] = (self.utn >> 8) & 0xFF
        p[6] = 0x0E
        p[7] = 0x20
        for _ in range(2):
            if self._s is None:
                self.connect()
            try:
                r = self._raw(_REC_MKOPER, 0, bytes(p), self.utn)
                if r is not None:
                    return len(r) > 0 and r[0] == 0x06
            except Exception:
                pass
            self.close()
        return False

    def arm(self, program):
        """Inserisce (arma) il programma indicato (1-based)."""
        return self._oper(_OP_INS, program)

    def disarm(self, program):
        """Disinserisce (disarma) il programma indicato (1-based)."""
        return self._oper(_OP_DIS, program)
