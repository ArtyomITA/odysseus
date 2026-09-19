"""Vista — gli occhi di Vergilius.

Holo-3.1-0.8B (VLM piccolo, full-CPU) interroga immagini al posto del cervello
testuale (LFM), che non vede. Il cervello riceve SOLO testo/JSON: nessuna
immagine entra mai nel suo contesto (llama-server erra su ImageContent senza
mmproj, e la cache KV resta stabile).

Misure che guidano il design (ricerche/vlm-occhi/07-parte1-*.md):
- grounding GUI 24/27 col prompt ufficiale H Company; i mancati sono tutti
  target < 30px -> zoom a 2 step li recupera (2/3);
- risponde a UNA domanda per chiamata: prompt composti -> risponde alla prima;
- vincoli "N righe" -> N parole; JSON con schema -> risposta pulita;
- 4 frame in una richiesta -> si ancora al primo; frame singoli -> corretti.
Quindi: Python orchestra (scompone, zooma, sequenzia), Holo guarda, LFM racconta.
"""
