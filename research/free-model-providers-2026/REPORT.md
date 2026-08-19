# Zusätzliche kostenlose Modell-Provider für den LiteLLM-Proxy

> Erstellt am 2026-08-18 · Tiefe: standard · 36 Primärquellen · Workspace: `research/free-model-providers-2026/`

## Kurzfazit

- **Z.AI ist der beste nächste Universal-Provider:** `GLM-4.7-Flash`, `GLM-4.5-Flash` und das Vision-Modell `GLM-4.6V-Flash` sind offiziell mit $0 für Ein- und Ausgabe gelistet. Die API ist OpenAI-kompatibel; feste Gratislimits sind allerdings nicht öffentlich dokumentiert und sollten mit einem deutschen Testkonto gemessen werden. [1][2]
- **ElevenLabs ist der beste zusätzliche Audio-Provider:** Die kostenlose, monatlich erneuerte API-Quote umfasst TTS, STT, Musik und weitere Audiofunktionen; LiteLLM 1.97.0 unterstützt ElevenLabs bereits nativ. Der Free-Tarif ist in Deutschland jedoch ausschließlich nichtkommerziell und verlangt bei Veröffentlichung Attribution. [4][5][6][8]
- **Cartesia bietet ebenfalls erneuerbares Audio:** 20.000 Credits pro Monat entsprechen ungefähr 27 Minuten TTS oder 1 Stunde 51 Minuten STT. Auch hier beginnt kommerzielle Nutzung erst im Bezahlplan; außerdem braucht LiteLLM eine eigene Protokollübersetzung. [9][10][12]
- **Für Embeddings gibt es keinen ebenso starken neuen Dauergratis-Anbieter:** Jina und Voyage bieten großzügige, aber grundsätzlich einmalige Kontingente. Jinas wirklich kostenloses `jina-embeddings-v4` ist gedrosselt und nur für Forschung/nichtkommerzielle Nutzung gedacht. [19][20][21]
- **Für Bildanalyse und OCR existieren gute Spezialanbieter:** Azure Vision (5.000 Transaktionen/Monat), Google Cloud Vision (1.000 Einheiten je Feature/Monat), OCR.space (25.000 Anfragen/Monat), remove.bg (50 Bearbeitungen/Monat) und Sightengine (zeitlich unbegrenzter Free-Plan) sind real kostenlos, aber keine normalen LLM-Routen. [13][14][15][16][17]
- **Für echte Bild-/Videogenerierung wurde kein vorbehaltlos empfehlenswerter neuer Dauergratis-Provider gefunden.** Pollinations erlaubt durch Quests verdiente Pollen-Credits und besitzt eine OpenAI-kompatible API, garantiert aber kein monatliches Kontingent; die bereits im Projekt dokumentierten Zuverlässigkeits- und Rechtsbedenken bleiben bestehen. [18]
- **Scaleway ist technisch und regional attraktiv, aber nur als Trial:** OpenAI-kompatibel, in Paris gehostet, 1 Mio. Tokens plus 60 Audiominuten gratis; danach wird automatisch abgerechnet und eine Erneuerung der Quote ist nicht dokumentiert. [22][23]
- **Together AI, SambaNova, Fireworks und die großen Bildhosts fallen für dieses Projekt durch:** fehlende erneuerbare Gratisquote, erforderlicher Guthabenkauf, widersprüchliche Zugangsbedingungen oder bloße Start-Credits. [24][25][26][27]

## Hintergrund und Abgrenzung

Gesucht wurden neue API-Anbieter für Chat/Reasoning/Code, Vision, Embeddings/Reranking, Bild/Video sowie Audio. Nicht erneut bewertet wurden die bereits integrierten 13 Provider. „Kostenlos“ bedeutet hier nutzbar ohne laufende Bezahlung; einmalige Credits und zeitlich begrenzte Promos werden separat ausgewiesen. Die Bewertung bezieht sich auf individuelle Nutzung aus Deutschland/EU und den Stand vom 18. August 2026.

## Priorität A: jetzt live verifizieren

### 1. Z.AI — Text, Reasoning, Coding und Vision

