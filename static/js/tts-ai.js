// static/js/tts-ai.js
// AI Text-to-Speech Module — supports server TTS and browser Web Speech API

import { getSettings } from './appConfig.js';

class AITTSManager {
    // Below this, a fragment is not worth its own synthesis round-trip — it is
    // merged with the next sentence rather than spoken (or dropped) on its own.
    static MIN_SPEAK_CHARS = 15;
    // Beyond this the text no longer fits comfortably in a query string and
    // synthesis falls back to POST + Blob (slower to start, but never truncated).
    static MAX_STREAM_URL_CHARS = 1600;
    // Characters that must still follow a comma before it counts as a cut point.
    static SUBSENTENCE_LOOKAHEAD = 25;
    // PocketTTS salta parole oltre 50 token per pezzo. Misurato col suo stesso
    // tokenizer sentencepiece sull'italiano: 0,46 token per carattere, quindi
    // 50 token sono ~108 caratteri, non 180. Il vecchio 180 era il doppio del
    // limite vero e nel log di PocketTTS lasciava tre avvisi
    // "Chunk has N tokens (max 50)". Stesso numero del ponte (LIMITE_PEZZO).
    static MAX_SPEAK_CHARS = 105;
    // Il PRIMO pezzo di un turno ha regole piu' larghe: e' l'unico la cui
    // attesa l'utente sente come "silenzio dopo la risposta". Misurato: la
    // prima virgola utile arriva ~0,3 s prima della prima frase intera, e la
    // sintesi tiene (fattore tempo reale 0,56), quindi anticipare non crea
    // buchi piu' avanti. Dal secondo pezzo si torna alle soglie normali,
    // altrimenti la voce suona spezzettata per tutta la risposta.
    // Stessi numeri del ponte: LIMITE_PRIMO_PEZZO 60, MIN_PRIMO_PEZZO 12.
    static MAX_FIRST_SPEAK_CHARS = 60;
    static MIN_FIRST_SPEAK_CHARS = 12;
    // Congiunzioni prima delle quali si puo' respirare senza che il taglio si
    // senta. Stesso elenco di `_CONGIUNZIONE` in voce/ponte_voce.py. Si taglia
    // PRIMA della parola, e solo quando non c'e' punteggiatura utile entro il
    // tetto: tagliare a ogni "e" o "che" spezzetterebbe la voce.
    static CONGIUNZIONI = new Set([
        'e', 'ed', 'o', 'oppure', 'ma', "pero'", 'però', 'mentre', 'quindi',
        "percio'", 'perciò', "perche'", 'perché', 'poi', 'che', 'se', 'con',
        'per', 'anche', 'dove', 'quando', 'come',
    ]);
    // Estremi ragionevoli per la velocita' di lettura: sotto 0.5 la voce
    // strascica fino a diventare incomprensibile, sopra 2 e' un cinguettio.
    // Una impostazione scritta a mano (o da un agente) puo' contenere di tutto.
    static SPEED_MIN = 0.5;
    static SPEED_MAX = 2.0;
    // Nessun avanzamento per questo tempo, a scaricamento finito, vuol dire che
    // `ended` non e' arrivato: la coda riparte lo stesso invece di piantarsi.
    static STALLO_MS = 3000;

    constructor() {
        this.currentAudio = null;
        this.isPlaying = false;
        this.available = false;
        this.useBrowserTTS = false;
        this.browserVoice = '';
        this.playbackSpeed = 1;
        this._fermaBoccaBrowser = null;  // chiude la bocca della voce del browser
        this._provider = 'disabled';
        this.autoPlay = false;
        this.cache = new Map(); // Client-side audio cache

        // Queue for sequential auto-play
        this._queue = [];       // Array of { text, button, resetFn }
        this._processing = false;

        // Streaming sentence-by-sentence TTS state
        this._streamSentencesSent = 0;  // chars of plain text already queued
        this._streamActive = false;
        this._streamButton = null;
        this._streamResetFn = null;
        this._streamDebounceTimer = null;

        // Check if TTS service is available
        this.checkAvailability();
    }

    async checkAvailability() {
        try {
            // Check user setting first — if TTS is disabled in settings, don't show buttons.
            // settings.js re-calls this right after saving TTS settings; it invalidates
            // the shared cache before doing so, so this still sees the new value.
            try {
                const settings = await getSettings();
                if (settings.tts_enabled === false) {
                    this.available = false;
                    this._provider = 'disabled';
                    return;
                }
            } catch {}

            const response = await fetch('/api/tts/stats');
            const stats = await response.json();
            this.available = stats.available && stats.ready;
            this.playbackSpeed = stats.speed || 1;
            this._provider = stats.provider || 'disabled';

            if (stats.provider === 'browser') {
                this.useBrowserTTS = true;
                this.browserVoice = stats.voice || '';
                this.available = 'speechSynthesis' in window;
                if (!this.available) {
                    console.warn('TTS: browser mode selected but speechSynthesis not supported');
                }
            } else if (this.available) {
                this.useBrowserTTS = false;
            } else {
                console.warn('TTS: not available');
            }
        } catch (error) {
            console.error('Failed to check TTS availability:', error);
            this.available = false;
        }
    }

