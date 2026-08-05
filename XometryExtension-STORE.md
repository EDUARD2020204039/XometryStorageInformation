# Chrome Web Store publication

Upload `XometryExtension-v2.67.zip` as a new Chrome Web Store item and select
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

> Extensie interna pentru portalul Xometry Partner. Calculeaza preturi, verifica
> stocuri si istoric, porneste analiza tehnica si generarea fisierelor GEO si
> permite crearea dosarelor interne de productie. Transferul catre serviciile
> HABA este dezactivat pana cand utilizatorul isi exprima acordul in pagina de
> configurare.

## Permission justifications

- `storage`: pastreaza local acordul utilizatorului, dimensiunile, valorile de
  ofertare si preferintele extensiei.
- `downloads`: descarca documentatia si fisierele GEO numai la comanda
  utilizatorului.
- `partner.xometry.eu`: citeste oferta afisata pentru a adauga instrumentele de
  calcul si analiza.
- Domeniile `habaresearch.eu`: comunica prin HTTPS/WSS cu serviciile interne de
  stoc, istoric, analiza GEO si dosare de productie.

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