Z.AI listet `GLM-4.7-Flash`, `GLM-4.5-Flash` und `GLM-4.6V-Flash` mit vollständig kostenlosen Ein- und Ausgabetokens. Bildgenerierung, Videogenerierung und ASR bei Z.AI sind dagegen kostenpflichtig. [1] Die Chat-API lässt sich mit OpenAI-Clients über `https://api.z.ai/api/paas/v4/` ansprechen, wobei Z.AI auf kleinere Schnittstellenunterschiede hinweist. [2]

Die internationalen Nutzungsbedingungen schließen Deutschland oder die EU nicht aus und gestatten ausdrücklich die Integration in eigene Anwendungen für nachgelagerte Endnutzer. Der Betreiber bleibt für Nutzerverwaltung, Sicherheit, Missbrauch und rechtliche Hinweise verantwortlich. [3] Nicht geklärt ist, wie hoch RPM, TPM oder tägliche Quoten der kostenlosen Modelle tatsächlich sind. Deshalb sollte Z.AI erst nach einem Live-Test ohne Zahlungsmittel mit konservativen Routingwerten aufgenommen werden.

**Empfehlung:** höchster Integrationsnutzen. Testen: Konto ohne Karte, `/models`, je ein Chat- und Vision-Aufruf, Rate-Limit-Header, Dauerbetrieb über mehrere Tage.

### 2. ElevenLabs — TTS, STT, Musik, Soundeffekte und Dubbing

ElevenLabs erneuert den kostenlosen API-Tarif monatlich. Die aktuelle Preistabelle nennt unter anderem 20.000 Flash/Turbo-TTS-Zeichen, 4,5 Stunden Scribe-v2-STT, 2,5 Stunden Realtime-STT und 3 Minuten Musik. [4] Die meisten API-Endpunkte stehen Free-Nutzern zur Verfügung. [7] LiteLLM implementiert bereits ElevenLabs-Adapter für Audio-Transkription und TTS, wodurch die Integration relativ risikoarm ist. [8]

Die Einschränkung ist lizenzrechtlich wichtig: Für Nutzer im EWR ist der Free-Tarif nur nichtkommerziell; veröffentlichte Free-Ausgaben müssen ElevenLabs zugeordnet werden. [5][6] Standardmäßig liegen Kundendaten in den USA. EU-Hosting, EU-Endpunkt und strikte EU-Verarbeitung sind Enterprise-Funktionen. [36]

**Empfehlung:** aufnehmen, sofern der Proxy ausdrücklich privat/nichtkommerziell ist und README/API-Metadaten Attribution sowie Lizenzgrenze deutlich anzeigen.

### 3. Cartesia — TTS und STT

Cartesia erneuert monatlich 20.000 Credits. Laut Preistabelle reicht das ungefähr für 27 Minuten Sonic-3.6-TTS oder 1 Stunde 51 Minuten Ink-2-STT. Eine kommerzielle Lizenz beginnt erst im Pro-Tarif. [9] Die Nutzungsbedingungen beschränken die kostenlose Standardlizenz entsprechend auf persönliche, nichtkommerzielle Verwendung. [10]

Technisch ist Cartesia aufwendiger: TTS und STT nutzen eigene Endpunkte wie `/tts/bytes` und `/stt` sowie einen versionierten Header. Ein nativer Cartesia-Adapter ist in LiteLLM 1.97.0 nicht dokumentiert, daher wäre ein Übersetzer auf die OpenAI-Audio-Schemata nötig. [12] Dedizierte regionale/EU-Deployments sind Enterprise vorbehalten. [11]

**Empfehlung:** zweite Audio-Priorität hinter ElevenLabs; nur integrieren, wenn der zusätzliche Wartungsaufwand für einen nichtkommerziellen Tarif akzeptabel ist.

## Priorität B: kostenlose Spezial-APIs außerhalb normaler LiteLLM-Routen

