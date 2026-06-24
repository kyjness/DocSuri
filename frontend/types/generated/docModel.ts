/* Curated from shared/dtos/docmodel.schema.json (SSOT — DocModel pivot, D1/D2/D4/D6/D8).
 * Producer: U1 ingestion (DocModelBuilder). Consumer: U7/U5 frontend (DocModelViewer).
 * SEC-9: the doc-model is url-free — figures carry an assetId only; signed image URLs come
 * from the parallel /assets manifest (joined by assetId). Run `pnpm gen:types` to refresh the
 * raw schema dump under types/.schema-raw/ for drift review. */

export interface DocModelRequest {
  paperId: string;
  version: number;
}

/** A reference to a stored image asset (assetId only — never a url/object_ref, SEC-9). */
export interface DocAssetRef {
  assetId: string;
  type: 'figure' | 'table';
  ordinal: number;
  caption?: string;
  sourceMode?: 'structured' | 'page-crop';
}

/** Body text; inline math is embedded as LaTeX in \( ... \) delimiters. */
export interface DocParagraphBlock {
  id: string;
  type: 'paragraph';
  text: string;
}

export interface DocTableCell {
  text: string;
  isHeader?: boolean;
  colspan?: number;
  rowspan?: number;
}

export interface DocTableRow {
  cells: DocTableCell[];
}

/** A table as structured DATA (rows/cols), not a cropped image (D8). */
export interface DocTableBlock {
  id: string;
  type: 'table';
  rows: DocTableRow[];
  caption?: string;
  anchorLabel?: string;
  assetRef?: DocAssetRef;
}

/** A display (block-level) equation as LaTeX (rendered by KaTeX). */
export interface DocFormulaBlock {
  id: string;
  type: 'formula';
  latex: string;
  display?: boolean;
  anchorLabel?: string;
}

/** A figure: a webp image referenced by assetId (joined to the /assets signed url). */
export interface DocFigureBlock {
  id: string;
  type: 'figure';
  assetRef: DocAssetRef;
  caption?: string;
  anchorLabel?: string;
}

export interface DocListItem {
  text: string;
}

export interface DocListBlock {
  id: string;
  type: 'list';
  ordered: boolean;
  items: DocListItem[];
}

export interface DocCodeBlock {
  id: string;
  type: 'code';
  text: string;
  language?: string;
}

export type DocBlock =
  | DocParagraphBlock
  | DocTableBlock
  | DocFormulaBlock
  | DocFigureBlock
  | DocListBlock
  | DocCodeBlock;

/** A heading-delimited section; subsections recurse via `sections`. */
export interface DocSection {
  id: string;
  title: string;
  blocks: DocBlock[];
  sections?: DocSection[];
}

export interface DocProvenance {
  sourceTier: 'native_html' | 'ar5iv' | 'eprint_latex' | 'pdf';
  parserVersion: string;
  schemaVersion: string;
  generatedAt: string;
}

export interface DocModelMeta {
  paperId: string;
  version: number;
  title: string;
  abstract?: string;
  provenance: DocProvenance;
}

/** The structured paper artifact: a nested section tree of typed content blocks. */
export interface DocModel {
  meta: DocModelMeta;
  sections: DocSection[];
}

// ---- getDocModel response union (branched by the ApiClient → screenState) ----

export interface DocModelOkDTO {
  status: 'ok';
  cached?: boolean;
  docModel: DocModel;
}

/** Lazy build in flight (D6/BR-30): cache miss enqueued a build job; client polls again. */
export interface DocModelBuildingDTO {
  status: 'building';
  retryAfterMs?: number;
}

/** OA license not permitted → rich view not opened; arXiv link-out instead (BR-SF-11). */
export interface DocModelLicenseDTO {
  status: 'license_unavailable';
}

/** No source tier produced a doc-model (built but every tier failed). */
export interface DocModelSourceUnavailableDTO {
  status: 'source_unavailable';
}

export type DocModelResponseDTO =
  | DocModelOkDTO
  | DocModelBuildingDTO
  | DocModelLicenseDTO
  | DocModelSourceUnavailableDTO;
