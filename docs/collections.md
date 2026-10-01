# Collections

Every collection the portal lists, one per satellite and sensor, built from
`src/bhoonidhi_stac/data/collections-manifest.json`. `scripts/collections_md.py`
writes this page; do not edit it by hand.

- **Producer**: the satellite's operator, credited in the collection's
  `providers`. NRSC/ISRO Bhoonidhi is the host and licensor of every
  collection.
- **Access**: the portal's access level. Open data is downloaded directly
  or ordered free of charge; priced data is sold.
- **Period**: when the products were acquired. "acquiring" means at least
  one product is still being added.

79 collections.

| Collection | Satellite | Sensor | Products | Producer | Access | Period |
|---|---|---|---|---|---|---|
| `aqua-modis` | Aqua | MODIS | (default) | NASA | open, on order | 2003-12-31 to 2019-12-31 |
| `cartosat-2-pan-spot` | CartoSat-2 | PAN(SPOT) | (default) | ISRO | priced | 2007-04-14 to 2019-05-23 |
| `cartosat-2s-mx-spot` | CartoSat-2S | MX(SPOT) | (default) | ISRO | priced | 2017-06-25 to acquiring |
| `cartosat-2s-pan-spot` | CartoSat-2S | PAN(SPOT) | (default) | ISRO | priced | 2017-06-25 to acquiring |
| `cartosat-3-mx-spot` | CartoSat-3 | MX(SPOT) | 17km-swath, 10km-swath | ISRO | priced | 2020-06-10 to acquiring |
| `cartosat-3-pan-spot` | CartoSat-3 | PAN(SPOT) | (default) | ISRO | priced | 2020-06-10 to acquiring |
| `eos-04-sar-crs` | EOS-04 | SAR(CRS) | L2B | ISRO | open, direct download | 2022-03-23 to acquiring |
| `eos-04-sar-frs1` | EOS-04 | SAR(FRS1) | (default) | ISRO | open, direct download | 2022-03-23 to acquiring |
| `eos-04-sar-frs2` | EOS-04 | SAR(FRS2) | (default) | ISRO | open, direct download | 2022-03-23 to acquiring |
| `eos-04-sar-mrs` | EOS-04 | SAR(MRS) | L2B, 1x1deg-tiles, WaterSpread, SoilMoisture | ISRO | open, direct download | 2022-03-23 to acquiring |
| `eos-06-ocm-gac` | EOS-06 | OCM(GAC) | L1C, L2C-AOD, L2C-Chlorophyll, L2C-DA, L2C-NDVI, L2C-RRS, L2C-TSM, L2C-VF | ISRO | open, direct download | 2023-04-01 to acquiring |
| `eos-06-ocm-lac` | EOS-06 | OCM(LAC) | L1C, L2C-AOD, L2C-Chlorophyll, L2C-DA, L2C-NDVI, L2C-RRS, L2C-TSM | ISRO | open, direct download | 2023-04-01 to acquiring |
| `irs-1a-liss1` | IRS-1A | LISS1 | (default) | ISRO | open, on order | 1988-04-04 to 1991-05-28 |
| `irs-1a-liss2` | IRS-1A | LISS2 | (default) | ISRO | open, on order | 1988-04-04 to 1991-05-28 |
| `irs-1b-liss1` | IRS-1B | LISS1 | (default) | ISRO | open, on order | 1991-10-02 to 2001-09-09 |
| `irs-1b-liss2` | IRS-1B | LISS2 | (default) | ISRO | open, on order | 1991-10-02 to 2001-09-09 |
| `irs-1c-liss3` | IRS-1C | LISS3 | (default) | ISRO | open, on order | 1996-11-14 to 2007-09-20 |
| `irs-1c-pan` | IRS-1C | PAN | (default) | ISRO | open, on order | 1996-11-14 to 2007-09-20 |
| `irs-1c-wifs` | IRS-1C | WIFS | (default) | ISRO | open, on order | 1996-11-14 to 2007-09-20 |
| `irs-1d-liss3` | IRS-1D | LISS3 | (default) | ISRO | open, on order | 1998-01-01 to 2007-09-20 |
| `irs-1d-pan` | IRS-1D | PAN | (default) | ISRO | open, on order | 1998-01-01 to 2007-09-20 |
| `irs-1d-wifs` | IRS-1D | WIFS | (default) | ISRO | open, on order | 1998-01-01 to 2007-09-20 |
| `jpss1-viirs` | JPSS1 | VIIRS | Day-Night_L1, Imagery_L1,  Moderate_L1 | NOAA | open, direct download | 2021-01-15 to acquiring |
| `kompsat-3-ms` | KompSat-3 | MS | (default) | KARI | priced | 2018-01-01 to 2020-05-29 |
| `kompsat-3a-ms` | KompSat-3A | MS | (default) | KARI | priced | 2018-01-01 to 2020-05-31 |
| `landsat-8-oli-tirs` | LandSat-8 | OLI+TIRS | L1 | USGS | open, direct download | 2017-01-01 to acquiring |
| `landsat-9-oli-tirs` | LandSat-9 | OLI+TIRS | L1 | USGS | open, direct download | 2022-04-01 to acquiring |
| `metop-b-avhrr` | MetOp-B | AVHRR | L1C | EUMETSAT | open, direct download | 2025-08-01 to acquiring |
| `metop-c-avhrr` | MetOp-C | AVHRR | L1C | EUMETSAT | open, direct download | 2025-08-01 to acquiring |
| `nisar-ssar` | NISAR | SSAR | RIFG, ROFF, RSLC, RUNW, GCOV, GOFF, GSLC, GUNW | NASA/ISRO | open, direct download | 2026-07-08 to acquiring |
| `noaa-11-avhrr` | NOAA-11 | AVHRR | (default) | NOAA | open, on order | 1994-08-25 to 1994-09-13 |
| `noaa-12-avhrr` | NOAA-12 | AVHRR | (default) | NOAA | open, on order | 1994-09-14 to 1995-11-04 |
| `noaa-14-avhrr` | NOAA-14 | AVHRR | (default) | NOAA | open, on order | 1995-04-03 to 2010-09-22 |
| `noaa-16-avhrr` | NOAA-16 | AVHRR | (default) | NOAA | open, on order | 2001-06-20 to 2005-08-11 |
| `noaa-17-avhrr` | NOAA-17 | AVHRR | (default) | NOAA | open, on order | 2005-09-20 to 2010-04-13 |
| `noaa-18-avhrr` | NOAA-18 | AVHRR | (default) | NOAA | open, on order | 2005-10-01 to 2009-10-09 |
| `noaa-19-avhrr` | NOAA-19 | AVHRR | L1C | NOAA | open, direct download | 2025-01-01 to 2025-08-11 |
| `novasar-1-sar-20m-2pol-scansar` | Novasar-1 | SAR(20m-2Pol-ScanSAR) | Strip | SSTL | open, direct download | 2019-10-01 to acquiring |
| `novasar-1-sar-20m-scansar` | Novasar-1 | SAR(20m-ScanSAR) | Strip | SSTL | open, direct download | 2019-10-01 to acquiring |
| `novasar-1-sar-30m-3pol-scansar` | Novasar-1 | SAR(30m-3Pol-ScanSAR) | Strip | SSTL | open, direct download | 2019-10-01 to acquiring |
| `novasar-1-sar-30m-scansar` | Novasar-1 | SAR(30m-ScanSAR) | Strip | SSTL | open, direct download | 2019-10-01 to acquiring |
| `novasar-1-sar-33m-copol-scansar` | Novasar-1 | SAR(33m-CoPol-ScanSAR) | Strip | SSTL | open, direct download | 2019-10-01 to acquiring |
| `novasar-1-sar-35m-3pol-scansar` | Novasar-1 | SAR(35m-3Pol-ScanSAR) | Strip | SSTL | open, direct download | 2019-10-01 to acquiring |
| `novasar-1-sar-40m-scansar` | Novasar-1 | SAR(40m-ScanSAR) | Strip | SSTL | open, direct download | 2019-10-01 to acquiring |
| `novasar-1-sar-50m-co6-cross1-scansar` | Novasar-1 | SAR(50m-Co6+Cross1-ScanSAR) | Strip | SSTL | open, direct download | 2019-10-01 to acquiring |
| `novasar-1-sar-50m-co6-cross3-scansar` | Novasar-1 | SAR(50m-Co6+Cross3-ScanSAR) | Strip | SSTL | open, direct download | 2019-10-01 to acquiring |
| `novasar-1-sar-6m-stripmap` | Novasar-1 | SAR(6m-Stripmap) | Strip-GRD, Strip-SLC | SSTL | open, direct download | 2019-10-01 to acquiring |
| `novasar-1-sar-all` | Novasar-1 | SAR(All) | Strip | SSTL | open, direct download | 2019-10-01 to acquiring |
| `novasar-1-sar-cocross-scansar` | Novasar-1 | SAR(CoCross-ScanSAR) | Strip | SSTL | open, direct download | 2019-10-01 to acquiring |
| `novasar-1-sar-maritime` | Novasar-1 | SAR(Maritime) | Strip | SSTL | open, direct download | 2019-10-01 to acquiring |
| `novasar-1-sar-scansar` | Novasar-1 | SAR(ScanSAR) | Strip | SSTL | open, direct download | 2019-10-01 to acquiring |
| `oceansat-1-ocm` | OceanSat-1 | OCM | (default) | ISRO | open, on order | 1999-07-01 to 2009-07-29 |
| `oceansat-2-ocm-gac` | OceanSat-2 | OCM(GAC) | L1C, L1B, L2B-AerosolDepth, L2B-Chlorophyll, L2B-DiffusedAttenuation, L2B-SuspendedSediments | ISRO | open, direct download | 2019-01-01 to 2023-05-03 |
| `oceansat-2-ocm-lac` | OceanSat-2 | OCM(LAC) | (default) | ISRO | open, direct download | 2009-12-31 to 2023-05-03 |
| `resourcesat-1-awifs` | ResourceSat-1 | AWIFS | 1x1deg-tiles, (default) | ISRO | open, direct download | 2003-12-07 to 2023-11-18 |
| `resourcesat-1-liss3` | ResourceSat-1 | LISS3 | 15x15min-tiles, (default) | ISRO | open, direct download | 2003-12-07 to 2023-11-18 |
| `resourcesat-1-liss4-mono` | ResourceSat-1 | LISS4(MONO) | (default) | ISRO | open, direct download | 2003-12-07 to acquiring |
| `resourcesat-1-liss4-mx23` | ResourceSat-1 | LISS4(MX23) | (default) | ISRO | open, direct download | 2003-12-07 to 2010-10-14 |
| `resourcesat-2-awifs` | ResourceSat-2 | AWIFS | BOA-Archives, L2, NDVI-10x10deg-tiles_15day_100m, 1x1deg-tiles, 10x10deg-tiles_15day_100m, 10x10deg-tiles_5day_100m, (default) | ISRO | open, direct download | 2011-05-08 to acquiring |
| `resourcesat-2-liss3` | ResourceSat-2 | LISS3 | BOA-Archives, L2, 15x15min-tiles | ISRO | open, direct download | 2011-05-08 to acquiring |
| `resourcesat-2-liss4-mx23` | ResourceSat-2 | LISS4(MX23) | (default) | ISRO | open, direct download | 2011-05-08 to acquiring |
| `resourcesat-2-liss4-mx70` | ResourceSat-2 | LISS4(MX70) | L2 | ISRO | open, direct download | 2011-05-08 to acquiring |
| `resourcesat-2a-awifs` | ResourceSat-2A | AWIFS | BOA-Archives, L2, (default) | ISRO | open, direct download | 2016-12-18 to acquiring |
| `resourcesat-2a-liss3` | ResourceSat-2A | LISS3 | BOA-Archives, L2 | ISRO | open, direct download | 2016-12-18 to acquiring |
| `resourcesat-2a-liss4-mx23` | ResourceSat-2A | LISS4(MX23) | (default) | ISRO | open, direct download | 2016-12-18 to acquiring |
| `resourcesat-2a-liss4-mx70` | ResourceSat-2A | LISS4(MX70) | L2 | ISRO | open, direct download | 2016-12-18 to acquiring |
| `risat-1-sar-crs` | RISAT-1 | SAR(CRS) | (default) | ISRO | open, on order | 2012-07-01 to 2016-09-30 |
| `risat-1-sar-frs1` | RISAT-1 | SAR(FRS1) | (default) | ISRO | open, on order | 2012-07-01 to 2016-09-30 |
| `risat-1-sar-frs2` | RISAT-1 | SAR(FRS2) | (default) | ISRO | open, on order | 2012-07-01 to 2016-09-30 |
| `risat-1-sar-mrs` | RISAT-1 | SAR(MRS) | (default) | ISRO | open, on order | 2012-07-01 to 2016-09-30 |
| `sentinel-1a-sar-iw` | Sentinel-1A | SAR(IW) | GRD, SLC | Copernicus/ESA | open, direct download | 2019-10-09 to 2026-06-29 |
| `sentinel-1b-sar-iw` | Sentinel-1B | SAR(IW) | GRD | Copernicus/ESA | open, direct download | 2019-10-04 to 2021-12-23 |
| `sentinel-1c-sar-iw` | Sentinel-1C | SAR(IW) | GRD, SLC | Copernicus/ESA | open, direct download | 2024-12-10 to acquiring |
| `sentinel-1d-sar-iw` | Sentinel-1D | SAR(IW) | GRD, SLC | Copernicus/ESA | open, direct download | 2025-11-10 to acquiring |
| `sentinel-2a-msi` | Sentinel-2A | MSI | Level-1C, Level-2A | Copernicus/ESA | open, direct download | 2019-10-01 to acquiring |
| `sentinel-2b-msi` | Sentinel-2B | MSI | Level-1C, Level-2A | Copernicus/ESA | open, direct download | 2019-10-01 to acquiring |
| `sentinel-2c-msi` | Sentinel-2C | MSI | Level-1C, Level-2A | Copernicus/ESA | open, direct download | 2025-02-17 to acquiring |
| `suomi-npp-viirs` | Suomi-NPP | VIIRS | Level-1_Day-Night, Level-1_Imagery, Level-1_Moderate | NASA/NOAA | open, direct download | 2021-01-15 to acquiring |
| `terra-modis` | Terra | MODIS | (default) | NASA | open, on order | 2002-10-01 to 2019-12-31 |
