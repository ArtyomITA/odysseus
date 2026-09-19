"""Ponte fra Odysseus e ShadowBroker.

Il modello non parla mai direttamente con ShadowBroker. Fra i due c'e' questo
pacchetto, che esiste per tre motivi misurati:

  * **Contesto.** Il catalogo strumenti di ShadowBroker pesa 12.374 token (il
    25% del nostro contesto) e `get_telemetry` ne restituisce 2,4 milioni. Un
    collegamento diretto muore alla prima domanda.

  * **Verita'.** Il loro `/api/ai/news-near` ignora in silenzio il parametro del
    raggio se lo chiami `radius_km`, e `brief_area` mescola dati locali con i
    primi N mondiali non filtrati. Un modello collegato direttamente
    risponderebbe che c'e' stato un terremoto 5.1 vicino a Kyiv (era in
    Indonesia). Qui le distanze si ricontrollano sempre.

  * **Classifica.** ShadowBroker ha gia' calcolato cosa e' grave: `threat_level`
    (fusione pesata a 7 componenti), `correlations`, gli alert su 113 aerei
    tracciati, e GT Strategic Risk Analytics su 1.641 regioni. Far ridecidere
    al modello cosa conta sarebbe piu' lento, piu' caro e meno affidabile.

Da cui la divisione del lavoro:

    Python  raccoglie tutto, ordina, filtra, geolocalizza, deduplica
    modello riceve un briefing gia' deciso e lo racconta

Il modello non sceglie mai cosa e' importante. Lo riceve.
"""

from src.shadowbroker.client import ShadowBrokerClient, get_client
from src.shadowbroker.store import LayerStore, get_store

__all__ = ["ShadowBrokerClient", "get_client", "LayerStore", "get_store"]
