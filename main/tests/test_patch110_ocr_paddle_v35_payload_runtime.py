from services.ocr_service.service import _extract_regions_from_prediction


class ArrayLike:
    def __init__(self, value):
        self._value = value

    def tolist(self):
        return self._value


def test_paddle_v35_rec_boxes_array_like_payload_creates_regions():
    regions = _extract_regions_from_prediction(
        artifact_id="doc001",
        page_number=1,
        prediction_payload={
            "rec_texts": ["POI Voltage", "138 kV"],
            "rec_scores": ArrayLike([0.91, 0.96]),
            "rec_boxes": ArrayLike([[10, 20, 110, 40], [120, 20, 180, 40]]),
        },
    )

    assert len(regions) == 2
    assert regions[0].text == "POI Voltage"
    assert regions[1].text == "138 kV"
    assert regions[1].confidence == 0.96
    assert regions[1].bbox.x0 == 120.0
    assert regions[1].bbox.x1 == 180.0


def test_paddle_v35_rec_polys_array_like_payload_creates_bbox():
    regions = _extract_regions_from_prediction(
        artifact_id="doc001",
        page_number=2,
        prediction_payload={
            "rec_texts": ArrayLike(["Transformer Schedule"]),
            "rec_scores": ArrayLike([0.88]),
            "rec_polys": ArrayLike([[[5, 10], [105, 10], [105, 30], [5, 30]]]),
        },
    )

    assert len(regions) == 1
    assert regions[0].bbox.x0 == 5.0
    assert regions[0].bbox.top == 10.0
    assert regions[0].bbox.x1 == 105.0
    assert regions[0].bbox.bottom == 30.0


def test_paddle_v35_rec_texts_are_preserved_without_coordinates():
    regions = _extract_regions_from_prediction(
        artifact_id="doc001",
        page_number=3,
        prediction_payload={
            "rec_texts": ArrayLike(["Recognized text without coordinates"]),
            "rec_scores": ArrayLike([0.77]),
        },
    )

    assert len(regions) == 1
    assert regions[0].text == "Recognized text without coordinates"
    assert regions[0].bbox.x0 == 0.0
    assert "coordinate_warning" in regions[0].metadata