| Anbieter | Kategorie | Erneuerbare Gratisquote | Haupthaken | Bewertung |
|---|---|---:|---|---|
| Azure Vision | Vision/OCR/multimodale Embeddings | 5.000 Transaktionen/Monat, 20 TPM | Azure-Ressource und regionsabhängiges F0-Angebot; kein Chat-Schema | Stark für Analyse/Retrieval [13] |
| Google Cloud Vision | Vision/OCR | 1.000 Einheiten je Feature/Monat | Separates Google-Cloud-Produkt, nicht Gemini/LiteLLM-Chat | Stark für OCR/Labels [14] |
| OCR.space | OCR/PDF | 25.000 Anfragen/Monat, max. 500/Tag/IP | 1 MB, PDF max. 3 Seiten, kein SLA | Sehr gute spezialisierte Gratisquote [15] |
| remove.bg | Bildbearbeitung | 50 Hintergrundentfernungen/Monat | Nur eine enge Funktion, proprietäres Schema | Sinnvoll als separates Tool [16] |
| Sightengine | Moderation/AI-Detection/OCR | Zeitlich unbegrenzt, 1 RPS | Monatsmenge öffentlich nicht genannt; kein Free-Video | Erst nach Konto-Verifikation [17] |

Diese Dienste sollten eher als separate Tool-Endpunkte oder Adapter behandelt werden, nicht als Modelle in einer Chat-Fallback-Kette. Azure Vision ist besonders interessant, weil die kostenlose Stufe auch multimodale Text-/Bild-Embeddings enthält. [13]

## Priorität C: Trials oder bedingte Gratisnutzung

### Embeddings und Reranking

Jina vergibt pro neuem API-Key einmalig 10 Mio. Tokens für Embeddings, Reranking, Klassifikation und DeepSearch. Die Embedding-API liegt unter einem OpenAI-ähnlichen `/v1/embeddings`-Endpunkt und erlaubt im Trial 100 RPM, 100.000 TPM und zwei parallele Anfragen. [20][19] Das dauerhaft auf $0 gesetzte `jina-embeddings-v4` ist jedoch für Forschung/nichtkommerzielle Nutzung lizenziert und nicht auf Production-Durchsatz ausgelegt. [19]

Voyage bietet je Konto sehr große, aber endliche Freimengen: bei aktuellen General-/Code-Embeddings und Rerankern bis zu 200 Mio. Tokens; beim multimodalen Modell zusätzlich 150 Mrd. Bild-/Videopixel. Batch-Aufrufe sind ausgeschlossen, nach Verbrauch wird abgerechnet. [21]

**Empfehlung:** als ausdrücklich begrenzte Trial-Kapazität dokumentieren, nicht in die dauerhafte Free-Fallback-Matrix aufnehmen.

### Scaleway Generative APIs

Scaleway nutzt `https://api.scaleway.ai/v1`, funktioniert mit dem OpenAI-SDK und hostet die Serverless-Modelle aktuell in Paris. [22][23] Das kostenlose Startkontingent beträgt höchstens 1 Mio. Modell-Tokens und 60 Transkriptionsminuten; anschließend erfolgt automatische Abrechnung. Die Dokumentation nennt keinen Reset. [23]

**Empfehlung:** wegen EU-Hosting ein guter optionaler Trial-Provider, aber ohne bestätigte Erneuerung kein „free provider“ im Sinne des Projekts.

### Pollinations

Pollinations bietet Text, Bildgenerierung, Bildbearbeitung und Video über eine OpenAI-kompatible API. Pollen-Credits können ohne Geld durch Quests verdient werden, sind aber kein garantiertes monatliches Freikontingent; Secret-Key-Anfragen verbrauchen das Guthaben. [18]

**Empfehlung:** nicht integrieren. Das Earned-Credit-Modell ist nicht planbar und löst die bereits im Projekt festgehaltenen Rechts-/Zuverlässigkeitsbedenken nicht.

## Ausgeschlossene Kandidaten

