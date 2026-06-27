"""The Python embedding constants must never drift from vector-spec.yaml / the schema."""

from __future__ import annotations

import dataclasses

import pytest
import yaml
from conftest import load_schema, valid_index_record_dict
from pydantic import ValidationError

from docsuri_shared import vector_spec as vs
from docsuri_shared.index_spec import papers_index_body

# Every top-level vector-spec.yaml key must be mirrored by a Python constant.
_EXPECTED_YAML_KEYS = {
    "specVersion",
    "model",
    "dimensions",
    "distanceMetric",
    "normalize",
    "inputType",
}


def _yaml_spec(shared_root):
    return yaml.safe_load((shared_root / "vector-spec" / "vector-spec.yaml").read_text())


def test_constants_match_yaml(shared_root):
    spec = _yaml_spec(shared_root)
    assert vs.SPEC_VERSION == spec["specVersion"]
    assert vs.MODEL == spec["model"]
    assert vs.DIMENSIONS == spec["dimensions"]
    assert vs.DISTANCE_METRIC == spec["distanceMetric"]
    assert vs.NORMALIZE == spec["normalize"]
    assert vs.INPUT_TYPE_WRITER == spec["inputType"]["writer"]
    assert vs.INPUT_TYPE_READER == spec["inputType"]["reader"]


def test_yaml_has_no_unmirrored_keys(shared_root):
    # Bidirectional parity: a NEW yaml key with no mirrored constant must fail loudly.
    assert set(_yaml_spec(shared_root)) == _EXPECTED_YAML_KEYS


def test_writer_reader_input_types_are_asymmetric():
    # The whole point of the Cohere v3 inputType param: the two sides differ.
    assert vs.INPUT_TYPE_WRITER != vs.INPUT_TYPE_READER


def test_schema_vector_dim_matches_constant():
    schema = load_schema("vector-spec/index-record.schema.json")
    vector = schema["properties"]["vector"]
    assert vector["minItems"] == vector["maxItems"] == vs.DIMENSIONS


def test_index_record_enforces_vector_dimension():
    vs.IndexRecord.model_validate(valid_index_record_dict())  # 1024-dim → ok
    bad = {**valid_index_record_dict(), "vector": [0.0] * 1023}
    with pytest.raises(ValidationError):
        vs.IndexRecord.model_validate(bad)


def test_index_record_block_refs_are_structured():
    payload = {
        **valid_index_record_dict(),
        "blockRefs": [
            {
                "paperId": "2106.01234",
                "version": 1,
                "sectionId": "s1",
                "blockId": "s1.p1",
                "blockType": "paragraph",
            }
        ],
    }
    record = vs.IndexRecord.model_validate(payload)
    assert record.blockRefs[0].blockId == "s1.p1"

    with pytest.raises(ValidationError):
        vs.IndexRecord.model_validate({**valid_index_record_dict(), "blockRefs": ["s1.p1"]})


def test_block_refs_mapping_is_non_indexed_provenance():
    mapping = papers_index_body()["mappings"]["properties"]["blockRefs"]
    assert mapping == {"type": "object", "enabled": False}


def test_source_provenance_is_optional_internal_metadata():
    record = vs.IndexRecord.model_validate(
        {
            **valid_index_record_dict(),
            "doi": "10.1000/example",
            "sourceArxivId": "2106.01234v1",
            "sourceProvenance": {
                "sourceName": "OPENALEX",
                "sourceId": "oa-1",
                "sourceTier": "OPENALEX_GROBID",
                "sourceUrl": "https://example.test/paper.pdf",
                "doi": "10.1000/example",
                "arxivId": "2106.01234v1",
            },
        }
    )

    assert record.doi == "10.1000/example"
    assert record.sourceArxivId == "2106.01234v1"
    assert record.sourceProvenance is not None
    assert record.sourceProvenance.sourceName == "OPENALEX"


def test_source_alias_mapping_is_keyword_and_provenance_is_non_indexed():
    properties = papers_index_body()["mappings"]["properties"]
    assert properties["doi"] == {"type": "keyword"}
    assert properties["sourceArxivId"] == {"type": "keyword"}
    assert properties["sourceProvenance"] == {"type": "object", "enabled": False}


def test_assert_same_space():
    vs.assert_same_space(vs.EMBEDDING_SPEC, vs.EMBEDDING_SPEC)  # identical → no raise
    # A space-defining field differing must raise — including the silent failure mode
    # where dimensions/model change but specVersion was NOT bumped.
    for changed in ("spec_version", "dimensions", "model", "distance_metric"):
        other = dataclasses.replace(
            vs.EMBEDDING_SPEC,
            **{changed: (768 if changed == "dimensions" else "CHANGED")},
        )
        with pytest.raises(ValueError):
            vs.assert_same_space(vs.EMBEDDING_SPEC, other)


def test_assert_same_space_ignores_input_type_roles():
    # input_type_* are asymmetric ROLES, not space identity — flipping one is NOT a mismatch.
    flipped = dataclasses.replace(vs.EMBEDDING_SPEC, input_type_writer="search_query")
    vs.assert_same_space(vs.EMBEDDING_SPEC, flipped)  # no raise
