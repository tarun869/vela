/**
 * Real vendor brand logos for the connector catalog, bundled as local assets
 * (no external/runtime CDN dependency). Each entry maps a connector id to its
 * imported logo and the tile background that suits that mark:
 *
 *   - `light`  — logo art is dark/coloured ink on transparency; sits on a white tile.
 *   - `dark`   — logo art is light/white ink (e.g. Generac wordmark); needs a dark tile.
 *
 * Connectors without a trustworthy first-party mark (e.g. AutoGrid, whose domain
 * now serves Uplight's brand) are intentionally omitted and fall back to the
 * abstract category glyph in ConnectorMark.
 */
import tesla from '../assets/logos/tesla.png'
import enphase from '../assets/logos/enphase.png'
import solaredge from '../assets/logos/solaredge.png'
import chargepoint from '../assets/logos/chargepoint.svg'
import nest from '../assets/logos/nest.png'
import sonnen from '../assets/logos/sonnen.png'
import generac from '../assets/logos/generac.svg'
import ecobee from '../assets/logos/ecobee.png'
import wallbox from '../assets/logos/wallbox.png'
import span from '../assets/logos/span.png'
import sunrun from '../assets/logos/sunrun.png'
import franklinwh from '../assets/logos/franklinwh.png'
import leap from '../assets/logos/leap.png'

export type ConnectorLogoTone = 'light' | 'dark'

export interface ConnectorLogoAsset {
  src: string
  /** Tile background tone the mark is designed to sit on. Defaults to 'light'. */
  tone?: ConnectorLogoTone
}

export const connectorLogos: Record<string, ConnectorLogoAsset> = {
  tesla:       { src: tesla },
  enphase:     { src: enphase },
  solaredge:   { src: solaredge },
  chargepoint: { src: chargepoint },
  nest:        { src: nest },
  sonnen:      { src: sonnen },
  generac:     { src: generac, tone: 'dark' },
  ecobee:      { src: ecobee },
  wallbox:     { src: wallbox },
  span:        { src: span },
  sunrun:      { src: sunrun },
  franklinwh:  { src: franklinwh },
  leap:        { src: leap },
}
