# Chrome Web Store publication

Upload the ZIP matching the current manifest version as a Chrome Web Store item and select
**Unlisted** visibility. Users must install the store listing once; later
published versions are delivered automatically by Chrome.

## Listing

- Name: `Xometry Price Calculator`
- Category: `Productivity`
- Language: `Romanian`
- Homepage: `https://xometrystorageinformation.habaresearch.eu/`
- Privacy policy: `https://xometrystorageinformation.habaresearch.eu/static/extension-privacy.html`
- Single purpose: `Analiza tehnica si ofertarea joburilor din portalul Xometry Partner pentru fluxul intern HABA.`

Suggested description:

> Xometry Price Calculator este o extensie interna pentru echipa HABA care
> adauga instrumente de ofertare direct in portalul Xometry Partner. Extensia
> preia informatiile tehnice vizibile ale ofertei, permite calcularea si
> pastrarea valorilor de ofertare, verifica stocurile si istoricul reperelor,
> porneste analiza tehnica si generarea fisierelor GEO si ajuta la crearea
> dosarelor interne de productie. Fisierele GEO pot fi vizualizate sau
> descarcate la cererea utilizatorului. Comunicarea cu serviciile interne HABA
> foloseste conexiuni securizate HTTPS/WSS si este dezactivata pana cand
> utilizatorul isi exprima acordul in pagina de configurare. Extensia nu
> afiseaza reclame si nu vinde datele prelucrate.

## Permission justifications

- `storage`: pastreaza local acordul utilizatorului, dimensiunile, valorile de
  ofertare si preferintele extensiei.
- `downloads`: descarca documentatia si fisierele GEO numai la comanda
  utilizatorului.
- `partner.xometry.eu`: citeste oferta afisata pentru a adauga instrumentele de
  calcul si analiza.
- Domeniile `habaresearch.eu`: comunica prin HTTPS/WSS cu serviciile interne de
  stoc, istoric, analiza GEO si dosare de productie.

## Remote code

Select **No, I am not using remote code**.

Justification, if the form requests text:

> Extensia nu executa JavaScript, WebAssembly sau alt cod descarcat de la
> distanta. Toate fisierele executabile sunt incluse in pachetul extensiei.
> Serviciile HABA returneaza numai date JSON, fisiere si stari operationale,
> care sunt procesate de codul local inclus in extensie.

## Privacy declarations

Declare collection of website content and user activity because the extension
reads offer data from the Xometry page and sends it to HABA services after
consent. Declare that data is used only for the extension's stated purpose,
is not sold, is not used for advertising and is not used for credit decisions.

## Release flow

1. Increase `version` in `XometryExtension/manifest.json`.
2. Run syntax and manifest validation.
3. Build a ZIP whose root contains `manifest.json`.
4. Upload the ZIP to the existing Web Store item and submit it for review.
5. Publish after approval. Chrome checks for updates periodically and at browser startup.

The first publication is manual. After the Web Store item exists, its item ID
and Google Web Store API credentials can be stored as repository secrets to
automate future uploads without exposing credentials in source control.