| Anbieter | Warum nicht als kostenlos aufnehmen? | Quellen |
|---|---|---|
| Together AI | Kein Free Trial; mindestens $5 Guthabenkauf und positiver Saldo vor API-Aufrufen, selbst wenn einzelne Modelle mit $0 gelistet sind. | [24] |
| SambaNova | Rate-Limit-Doku beschreibt zwar einen täglichen Free Tier, die aktuelle Tarifseite verlangt jedoch Zahlungsmittel und gekaufte Credits vor dem ersten Request. Bis zu einem echten Neuanmeldungstest gilt die strengere aktuelle Aussage. | [25] |
| Fireworks AI | Nur $1 einmaliges Startguthaben; danach kostenpflichtig. | [26] |
| Stability AI | Einmalig 25 Credits, laut eigener Umrechnung nur $0,25; kein erneuerbares API-Kontingent. | [27] |
| fal | Prepaid-Credits; erfolgreiche Bild-/Videoausgaben sind kostenpflichtig. | [28] |
| Replicate | Zeit- bzw. outputbasierte Abrechnung, keine dokumentierte erneuerbare Gratisquote. | [29] |
| Runware | Einmalig $2 Startguthaben; danach Pay-as-you-go. | [30] |
| Segmind | Mindestens $10 Aufladung für die API; „Free Account“ bedeutet keine kostenlose Inferenz. | [31] |
| Deepgram | Einmalige $200 Credits; danach Pay-as-you-go. Positiv: dedizierter EU-Endpunkt. | [32] |
| Speechmatics | Einmalige $100 Credits ohne Karte; danach Upgrade nötig. | [33] |
| AssemblyAI | Einmalige $50 Audio-Credits; danach blockiert bis zum Upgrade. | [34] |
| Gladia | Seit Juli 2026 keine monatlichen 10 Gratisstunden mehr, sondern einmalige €50 Wallet-Credits. | [35] |

## Empfohlene Reihenfolge

1. **Z.AI live testen und bei Erfolg integrieren**: drei kostenlose Modelle, hoher Zusatznutzen, OpenAI-kompatibel.
2. **ElevenLabs live testen und integrieren**, falls nichtkommerzielle Nutzung/Attribution zum Projekt passt.
3. **Cartesia nur nach Kosten-Nutzen-Abwägung** eines eigenen Audio-Adapters integrieren.
4. **Azure Vision, OCR.space und optional Google Cloud Vision** als separate Spezialtools planen, nicht in die normale Chat-Fallback-Matrix drücken.
5. **Jina/Voyage/Scaleway höchstens als opt-in Trials** führen, mit sichtbarem Restguthaben und hartem Stop vor kostenpflichtiger Nutzung.
6. **Keine neue Bildgenerierungsroute hinzufügen**, solange kein stabiler, rechtlich klarer, erneuerbarer Gratisanbieter gefunden wird.

## Offene Fragen

- Kann ein neues deutsches Z.AI-Konto die drei $0-Modelle ohne Karte oder Einzahlung aufrufen, und welche RPM/TPM/RPD-Werte zeigt das Konto?
- Sind alle für den Proxy vorgesehenen ElevenLabs-TTS-/STT-Modelle im Free-Tarif wirklich freigeschaltet, und wie werden Credits pro Modell abgezogen?
- Darf Cartesia-Free-Output ohne Attribution öffentlich verbreitet werden? Die Bedingungen beantworten die kommerzielle Nutzung, aber nicht diese Detailfrage eindeutig.
- Lässt sich Azure Vision F0 in einer deutschen bzw. westeuropäischen Subscription tatsächlich anlegen?
- Wie viele monatliche Operationen enthält der Sightengine-Free-Tarif aktuell?

## Quellen

