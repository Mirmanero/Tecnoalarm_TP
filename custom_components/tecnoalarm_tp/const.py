"""Costanti per l'integrazione Tecnoalarm TP (locale, protocollo diretto)."""

DOMAIN = "tecnoalarm_tp"

CONF_CODE = "code"
CONF_PASSPHRASE = "passphrase"
CONF_UPDATE_INTERVAL = "update_interval"

DEFAULT_PORT = 10001
DEFAULT_UPDATE_INTERVAL = 5

# La libreria non ha modo di chiedere alla centrale "quanti programmi/zone
# hai": si scansiona sempre un range massimo e si scartano gli slot non
# configurati (Zone.configured=False, nome programma vuoto). Attenzione:
# interrogare indici oltre il numero fisico di zone/programmi della centrale
# NON ritorna un NAK immediato, la centrale semplicemente non risponde, quindi
# ogni indice extra costa un timeout pieno (fino a ~18s, verificato sul campo).
# Per questo i limiti restano quelli di default della libreria (il modello
# TP42 supporta appunto fino a 42 zone e 8 programmi): non vanno alzati senza
# aver prima verificato che la centrale risponda subito agli indici extra.
PROBE_N_PROGRAMS = 8
PROBE_N_ZONES = 42
MIN_UPDATE_INTERVAL = 2
MAX_UPDATE_INTERVAL = 60

# Ogni quanti tick di update_interval viene rilettura anche lo stato delle
# zone (lettura piu' lenta, ~2s per 42 zone: non ha senso farla ad ogni tick).
ZONE_POLL_EVERY_N_TICKS = 4

# La batteria delle zone cambia lentissimamente: rileggerla ogni 20s (come le
# zone) e' inutile. Intervallo indipendente, in secondi (tempo reale, non
# tick, cosi' resta valido anche cambiando update_interval dalle opzioni).
BATTERY_POLL_INTERVAL_SECONDS = 3600

CONNECT_TIMEOUT = 8