    extractPlainText(content) {
        // Strip <think>/<thinking> blocks (model reasoning). The opening tag may
        // carry attributes (`<think time="2.4">`), and while streaming the block
        // is still open — strip that too, or the reasoning gets read aloud and
        // the plain text later *shrinks* when the closing tag lands, which stalls
        // the streaming offset for the rest of the turn.
        let cleaned = content
            .replace(/<think(?:ing)?\b[^>]*>[\s\S]*?<\/think(?:ing)?>/gi, '')
            .replace(/<think(?:ing)?\b[^>]*>[\s\S]*$/i, '');

        // Create a temporary div to parse HTML/markdown
        const temp = document.createElement('div');
        temp.innerHTML = cleaned;

        // Remove code blocks
        temp.querySelectorAll('pre, code').forEach(el => el.remove());

        // Get text content
        let text = temp.textContent || temp.innerText || '';

        // Clean up markdown syntax
        text = text
            .replace(/#{1,6}\s/g, '') // Remove headers
            .replace(/\*\*(.+?)\*\*/g, '$1') // Remove bold
            .replace(/\*(.+?)\*/g, '$1') // Remove italic
            .replace(/\[(.+?)\]\(.+?\)/g, '$1') // Remove links
            .replace(/`(.+?)`/g, '$1') // Remove inline code
            .replace(/\n{3,}/g, '\n\n') // Normalize line breaks
            .trim();

        return text;
    }

    /**
     * Last pass before the text reaches the synthesizer.
     *
     * Deliberately NOT part of extractPlainText(): the streaming offset counter
     * indexes into that string, and any filter applied there can make the text
     * *shrink* mid-stream. A parenthesis that is still unclosed when the chunk
     * boundary falls ("...la mappa (vedi") survives one update and disappears on
     * the next, which drifts the offset and re-reads or drops a sentence — the
     * exact failure mode already hit with <think> blocks.
     *
     * Applied here instead, the offsets are computed on untouched text and only
     * what is actually spoken gets cleaned. Cost: a handful of regexes over
     * ~100 characters, microseconds, against a synthesis that takes seconds.
     *
     * Brackets: the characters go, the content stays. A parenthetical read
     * inline still makes sense; deleting it loses meaning.
     */
    static forSpeech(text) {
        if (!text) return '';
        return text
            // Emoji and pictographs. Emoji_Component is deliberately absent from
            // this class: it contains the digits 0-9 and '#', which would strip
            // every number out of the reply.
            .replace(/[\p{Extended_Pictographic}\p{Emoji_Modifier}\p{Regional_Indicator}]/gu, '')
            .replace(/[︀-️‍⃣]/g, '')  // variation selectors, ZWJ, keycap
            // Tag fra quadre: `[joy]`, `[emotion:happy]`, `[1]`. Vanno tolti
            // CONTENUTO COMPRESO, e prima della regola sotto che trasforma le
            // parentesi in spazi: quella lascia la parola, quindi l'assistente
            // diceva "joy" all'inizio di ogni risposta. Solo etichette corte e
            // senza spazi interni, cosi' un inciso vero fra quadre resta detto.
            .replace(/\[\s*(?:[a-z][a-z0-9_.\-]{0,20}|[A-Z][A-Z0-9_.\-]{0,20})(?:\s*[:=]\s*[A-Za-z0-9_.\- ]{0,20})?\s*\]/g, ' ')
            // Brackets of every kind, content kept
            .replace(/[()\[\]{}<>«»„“”"']/g, ' ')
            // Leftover markdown and table furniture
            .replace(/^[ \t]*[-*+•]\s+/gm, '')
            .replace(/[|_*~`#^]/g, ' ')
            // Arrows and bullets read as noise
            .replace(/[→←↔⇒⇐➜►▶▪●·]/g, ' ')
            // A space before punctuation is what the substitutions above leave behind
            .replace(/[ \t]+([,.;:!?])/g, '$1')
            .replace(/[ \t]{2,}/g, ' ')
            // The substitutions leave spaces hugging the line breaks, and a
            // stray space before a newline turns into an audible stumble.
            .replace(/[ \t]*\n[ \t]*/g, '\n')
            .replace(/\n{3,}/g, '\n\n')
            .trim();
    }

    /**
     * URL the <audio> element can play while it downloads.
     *
     * GET and not POST because an <audio> element can only be pointed at a URL;
     * anything fetched by hand ends up in a Blob, and a Blob is complete by
     * definition — which reintroduces the wait this removes. Very long text
     * would not fit in a URL, so synthesize() falls back to the POST path there.
     */
    _streamUrl(plainText) {
        return '/api/tts/stream?text=' + encodeURIComponent(plainText);
    }

    getCacheKey(text) {
        // Simple hash function for cache key
        let hash = 0;
        for (let i = 0; i < text.length; i++) {
            const char = text.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash;
        }
        return hash.toString(36);
    }

    async synthesize(text, onProgress = null) {
        if (!this.available) {
            throw new Error('AI TTS service not available');
        }

        // forSpeech() last: emoji and brackets must not reach the synthesizer,
        // but must not disturb the streaming offsets either. See its comment.
        const plainText = AITTSManager.forSpeech(this.extractPlainText(text));

        if (!plainText) {
            // A chunk that was nothing but emoji or punctuation. The queue
            // catches this and moves on to the next item.
            throw new Error('No text to synthesize');
        }

        // Browser TTS doesn't use synthesize — handled directly in play()
        if (this.useBrowserTTS) {
            return '__browser_tts__';
        }

        // Progressive path: hand back a URL and let <audio> pull it. The
        // element starts playing on the first frames instead of waiting for the
        // last byte, which is what a Blob forces. No fetch happens here at all —
        // the request begins when something loads the URL, and _prefetch() is
        // what makes that happen early enough to overlap the previous sentence.
        if (plainText.length <= AITTSManager.MAX_STREAM_URL_CHARS) {
            return this._streamUrl(plainText);
        }

        const cacheKey = this.getCacheKey(plainText);

        // Check cache first
        if (this.cache.has(cacheKey)) {
            return this.cache.get(cacheKey);
        }

        try {
            if (onProgress) onProgress('synthesizing');

            const response = await fetch('/api/tts/synthesize', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    text: plainText,
                    format: 'audio'
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail?.message || 'Synthesis failed');
            }

            const audioBlob = await response.blob();
            const audioUrl = URL.createObjectURL(audioBlob);

            // Cache the result
            this.cache.set(cacheKey, audioUrl);

            if (onProgress) onProgress('complete');

            return audioUrl;

        } catch (error) {
            if (onProgress) onProgress('error');
            throw error;
        }
    }

    /**
     * Velocita' di lettura chiesta dall'utente, ridotta a un numero sensato.
     *
     * Viene da /api/tts/stats, cioe' dalla stessa `tts_speed` che il pannello
     * impostazioni scrive. Il ponte la accetta e la butta via: PocketTTS non ha
     * nessun parametro di velocita'. L'unico posto dove l'impostazione puo'
     * avere effetto e' qui, sull'elemento che suona.
     */
    _velocita() {
        var v = Number(this.playbackSpeed);
        if (!isFinite(v) || v <= 0) return 1;
        return Math.min(AITTSManager.SPEED_MAX, Math.max(AITTSManager.SPEED_MIN, v));
    }

    /**
     * Applica la velocita' a un elemento audio, qualunque sia il fornitore.
     *
     * Prima lo faceva solo il percorso `local`, quindi con PocketTTS
     * l'impostazione non faceva assolutamente niente. `preservesPitch` tiene il
     * timbro della voce mentre cambia la durata: senza, a 1.5x si sente Paperino.
     * I due nomi con prefisso servono ai motori vecchi, che ignorano l'altro.
     */
    _applicaVelocita(audio) {
        var v = this._velocita();
        try {
            audio.preservesPitch = true;
            audio.webkitPreservesPitch = true;
            audio.mozPreservesPitch = true;
        } catch (_) { /* proprieta' assente: pazienza, cambia il timbro */ }
        if (v !== 1) audio.playbackRate = v;
    }

    _findBrowserVoice() {
        if (!this.browserVoice) return null;
        const voices = window.speechSynthesis.getVoices();
        const target = this.browserVoice.toLowerCase();
        // Try exact match first, then partial
        return voices.find(v => v.name.toLowerCase() === target) ||
               voices.find(v => v.name.toLowerCase().includes(target)) ||
               null;
    }

    async play(text) {
        // Stop current audio if playing
        this.stop();

        const plainText = this.extractPlainText(text);
        if (!plainText) return;

        if (this.useBrowserTTS) {
            return this._playBrowser(plainText);
        }

        try {
            const audioUrl = await this.synthesize(text);

            this.currentAudio = new Audio(audioUrl);
            this._applicaVelocita(this.currentAudio);
            window.OdysseusAudioDevices?.applyOutputDevice(this.currentAudio);
            // L'avatar e' un di piu': se inciampa non deve portarsi dietro la
            // voce. Un errore qui dentro faceva fallire tutta la riproduzione.
            try { window.OdysseusAvatar?.attachAudio(this.currentAudio); }
            catch (e) { console.warn('avatar: aggancio fallito', e); }
            await this.currentAudio.play();
            this.isPlaying = true;
            // Note: onended should be set by the caller (addAITTSButton)
            // to reset button state when audio finishes

        } catch (error) {
            console.error('Failed to play audio:', error);
            throw error;
        }
    }

    /**
     * Bocca dell'avatar mentre parla la voce del browser (percorso B).
     *
     * Con `speechSynthesis` non esiste nessun elemento <audio> e nessun nodo
     * Web Audio da intercettare: l'audio lo suona il sistema operativo e la
     * pagina non lo vede. Quindi l'ampiezza non si misura, si inventa — ma
     * inventata sul ritmo vero delle parole, non a caso: ogni evento `boundary`
     * e' l'inizio di una parola, quindi un colpo di apertura che poi si
     * richiude da solo.
     *
     * Ci sono motori (Chrome con voci remote) che `boundary` non lo emettono
     * mai: dopo mezzo secondo di silenzio si passa a un andamento a tempo, ~4
     * sillabe al secondo, che e' sempre meglio di una bocca ferma.
     *
     * Restituisce la funzione da chiamare per smettere.
     */
    _boccaBrowser(utterance) {
        var avatar = window.OdysseusAvatar;
        if (!avatar || typeof avatar.pushLivello !== 'function') return function() {};

        var vivo = true;
        var livello = 0;
        var parole = 0;
        var t0 = performance.now();

        var spingi = function(v) {
            try { avatar.pushLivello(Math.max(0, Math.min(1, v))); } catch (_) {}
        };

        var passo = function() {
            // La condizione d'uscita vera e' questa, non solo `vivo`: se
            // l'enunciato viene annullato, `end` puo' non arrivare mai e il
            // ciclo resterebbe acceso per sempre a spingere zeri.
            if (!vivo || !window.speechSynthesis.speaking) {
                vivo = false;
                spingi(0);
                return;
            }
            var ora = performance.now();
            if (parole === 0 && ora - t0 > 500) {
                livello = 0.30 + 0.35 * Math.abs(Math.sin(ora / 120));
            } else {
                livello *= 0.86;   // rilascio: la parola si spegne in ~200 ms
            }
            spingi(livello);
            requestAnimationFrame(passo);
        };

        try {
            utterance.addEventListener('boundary', function() {
                parole++;
                livello = 0.85;
            });
        } catch (_) { /* motore senza boundary: resta l'andamento a tempo */ }

        requestAnimationFrame(passo);
        return function() { vivo = false; spingi(0); };
    }

    _playBrowser(plainText) {
        return new Promise((resolve, reject) => {
            const utterance = new SpeechSynthesisUtterance(plainText);
            const voice = this._findBrowserVoice();
            if (voice) utterance.voice = voice;
            utterance.rate = this._velocita();

            // Fuori dalla coda (play() diretta) gli eventi non li segnala
            // nessuno: il microfono resterebbe aperto mentre l'assistente
            // parla. Dentro la coda ci pensa gia' _processQueue.
            var segnala = !this._processing;
            var fermaBocca = null;
            const chiudi = () => {
                if (fermaBocca) { fermaBocca(); fermaBocca = null; }
                this._fermaBoccaBrowser = null;
                this.isPlaying = false;
                if (segnala) { segnala = false; this._segnala('tts-end'); }
            };

            utterance.onstart = () => {
                fermaBocca = this._boccaBrowser(utterance);
                this._fermaBoccaBrowser = fermaBocca;
            };
            utterance.onend = () => {
                chiudi();
                resolve();
            };
            utterance.onerror = (e) => {
                chiudi();
                reject(new Error('Browser TTS error: ' + e.error));
            };
            utterance.onpause = () => {
                if (fermaBocca) { fermaBocca(); fermaBocca = null; }
            };
            utterance.onresume = () => {
                if (!fermaBocca) fermaBocca = this._boccaBrowser(utterance);
            };

            if (segnala) this._segnala('tts-start');
            window.speechSynthesis.speak(utterance);
            this.isPlaying = true;
        });
    }

    stop() {
        // Cancel streaming TTS
        this._streamActive = false;
        if (this._streamDebounceTimer) {
            clearTimeout(this._streamDebounceTimer);
            this._streamDebounceTimer = null;
        }
        this._streamSentencesSent = 0;

        // Clear the entire queue and reset all queued buttons
        for (const item of this._queue) {
            if (item.resetFn) item.resetFn();
            // A prefetched element is mid-download and would keep the
            // synthesiser busy on a sentence nobody will hear. Emptying src
            // aborts the request.
            if (item._audio) {
                try { item._audio.src = ''; item._audio.load(); } catch (_) {}
                item._audio = null;
            }
        }
        const stavaParlando = this._processing;
        this._queue = [];
        this._processing = false;
        if (stavaParlando) this._segnala('tts-end');

        if (this.useBrowserTTS) {
            window.speechSynthesis.cancel();
            // `cancel()` non garantisce l'evento `end`: la bocca va chiusa a mano.
            if (this._fermaBoccaBrowser) {
                try { this._fermaBoccaBrowser(); } catch (_) {}
                this._fermaBoccaBrowser = null;
            }
            this.isPlaying = false;
        }
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio.currentTime = 0;
            this.currentAudio = null;
            this.isPlaying = false;
        }
    }

    /**
     * Enqueue a message for auto-play. Plays sequentially — each message
     * finishes before the next starts. Stopping any message clears the queue.
     */
    enqueue(text, button, resetFn) {
        // Mai in coda un pezzo che non ha nulla da dire: dopo forSpeech() un
        // pezzo fatto solo di simboli, emoji o barre di tabella resta vuoto e
        // synthesize() lo respingeva con "No text to synthesize", rompendo la
        // coda a meta' messaggio.
        if (!AITTSManager.forSpeech(this.extractPlainText(text || ''))) return;
        this._queue.push({ text, button, resetFn });
        if (!this._processing) {
            this._processQueue();
        } else if (this._queue.length === 2) {
            // Something is already playing and this is the next in line:
            // start synthesising it now instead of at hand-over.
            this._prefetch(this._queue[1]);
        }
    }

    /**
     * Mette in coda un testo intero, tagliato come quello che arriva in diretta.
     *
     * E' quello che usa il pulsante "leggi ad alta voce". Prima gli passava il
     * messaggio intero a `enqueue()`: PocketTTS taglia a 50 token per pezzo e
     * oltre quella soglia SALTA le parole senza dirlo, quindi di un messaggio
     * lungo si sentiva solo l'inizio. Stesso tagliatore e stessa coda della
     * lettura automatica: un pezzo che parte prima e nessuna parola persa.
     */
    enqueueSpezzato(text, button, resetFn) {
        var plainText = this.extractPlainText(text);
        if (!plainText) return;

        // Lo spazio in fondo serve al tagliatore: taglia solo quando dopo la
        // punteggiatura c'e' uno spazio, e l'ultima frase non ne ha.
        var conSpazio = plainText.trim() + ' ';
        var pezzi = this._spezza(conSpazio);
        var consumati = pezzi.join('').length;
        var coda = conSpazio.substring(consumati).trim();

        this._accodaConTetto(pezzi, coda, button, resetFn);
    }

    /**
     * Riunisce i pezzi corti e accoda, senza mai superare il tetto.
     *
     * Due percorsi finivano alla sintesi senza controllo: la riunione dei
     * pezzi corti (che sommava fino a superare il tetto) e la `coda`, cioe'
     * l'avanzo dopo l'ultimo taglio di `_spezza`, che non era ripassato da
     * nessuna parte. Entrambi finiscono qui.
     */
    _accodaConTetto(pezzi, coda, button, resetFn) {
        var MAX = AITTSManager.MAX_SPEAK_CHARS;
        var accumulato = '';
        var scarica = (testo) => {
            var pulito = String(testo || '').trim();
            if (!pulito) return;
            var fuori = AITTSManager._sottoTetto(pulito);
            for (var n = 0; n < fuori.length; n++) this.enqueue(fuori[n], button, resetFn);
        };
        for (var k = 0; k < pezzi.length; k++) {
            // La riunione si ferma al tetto: meglio un pezzo un po' corto che
            // uno che PocketTTS ritaglia da solo saltando parole.
            if (accumulato && (accumulato + pezzi[k]).trim().length > MAX) {
                scarica(accumulato);
                accumulato = '';
            }
            accumulato += pezzi[k];
            if (accumulato.trim().length < AITTSManager.MIN_SPEAK_CHARS) continue;
            scarica(accumulato);
            accumulato = '';
        }
        scarica(accumulato + ' ' + (coda || ''));
    }

    /**
     * Start synthesising an item without playing it, so the audio is ready the
     * moment the previous one ends.
     *
     * This is what removes the 3-4 second gap between sentences. The queue was
     * already serial, but each item did synthesise-then-play: PocketTTS needs
     * ~2 s for a short sentence and ~8 s for a paragraph, and that wait landed
     * in silence between every pair of sentences.
     *
     * Making the blocks bigger would also reduce the gaps, but it delays the
     * FIRST word by the same amount. Prefetching costs nothing in latency: the
     * synthesis of block N+1 overlaps the playback of block N.
     */
    _prefetch(item) {
        if (!item || item._prefetched || this.useBrowserTTS) return;
        item._prefetched = true;
        // With the progressive path, synthesize() only builds a URL — it starts
        // no work. The request has to be kicked off by an element, so one is
        // created here and told to buffer. That element is then handed to
        // _playQueueItem(), so the sentence is never synthesised twice.
        // Failures are ignored on purpose — playback retries and reports.
        try {
            const p = this.synthesize(item.text);
            Promise.resolve(p).then((url) => {
                if (!url || url === '__browser_tts__') return;
                if (url.startsWith('/api/tts/stream')) {
                    const audio = new Audio();
                    audio.preload = 'auto';
                    audio.src = url;
                    audio.load();
                    item._audio = audio;
                }
            }).catch(() => {});
        } catch (_) { /* rete assente: si riprova alla riproduzione */ }
    }

    /**
     * Announces that the assistant is speaking, or has stopped.
     *
     * Emitted around the WHOLE queue, not per sentence. Per-sentence events
     * would unmute the microphone in every gap between sentences, which is
     * exactly when the speakers are still ringing and the live transcriber
     * would catch the assistant's own tail.
     */
    _segnala(nome) {
        try {
            window.dispatchEvent(new CustomEvent('odysseus:' + nome));
        } catch (_) { /* ambiente senza window: niente da segnalare */ }
    }

    async _processQueue() {
        if (this._processing) return;
        this._processing = true;
        this._segnala('tts-start');

        // Pulsanti toccati durante questa coda: si rimettono a ▶ tutti insieme
        // alla fine, non pezzo per pezzo.
        const daRipristinare = new Set();
        const ripristina = () => {
            for (const fn of daRipristinare) {
                try { fn(); } catch (_) {}
            }
            daRipristinare.clear();
        };

        while (this._queue.length > 0) {
            const item = this._queue[0];
            if (item.resetFn) daRipristinare.add(item.resetFn);
            // Warm the NEXT item while this one plays.
            this._prefetch(this._queue[1]);
            try {
                await this._playQueueItem(item);
            } catch (err) {
                console.error('TTS queue item error:', err);
            }
            if (this._queue.length > 0 && this._queue[0] === item) {
                this._queue.shift();
            }
            if (!this._processing) {
                // stop() got there first and already signalled the end.
                ripristina();
                return;
            }
            // A sentence may have been appended while this one was playing.
            this._prefetch(this._queue[0]);
        }
        this._segnala('tts-end');

        this._processing = false;
        ripristina();
    }

    async _playQueueItem(item) {
        const { text, button } = item;
        const ICON_LOADING = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="9" stroke-dasharray="42" stroke-dashoffset="12" stroke-linecap="round"><animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="0.8s" repeatCount="indefinite"/></circle></svg>';
        var ICON_STOP = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>';

        button.innerHTML = ICON_LOADING;
        button.classList.add('loading');
        button.style.color = '#ccc';
        button.title = 'Ferma la lettura';

        try {
            if (!this._processing) return;

            const audioUrl = await this.synthesize(text);

            if (!this._processing) return;

            button.innerHTML = ICON_STOP;
            button.classList.remove('loading');
            button.classList.add('playing');
            button.title = 'Ferma la lettura';

            if (this.useBrowserTTS) {
                const plainText = this.extractPlainText(text);
                await this._playBrowser(plainText);
            } else {
                if (this.currentAudio) {
                    this.currentAudio.pause();
                    this.currentAudio = null;
                }

                await new Promise((resolve, reject) => {
                    // The element _prefetch() already started buffering, if any.
                    // Reusing it is the whole point: creating a fresh one here
                    // would ask the server to synthesise the same sentence twice
                    // and throw away the head start.
                    const audio = item._audio || new Audio(audioUrl);
                    item._audio = null;
                    // Vale per tutti i fornitori, non solo per `local`:
                    // l'analizzatore dell'avatar legge il grafo Web Audio a
                    // valle dell'elemento, quindi continua a ricevere campioni
                    // anche a velocita' diversa da 1.
                    this._applicaVelocita(audio);
                    this.currentAudio = audio;
                    // Queued playback is the path the read-aloud button and
                    // auto-speak use, so the avatar has to be tapped here too.
                    window.OdysseusAudioDevices?.applyOutputDevice(audio);
                    // Dentro la Promise: un'eccezione dell'avatar qui faceva
                    // saltare la riproduzione insieme alla bocca. L'avatar e'
                    // accessorio, la voce no.
                    try { window.OdysseusAvatar?.attachAudio(audio); }
                    catch (e) { console.warn('avatar: aggancio fallito', e); }
                    // Guardia contro l'`ended` che non arriva.
                    //
                    // Il WAV che arriva dal ponte non ha una lunghezza vera
                    // (e' un flusso: le dimensioni valgono 0xFFFFFFFF), quindi
                    // `duration` non dice niente e ci sono lettori che, a
                    // scaricamento finito, restano fermi senza emettere
                    // `ended`. Prima bastava per piantare la coda per il resto
                    // della risposta: la voce "a volte non parte".
                    //
                    // Il controllo scatta solo quando il download e' FINITO
                    // (networkState IDLE) e il tempo di riproduzione non
                    // avanza: durante la sintesi una pausa e' normale e non
                    // deve troncare la frase.
                    var chiuso = false;
                    var vigile = null;
                    // Quando l'audio suona davvero il lettore emette `timeupdate`
                    // ~4 volte al secondo, anche a scheda nascosta. E' la prova
                    // che NON e' piantato, e vale molto piu' del confronto fra
                    // due letture di `currentTime`: con la scheda in secondo
                    // piano il browser rallenta i timer, le due letture cadono
                    // troppo lontane e il tempo sembrava fermo a torto.
                    var ultimoAvanzamento = Date.now();
                    const avanza = () => { ultimoAvanzamento = Date.now(); };
                    audio.addEventListener('timeupdate', avanza);
                    const concludi = (fn, arg) => {
                        if (chiuso) return;
                        chiuso = true;
                        if (vigile) clearInterval(vigile);
                        audio.removeEventListener('timeupdate', avanza);
                        // Un solo audio alla volta per costruzione: chi esce di
                        // scena viene fermato e sganciato PRIMA che parta il
                        // pezzo seguente. Senza questo, il vigile dello stallo
                        // faceva partire il pezzo dopo sopra quello in corso e
                        // le voci si accavallavano.
                        try { audio.pause(); } catch (_) {}
                        try { audio.onended = audio.onerror = audio.onpause = null; } catch (_) {}
                        this.isPlaying = false;
                        if (this.currentAudio === audio) this.currentAudio = null;
                        fn(arg);
                    };
                    vigile = setInterval(() => {
                        if (audio.ended) { concludi(resolve); return; }
                        // Scheda nascosta o occlusa: i timer non sono attendibili,
                        // il vigile resta zitto e riparte da zero al ritorno.
                        if (typeof document !== 'undefined' && document.hidden) {
                            ultimoAvanzamento = Date.now();
                            return;
                        }
                        if (audio.paused || audio.networkState !== 2) {
                            ultimoAvanzamento = Date.now();
                            return;
                        }
                        if (Date.now() - ultimoAvanzamento >= AITTSManager.STALLO_MS) {
                            console.warn('TTS: nessun `ended`, passo al pezzo seguente');
                            concludi(resolve);
                        }
                    }, 500);
                    audio.onended = () => concludi(resolve);
                    audio.onerror = () => concludi(reject, new Error('Audio playback error'));
                    audio.onpause = () => {
                        if (this.currentAudio !== audio) concludi(resolve);
                    };
                    audio.play().then(() => {
                        this.isPlaying = true;
                    }).catch(reject);
                });
            }
        } catch (err) {
            // Rilanciato: chi registra l'errore e' _processQueue().
            throw err;
        }
        // Niente ripristino del pulsante qui: la coda e' fatta di molti pezzi
        // dello stesso messaggio, e rimettere l'icona ▶ alla fine di ognuno
        // faceva lampeggiare il tasto e lasciava l'utente senza un comando per
        // fermare. Il ripristino lo fa _processQueue() a coda finita (e stop()).
    }

    // ── Streaming TTS (sentence-by-sentence) ──

    streamingStart() {
        this._streamSentencesSent = 0;
        this._streamActive = true;
        this._streamButton = null;
        this._streamResetFn = null;
    }

    streamingUpdate(accumulatedText) {
        if (!this._streamActive || !this.available || !this.autoPlay) return;
        if (this._streamDebounceTimer) return;
        this._streamDebounceTimer = setTimeout(() => {
            this._streamDebounceTimer = null;
            this._processStreamingSentences(accumulatedText);
        }, 150);
    }

    /**
     * Cuts a region of text into speakable pieces.
     *
     * Three cuts, in order of preference:
     *
     * 1. End of sentence — as before, minus the two traps: "1." in a numbered
     *    list and an initial like "A." are not sentence ends.
     *
     * 2. Comma, semicolon or colon, but only when at least SUBSENTENCE_LOOKAHEAD
     *    characters follow. The look-ahead is what keeps it from sounding
     *    chopped: a comma near the end of what has arrived so far might really
     *    be the end of the thought, and cutting there leaves a stub hanging.
     *    Waiting for proof that the sentence continues costs nothing — the next
     *    streaming update brings it. This is what starts the audio mid-sentence
     *    instead of after it.
     *
     * 3. Hard cap. PocketTTS logs "Chunk has 182 tokens (max 50), generation may
     *    skip words" and then silently drops words. Anything over
     *    MAX_SPEAK_CHARS is cut at the next space whether the grammar likes it
     *    or not — a slightly early breath beats a missing clause.
     *
     * The count of characters consumed is what the caller adds to its offset, so
     * every branch must push the text it consumed, whitespace included.
     */
    /**
     * Ultimo spazio prima di una congiunzione, oltre `minimo`. -1 se non c'e'.
     *
     * Il taglio cade PRIMA della parola (lo spazio resta al pezzo seguente),
     * come `_CONGIUNZIONE` nel ponte.
     */
    static _tagliaSuCongiunzione(testo, minimo) {
        var re = /\s+(?=([A-Za-zÀ-ÿ']+)[\s,.;:!?])/g;
        var m;
        var migliore = -1;
        while ((m = re.exec(testo)) !== null) {
            if (m.index >= minimo && AITTSManager.CONGIUNZIONI.has(m[1].toLowerCase())) {
                migliore = m.index;
            }
        }
        return migliore;
    }

    /** Ultimo spazio bianco oltre `minimo`. -1 se non c'e': mai a meta' parola. */
    static _tagliaSuSpazio(testo, minimo) {
        for (var i = testo.length - 1; i >= minimo; i--) {
            if (/\s/.test(testo[i])) return i;
        }
        return -1;
    }

    /**
     * Rete di sicurezza: nessun pezzo oltre il tetto, da qualunque strada arrivi.
     *
     * `_spezza` lascia sempre un avanzo (la coda dopo l'ultimo taglio) che
     * nessuno ricontrollava: la frase finale di un turno arrivava intera a
     * PocketTTS, che oltre ~50 token salta parole senza dirlo.
     */
    static _sottoTetto(testo) {
        var MAX = AITTSManager.MAX_SPEAK_CHARS;
        var fuori = [];
        var resto = String(testo || '').trim();
        while (resto.length > MAX) {
            var finestra = resto.slice(0, MAX + 1);
            var taglio = AITTSManager._tagliaSuCongiunzione(finestra, AITTSManager.MIN_SPEAK_CHARS);
            if (taglio < 0) taglio = AITTSManager._tagliaSuSpazio(finestra, AITTSManager.MIN_SPEAK_CHARS);
            // Una sola parola piu' lunga del tetto: si sfora invece di
            // spaccarla a meta'. Spezzare dentro la parola e' sempre peggio.
            if (taglio < 0) break;
            fuori.push(resto.slice(0, taglio).trim());
            resto = resto.slice(taglio).trim();
        }
        if (resto) fuori.push(resto);
        return fuori.filter(Boolean);
    }

    _spezza(regione, primo) {
        var pezzi = [];
        var corrente = '';

        for (var i = 0; i < regione.length; i++) {
            corrente += regione[i];
            var ch = regione[i];
            var next = regione[i + 1];
            var resto = regione.length - (i + 1);
            // Le soglie valgono per il pezzo in costruzione, non per la regione:
            // solo il PRIMO pezzo del turno si chiude presto. Prima restavano
            // larghe per tutta la regione e la voce suonava spezzettata.
            var inTesta = primo && pezzi.length === 0;
            var LOOK = inTesta ? 0 : AITTSManager.SUBSENTENCE_LOOKAHEAD;
            var MINIMO = inTesta ? AITTSManager.MIN_FIRST_SPEAK_CHARS : AITTSManager.MIN_SPEAK_CHARS;
            var MAX = inTesta ? AITTSManager.MAX_FIRST_SPEAK_CHARS : AITTSManager.MAX_SPEAK_CHARS;

            // La punteggiatura vale come taglio SOLO se dopo c'e' uno spazio:
            // e' la guardia che tiene insieme "1.541,19", "3,5%" e "LDO.MI",
            // dove dopo il punto o la virgola c'e' una cifra.
            if (next && /\s/.test(next)) {
                if (ch === '.' || ch === '!' || ch === '?' || ch === '…') {
                    var ultima = corrente.trim().split(/\s/).pop() || '';
                    if (!/^\d+\.$/.test(ultima) && !/^[A-Z][a-z]?\.$/.test(ultima)) {
                        pezzi.push(corrente);
                        corrente = '';
                        continue;
                    }
                } else if ((ch === ';' || ch === ':' || ch === ',') &&
                           corrente.trim().length >= MINIMO &&
                           resto >= LOOK) {
                    pezzi.push(corrente);
                    corrente = '';
                    continue;
                }
            }

            // Tetto: qui non si puo' aspettare uno spazio nel testo che segue,
            // altrimenti un elenco senza punteggiatura sfora di molto. Si torna
            // indietro dentro il pezzo: prima una congiunzione, poi l'ultimo
            // spazio, mai a meta' parola.
            if (corrente.length >= MAX) {
                var taglio = AITTSManager._tagliaSuCongiunzione(corrente, MINIMO);
                if (taglio < 0) taglio = AITTSManager._tagliaSuSpazio(corrente, MINIMO);
                // Nessuno spazio dentro il pezzo: e' una parola sola piu' lunga
                // del tetto (un URL, un nome di file). Si sfora, non si spacca:
                // il taglio arrivera' al primo spazio utile.
                if (taglio > 0) {
                    pezzi.push(corrente.slice(0, taglio));
                    corrente = corrente.slice(taglio);
                }
            }
        }
        return pezzi;
    }

    _processStreamingSentences(accumulatedText) {
        if (!this._streamActive) return;

        var text = accumulatedText
            .replace(/```[\s\S]*?```/g, '')
            .replace(/```[\s\S]*$/g, '');

        var plainText = this.extractPlainText(text);
        if (!plainText || plainText.length <= this._streamSentencesSent) return;

        var newRegion = plainText.substring(this._streamSentencesSent);

        // Raw chunks, whitespace included: the offset counter indexes into
        // plainText, so it has to advance by what was actually consumed. The
        // old code advanced by `trimmed.length + 1`, which assumes exactly one
        // separator character — a paragraph break ("\n\n") made it drift and
        // re-read a character every time.
        var primo = this._streamSentencesSent === 0;
        var chunks = this._spezza(newRegion, primo);

        if (chunks.length === 0) return;

        // Short chunks are glued onto the following one instead of being
        // dropped. Previously anything under 15 characters advanced the offset
        // without ever being queued, so a reply opening with "Ciao!" lost its
        // greeting outright — silently, since nothing logged the skip.
        var advancedChars = 0;
        var pending = '';
        var pendingRaw = 0;
        var btn = this._streamButton || this._createPlaceholderButton();
        var resetFn = this._streamResetFn || function() {};
        for (var j = 0; j < chunks.length; j++) {
            // La riunione dei pezzi corti si ferma al tetto: sommare un pezzo
            // da 14 caratteri con uno da 105 mandava 119 caratteri alla
            // sintesi, cioe' oltre il limite che si voleva rispettare.
            if (pending && (pending + chunks[j]).trim().length > AITTSManager.MAX_SPEAK_CHARS) {
                this.enqueue(pending.trim(), btn, resetFn);
                advancedChars += pendingRaw;
                pending = '';
                pendingRaw = 0;
            }
            pending += chunks[j];
            pendingRaw += chunks[j].length;
            var soglia = (primo && advancedChars === 0)
                ? AITTSManager.MIN_FIRST_SPEAK_CHARS : AITTSManager.MIN_SPEAK_CHARS;
            if (pending.trim().length < soglia) continue;
            this.enqueue(pending.trim(), btn, resetFn);
            advancedChars += pendingRaw;
            pending = '';
            pendingRaw = 0;
        }

        // A trailing short fragment is deliberately NOT counted as consumed:
        // it stays in newRegion so the next update can glue the following
        // sentence onto it, and streamingEnd() speaks it if the turn ends here.
        this._streamSentencesSent += advancedChars;
    }

    _createPlaceholderButton() {
        var btn = document.createElement('button');
        btn.style.display = 'none';
        btn.className = 'ai-tts-button streaming-placeholder';
        return btn;
    }

    streamingAttachButton(button, resetFn) {
        this._streamButton = button;
        this._streamResetFn = resetFn;
        for (var i = 0; i < this._queue.length; i++) {
            if (this._queue[i].button && this._queue[i].button.classList.contains('streaming-placeholder')) {
                this._queue[i].button = button;
                this._queue[i].resetFn = resetFn;
            }
        }
    }

    streamingEnd(finalText) {
        if (!this._streamActive) return;
        this._streamActive = false;
        if (this._streamDebounceTimer) {
            clearTimeout(this._streamDebounceTimer);
            this._streamDebounceTimer = null;
        }

        var text = finalText
            .replace(/```[\s\S]*?```/g, '')
            .replace(/```[\s\S]*$/g, '');

        var plainText = this.extractPlainText(text);
        if (!plainText) return;

        // No length floor here: this is the end of the turn, so there is
        // nothing left to glue a short tail onto. The old `>= 15` check made a
        // reply that ended on a brief sentence lose its closing line.
        var remaining = plainText.substring(this._streamSentencesSent).trim();
        if (remaining.length > 0) {
            var btn = this._streamButton || this._createPlaceholderButton();
            var resetFn = this._streamResetFn || function() {};

            // The tail gets cut too. Sending it whole would hand PocketTTS a
            // paragraph — past its ~50-token limit, where it starts dropping
            // words. The trailing space is there because _spezza() only cuts
            // when whitespace follows the punctuation, and the last sentence of
            // a turn has nothing after it.
            var conSpazio = remaining + ' ';
            var pezzi = this._spezza(conSpazio);
            var consumati = pezzi.join('').length;
            var coda = conSpazio.substring(consumati).trim();
            this._accodaConTetto(pezzi, coda, btn, resetFn);
        }
        this._streamSentencesSent = 0;
    }

    clearCache() {
        for (const url of this.cache.values()) {
            URL.revokeObjectURL(url);
        }
        this.cache.clear();
    }
}

// Create global AI TTS manager instance
window.aiTTSManager = new AITTSManager();

// Function to add AI TTS button to a message element's action bar
export function addAITTSButton(messageElement, text) {
    if (!window.aiTTSManager.available || window.aiTTSManager._provider === 'disabled') {
        return;
    }

    if (messageElement.querySelector('.ai-tts-button')) {
        return;
    }

    // Find the msg-actions container in the footer
    const actions = messageElement.querySelector('.msg-actions');
    if (!actions) return;

    var ICON_PLAY = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="6 3 20 12 6 21 6 3"/></svg>';
    var ICON_STOP = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>';
    var ICON_LOADING = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="9" stroke-dasharray="42" stroke-dashoffset="12" stroke-linecap="round"><animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="0.8s" repeatCount="indefinite"/></circle></svg>';

    const playButton = document.createElement('button');
    playButton.className = 'ai-tts-button';
    playButton.type = 'button';
    playButton.title = 'Leggi ad alta voce';
    playButton.innerHTML = ICON_PLAY;
    playButton.style.cssText = 'background:none;border:none;color:#6b7280;cursor:pointer;padding:2px 6px;border-radius:4px;transition:color .15s;line-height:1;display:inline-flex;align-items:center;';

    playButton.addEventListener('mouseenter', () => { playButton.style.color = '#ccc'; });
    playButton.addEventListener('mouseleave', () => {
        if (!playButton.classList.contains('playing') && !playButton.classList.contains('loading')) playButton.style.color = '#6b7280';
    });

    function resetButton() {
        playButton.innerHTML = ICON_PLAY;
        playButton.classList.remove('playing', 'loading');
        playButton.style.color = '#6b7280';
        playButton.title = 'Leggi ad alta voce';
    }

    playButton.addEventListener('click', async (e) => {
        e.stopPropagation();
        const mgr = window.aiTTSManager;

        if (mgr.isPlaying || mgr._processing) {
            mgr.stop();
            resetButton();
            return;
        }

        // Spezzettato, non intero: vedi enqueueSpezzato().
        mgr.enqueueSpezzato(text, playButton, resetButton);
    });

    actions.appendChild(playButton);
}

// Stop audio when navigating away
window.addEventListener('beforeunload', () => {
    if (window.aiTTSManager) {
        window.aiTTSManager.stop();
    }
});

export { AITTSManager };

const ttsModule = { AITTSManager, addAITTSButton };
export default ttsModule;
