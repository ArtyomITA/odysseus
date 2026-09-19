// static/js/asrStreaming.js
//
// Microfono acceso, testo che arriva mentre parli, fine turno automatica.
//
// Sostituisce il giro precedente — registra tutto, carica il file, ffmpeg,
// trascrivi — che non produceva una parola finche' non premevi stop. Qui il
// testo comincia ad arrivare dopo circa un secondo di parlato, e il turno si
// chiude da solo dopo ~800 ms di silenzio.
//
// Uso:
//   const asr = new AsrStreaming({
//       onParziale: (testo) => { ... },        // mentre parla
//       onTurno:    (testo) => { ... },        // ha finito di parlare
//       onErrore:   (msg)  => { ... },
//   });
//   await asr.avvia();      // chiede il microfono e apre la connessione
//   asr.ferma();            // chiude tutto

const FREQUENZA = 16000;

export class AsrStreaming {
    constructor(opzioni = {}) {
        this.onParziale = opzioni.onParziale || (() => {});
        this.onTurno = opzioni.onTurno || (() => {});
        this.onErrore = opzioni.onErrore || (() => {});
        this.onStato = opzioni.onStato || (() => {});
        this.lingua = opzioni.lingua || 'it';

        this._ws = null;
        this._ctx = null;
        this._nodo = null;
        this._sorgente = null;
        this._stream = null;
        this._attivo = false;
        this._muto = false;
    }

    get attivo() { return this._attivo; }

    /**
     * Silenzia l'invio senza chiudere niente.
     *
     * Serve mentre l'assistente parla: senza cuffie il microfono risente le
     * casse e il riconoscitore trascriverebbe la voce dell'assistente come se
     * fosse la nostra. La cancellazione d'eco del browser non copre l'audio
     * riprodotto dalla pagina stessa, quindi questo interruttore resta
     * necessario finche' non c'e' il giro WebRTC anti-eco.
     */
    silenzia(valore) { this._muto = !!valore; }

    async avvia() {
        if (this._attivo) return;

        if (!window.isSecureContext) {
            this.onErrore('Il microfono richiede HTTPS o localhost.');
            return;
        }
        if (!navigator.mediaDevices?.getUserMedia) {
            this.onErrore('Microfono non supportato da questo browser.');
            return;
        }

        try {
            await this._apriConnessione();
            await this._apriMicrofono();
            this._attivo = true;
            this.onStato('in ascolto');
        } catch (e) {
            this.ferma();
            this.onErrore(e.message || String(e));
        }
    }

    _apriConnessione() {
        return new Promise((risolvi, rifiuta) => {
            const schema = location.protocol === 'https:' ? 'wss' : 'ws';
            const url = `${schema}://${location.host}/api/stt/stream?lingua=${encodeURIComponent(this.lingua)}`;
            const ws = new WebSocket(url);
            ws.binaryType = 'arraybuffer';

            const scadenza = setTimeout(() => {
                try { ws.close(); } catch (_) {}
                rifiuta(new Error('Il servizio di trascrizione non risponde.'));
            }, 8000);

            ws.onopen = () => { clearTimeout(scadenza); this._ws = ws; risolvi(); };
            ws.onerror = () => { clearTimeout(scadenza); rifiuta(new Error('Connessione alla trascrizione fallita.')); };
            ws.onclose = () => { if (this._attivo) this.ferma(); };
            ws.onmessage = (ev) => this._messaggio(ev);
        });
    }

    _messaggio(ev) {
        let dati;
        try { dati = JSON.parse(ev.data); } catch (_) { return; }

        if (dati.errore) { this.onErrore(dati.errore); return; }

        const testo = (dati.testo || '').trim();
        if (dati.fine_turno) {
            // Un turno vuoto capita: silenzio prolungato senza parlato. Non va
            // consegnato, altrimenti si manda una richiesta vuota al modello.
            if (testo) this.onTurno(testo);
        } else if (testo) {
            this.onParziale(testo);
        }
    }

    async _apriMicrofono() {
        // Il contesto si chiede direttamente a 16 kHz: il ricampionamento lo fa
        // il browser, che lo fa meglio e senza costarci un ciclo.
        this._ctx = new (window.AudioContext || window.webkitAudioContext)({
            sampleRate: FREQUENZA,
        });

        const vincoli = window.OdysseusAudioDevices?.micConstraints() || { audio: true };
        // La cancellazione d'eco non risolve il rientro dalle casse della
        // pagina, ma toglie comunque il rumore d'ambiente: tenerla accesa.
        if (vincoli.audio === true) vincoli.audio = {};
        Object.assign(vincoli.audio, {
            echoCancellation: true, noiseSuppression: true, autoGainControl: true,
        });

        this._stream = await navigator.mediaDevices.getUserMedia(vincoli);

        await this._ctx.audioWorklet.addModule('/static/js/asrWorklet.js');
        this._sorgente = this._ctx.createMediaStreamSource(this._stream);
        this._nodo = new AudioWorkletNode(this._ctx, 'raccoglitore-microfono');

        this._nodo.port.onmessage = (e) => {
            if (this._muto) return;
            if (this._ws && this._ws.readyState === WebSocket.OPEN) {
                this._ws.send(e.data);
            }
        };

        this._sorgente.connect(this._nodo);
        // Il nodo non produce uscita, ma senza una destinazione alcuni browser
        // non fanno girare il grafo. Un guadagno a zero lo tiene vivo in
        // silenzio, senza rimandare il microfono nelle casse.
        const silenziatore = this._ctx.createGain();
        silenziatore.gain.value = 0;
        this._nodo.connect(silenziatore).connect(this._ctx.destination);
    }

    /** Chiude il turno adesso invece di aspettare il silenzio. */
    concludi() {
        if (this._ws && this._ws.readyState === WebSocket.OPEN) {
            this._ws.send('fine');
        }
    }

    ferma() {
        this._attivo = false;
        try { this._nodo?.port.postMessage('stop'); } catch (_) {}
        try { this._nodo?.disconnect(); } catch (_) {}
        try { this._sorgente?.disconnect(); } catch (_) {}
        try { this._stream?.getTracks().forEach(t => t.stop()); } catch (_) {}
        try { this._ctx?.close(); } catch (_) {}
        try { this._ws?.close(); } catch (_) {}
        this._nodo = this._sorgente = this._stream = this._ctx = this._ws = null;
        this.onStato('spento');
    }
}

export default AsrStreaming;
