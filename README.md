# Tecnoalarm TP (integrazione locale per Home Assistant)

Integrazione Home Assistant per centrali Tecnoalarm serie TP (TP4/8/10/42),
100% locale via IP: nessun account, nessun cloud. Usa la libreria vendorizzata
`tecnoalarm_tp42` per parlare direttamente con la centrale.

## Cosa fa (v1)

- Uno **switch** per ogni programma configurato: `turn_on` arma, `turn_off` disarma.
- Un **binary_sensor** per ogni zona configurata: aperta/chiusa, con attributo `excluded`.

Non ancora incluso (estendibile in futuro senza toccare l'architettura):
telecomandi, stato generale centrale (allarme/manomissione/batteria/rete), GSM,
isolamento/reintegro zone da UI.

## Installazione

Copia la cartella `custom_components/tecnoalarm_tp` nella cartella
`custom_components` della tua installazione Home Assistant, riavvia, poi
aggiungi l'integrazione "Tecnoalarm TP" da Impostazioni → Dispositivi e servizi.

Parametri richiesti: IP della centrale, porta (10001-10004), codice utente
(PIN), passphrase della porta (lasciare vuota se non impostata).

## Dipendenze

`pycryptodome` (dichiarata in `manifest.json`, installata automaticamente da
Home Assistant).
