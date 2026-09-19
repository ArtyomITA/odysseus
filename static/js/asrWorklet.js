// static/js/asrWorklet.js
//
// Preleva il microfono e lo consegna a pezzi da 100 ms, gia' in interi a 16 bit.
//
// Sta in un file suo e non in una blob URL di proposito: la CSP dichiara
// `script-src 'self'`, e `addModule()` su una blob verrebbe rifiutato.
//
// Il contesto audio viene creato a 16 kHz dal chiamante, quindi qui non si
// ricampiona niente: ci pensa il browser, meglio e prima di quanto potremmo
// fare noi in JavaScript.

const CAMPIONI_PER_PEZZO = 1600; // 100 ms a 16 kHz

class RaccoglitoreMicrofono extends AudioWorkletProcessor {
    constructor() {
        super();
        this._buffer = new Float32Array(CAMPIONI_PER_PEZZO);
        this._riempiti = 0;
        this._attivo = true;
        this.port.onmessage = (e) => {
            if (e.data === 'stop') this._attivo = false;
        };
    }

    process(inputs) {
        if (!this._attivo) return false;

        const canale = inputs[0] && inputs[0][0];
        // Nessun input: il nodo e' collegato ma la traccia non produce ancora.
        // Restituire true tiene vivo il processore in attesa.
        if (!canale) return true;

        for (let i = 0; i < canale.length; i++) {
            this._buffer[this._riempiti++] = canale[i];
            if (this._riempiti === CAMPIONI_PER_PEZZO) {
                // Conversione a interi con segno a 16 bit, little endian: e'
                // quello che sherpa-onnx si aspetta, e dimezza il traffico
                // rispetto ai float.
                const pcm = new Int16Array(CAMPIONI_PER_PEZZO);
                for (let k = 0; k < CAMPIONI_PER_PEZZO; k++) {
                    const v = Math.max(-1, Math.min(1, this._buffer[k]));
                    pcm[k] = v < 0 ? v * 0x8000 : v * 0x7FFF;
                }
                this.port.postMessage(pcm.buffer, [pcm.buffer]);
                this._riempiti = 0;
            }
        }
        return true;
    }
}

registerProcessor('raccoglitore-microfono', RaccoglitoreMicrofono);
