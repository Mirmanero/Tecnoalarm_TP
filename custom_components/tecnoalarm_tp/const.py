"""Costanti per l'integrazione Tecnoalarm TP (locale, protocollo diretto)."""

DOMAIN = "tecnoalarm_tp"

CONF_CODE = "code"
CONF_PASSPHRASE = "passphrase"
CONF_N_PROGRAMS = "n_programs"
CONF_N_ZONES = "n_zones"
CONF_UPDATE_INTERVAL = "update_interval"

DEFAULT_PORT = 10001
DEFAULT_N_PROGRAMS = 8
DEFAULT_N_ZONES = 42
DEFAULT_UPDATE_INTERVAL = 5
MIN_UPDATE_INTERVAL = 2
MAX_UPDATE_INTERVAL = 60

# Ogni quanti tick di update_interval viene rilettura anche lo stato delle
# zone (lettura piu' lenta, ~2s per 42 zone: non ha senso farla ad ogni tick).
ZONE_POLL_EVERY_N_TICKS = 4

CONNECT_TIMEOUT = 8