[1] Z.AI Pricing — https://docs.z.ai/guides/overview/pricing (Datum unbekannt, abgerufen 2026-08-18)
[2] Z.AI OpenAI SDK Compatibility — https://docs.z.ai/guides/develop/openai/python (Datum unbekannt, abgerufen 2026-08-18)
[3] Z.AI Terms of Use — https://docs.z.ai/legal-agreement/terms-of-use (veröffentlicht 2026-04-14, abgerufen 2026-08-18)
[4] ElevenLabs API Pricing — https://elevenlabs.io/pricing/api (Datum unbekannt, abgerufen 2026-08-18)
[5] ElevenLabs EEA Terms — https://elevenlabs.io/terms-of-use-eu (veröffentlicht 2026-03-31, abgerufen 2026-08-18)
[6] ElevenLabs Free-Plan Publication Rules — https://help.elevenlabs.io/hc/en-us/articles/13313564601361-Can-I-publish-the-content-I-generate-on-the-platform (Datum unbekannt, abgerufen 2026-08-18)
[7] ElevenLabs API Availability by Plan — https://elevenlabs.io/docs/help-center/technical/how-much-does-it-cost-to-use-the-api (Datum unbekannt, abgerufen 2026-08-18)
[8] LiteLLM ElevenLabs Audio Adapter — https://github.com/BerriAI/litellm/blob/main/litellm/llms/elevenlabs/audio_transcription/transformation.py (Datum unbekannt, abgerufen 2026-08-18)
[9] Cartesia Pricing — https://www.cartesia.ai/pricing (Datum unbekannt, abgerufen 2026-08-18)
[10] Cartesia Terms — https://www.cartesia.ai/legal/terms (veröffentlicht 2024-06-14, abgerufen 2026-08-18)
[11] Cartesia Regional Endpoints — https://docs.cartesia.ai/enterprise/regional-endpoints (Datum unbekannt, abgerufen 2026-08-18)
[12] Cartesia API Conventions — https://docs.cartesia.ai/use-the-api/api-conventions (Datum unbekannt, abgerufen 2026-08-18)
[13] Azure Vision Pricing — https://azure.microsoft.com/en-us/pricing/details/computer-vision/ (Datum unbekannt, abgerufen 2026-08-18)
[14] Google Cloud Vision Pricing — https://cloud.google.com/vision/pricing (Datum unbekannt, abgerufen 2026-08-18)
[15] OCR.space API — https://ocr.space/ocrapi (Datum unbekannt, abgerufen 2026-08-18)
[16] remove.bg API — https://www.remove.bg/api (Datum unbekannt, abgerufen 2026-08-18)
[17] Sightengine Pricing — https://sightengine.com/pricing (Datum unbekannt, abgerufen 2026-08-18)
[18] Pollinations Repository/API Documentation — https://github.com/pollinations/pollinations (veröffentlicht/abgerufen 2026-08-18)
[19] Jina Embeddings — https://jina.ai/en-US/embeddings/ (Datum unbekannt, abgerufen 2026-08-18)
[20] Jina Reader and Search Foundation APIs — https://jina.ai/reader/ (Datum unbekannt, abgerufen 2026-08-18)
[21] Voyage AI Pricing — https://docs.voyageai.com/docs/pricing (Datum unbekannt, abgerufen 2026-08-18)
[22] Scaleway Generative APIs Quickstart — https://www.scaleway.com/en/docs/generative-apis/quickstart/ (veröffentlicht 2026-04-16, abgerufen 2026-08-18)
[23] Scaleway Generative APIs FAQ — https://www.scaleway.com/en/docs/generative-apis/faq/ (veröffentlicht 2026-04-13, abgerufen 2026-08-18)
[24] Together AI Billing and Credits — https://docs.together.ai/docs/billing-credits (Datum unbekannt, abgerufen 2026-08-18)
[25] SambaNova Plans — https://cloud.sambanova.ai/plans (Datum unbekannt, abgerufen 2026-08-18)
[26] Fireworks AI Pricing — https://fireworks.ai/pricing (Datum unbekannt, abgerufen 2026-08-18)
[27] Stability AI Platform Pricing — https://platform.stability.ai/pricing (Datum unbekannt, abgerufen 2026-08-18)
[28] fal Model API Pricing — https://fal.ai/docs/documentation/model-apis/pricing (Datum unbekannt, abgerufen 2026-08-18)
[29] Replicate Pricing — https://replicate.com/pricing (Datum unbekannt, abgerufen 2026-08-18)
[30] Runware Pricing — https://runware.ai/pricing (veröffentlicht 2026, abgerufen 2026-08-18)
[31] Segmind Pricing and Billing — https://docs.segmind.com/docs/account/pricing-and-billing (Datum unbekannt, abgerufen 2026-08-18)
[32] Deepgram Pricing — https://deepgram.com/pricing (Datum unbekannt, abgerufen 2026-08-18)
[33] Speechmatics Pricing — https://www.speechmatics.com/pricing (Datum unbekannt, abgerufen 2026-08-18)
[34] AssemblyAI Free Signup Credits — https://support.assemblyai.com/articles/5370767329-can-i-sign-up-for-free (veröffentlicht 2026-02-27, abgerufen 2026-08-18)
[35] Gladia Credit-based Billing — https://support.gladia.io/article/credit-based-billing (Datum unbekannt, abgerufen 2026-08-18)
[36] ElevenLabs Data Residency — https://elevenlabs.io/docs/overview/administration/data-residency (Datum unbekannt, abgerufen 2026-08-18)
