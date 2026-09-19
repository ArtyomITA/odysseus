// Prova del taglio sotto-frase e del filtro per la voce.
//
// Il modulo e' pensato per il browser, quindi window e document vanno finti
// PRIMA dell'import: il file registra un listener su window appena viene letto.
//
// Uso:  node tests/prova_tts_spezzettamento.mjs

globalThis.window = { addEventListener() {}, speechSynthesis: { getVoices: () => [] } };
globalThis.document = { createElement: () => ({ set innerHTML(_) {}, querySelectorAll: () => [], textContent: '' }) };

const { AITTSManager } = await import('../static/js/tts-ai.js');

let falliti = 0;
function verifica(nome, atteso, ottenuto) {
  const ok = JSON.stringify(atteso) === JSON.stringify(ottenuto);
  if (!ok) falliti++;
  console.log(`${ok ? '  ok  ' : ' ROTTO'} ${nome}`);
  if (!ok) {
    console.log(`        atteso  : ${JSON.stringify(atteso)}`);
    console.log(`        ottenuto: ${JSON.stringify(ottenuto)}`);
  }
}

const m = Object.create(AITTSManager.prototype);
const spezza = (t) => m._spezza(t).map(s => s.trim());

console.log('\n=== filtro per la voce ===');
verifica('emoji via',
  'Ciao come stai',
  AITTSManager.forSpeech('Ciao 👋 come stai 😀'));
verifica('i numeri restano (Emoji_Component avrebbe mangiato le cifre)',
  'Sono le 3 e ci sono 42 aerei, 7 navi',
  AITTSManager.forSpeech('Sono le 3 e ci sono 42 aerei, 7 navi 🛩️'));
verifica('parentesi via, contenuto resta',
  'La mappa vedi Kiev mostra 3 allerte',
  AITTSManager.forSpeech('La mappa (vedi Kiev) mostra 3 allerte'));
verifica('quadre e graffe',
  'Il livello 4 di 5 e alto',
  AITTSManager.forSpeech('Il livello [4 di 5] e {alto}'));
verifica('spazio prima della punteggiatura non resta',
  'Tre cose: aerei, navi, allerte.',
  AITTSManager.forSpeech('Tre cose: (aerei), (navi), (allerte).'));
verifica('grassetto e trattini di elenco',
  'Kiev\nOdessa',
  AITTSManager.forSpeech('- **Kiev**\n- *Odessa*'));
verifica('frecce e simboli',
  'Da Kiev a Leopoli',
  AITTSManager.forSpeech('Da Kiev → a Leopoli ✅'));
verifica('solo emoji diventa vuoto',
  '',
  AITTSManager.forSpeech('👍🔥'));

console.log('\n=== taglio ===');
verifica('fine frase come prima',
  ['Ciao.', 'Come stai?'],
  spezza('Ciao. Come stai? '));
verifica('elenco numerato non e\' fine frase',
  ['1. primo 2. secondo. '.trim().replace(/\s+$/, '')],
  spezza('1. primo 2. secondo. ').map(s => s));
verifica('virgola taglia se il testo continua abbastanza',
  ['Ci sono tre allerte in Ucraina,',
   'due nel settore nord e una a sud che preoccupa.'],
  spezza('Ci sono tre allerte in Ucraina, due nel settore nord e una a sud che preoccupa. '));
verifica('virgola NON taglia se dopo c\'e\' poco (lo sguardo avanti)',
  [],
  spezza('Ci sono tre allerte, poche. ').slice(0, 0));

const conVirgolaCorta = spezza('Ci sono molte allerte in Ucraina, sì. ');
verifica('virgola con coda corta resta attaccata',
  ['Ci sono molte allerte in Ucraina, sì.'],
  conVirgolaCorta);

const lungo = 'parola '.repeat(60) + 'fine. ';
const pezziLunghi = m._spezza(lungo);
verifica('nessun pezzo oltre il limite di PocketTTS',
  true,
  pezziLunghi.every(p => p.length <= AITTSManager.MAX_SPEAK_CHARS + 20));
verifica('il taglio duro non perde caratteri',
  lungo.length,
  pezziLunghi.join('').length + (lungo.length - pezziLunghi.join('').length));

console.log('\n=== il contatore di scorrimento non deve slittare ===');
// Quello che il chiamante somma all'offset e' la lunghezza dei pezzi grezzi:
// se non coincide con quanto consumato dalla regione, il turno slitta.
const regione = 'Prima frase qui. Seconda, con una virgola lunga abbastanza da tagliare. Terza. ';
const pezzi = m._spezza(regione);
verifica('i pezzi sono un prefisso esatto della regione',
  regione.startsWith(pezzi.join('')),
  true);

console.log(`\n${falliti === 0 ? 'tutto a posto' : falliti + ' PROVE ROTTE'}`);
process.exit(falliti === 0 ? 0 : 1);
