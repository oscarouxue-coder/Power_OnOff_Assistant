import unittest

from src.models.onu_registration_models import (
    DiscoveredOnu,
    OLT_FAMILY_C600,
    OnuProvisionRequest,
)
from src.services.onu_batch_registration_service import build_batch_requests


def target(serial, pon="gpon_olt-1/1/5", suggested=None):
    return DiscoveredOnu(
        family=OLT_FAMILY_C600,
        pon_interface=pon,
        serial_number=serial,
        suggested_onu_id=suggested,
    )


class BatchRequestBuildTests(unittest.TestCase):
    def test_assigns_distinct_ids_per_pon_and_keeps_discovery_suggestions(self):
        base = OnuProvisionRequest(family=OLT_FAMILY_C600, onu=target("ZTEG00000001"), onu_id=10)

        requests = build_batch_requests(
            [
                target("ZTEG00000001", suggested=12),
                target("ZTEG00000002"),
                target("ZTEG00000003", pon="gpon_olt-1/1/6"),
            ],
            base,
        )

        self.assertEqual([request.onu_id for request in requests], [12, 10, 10])

    def test_rejects_duplicate_serial_numbers(self):
        base = OnuProvisionRequest(family=OLT_FAMILY_C600, onu=target("ZTEG00000001"), onu_id=10)

        with self.assertRaisesRegex(ValueError, "SN 重复"):
            build_batch_requests([target("ZTEG00000001"), target("ZTEG00000001")], base)


if __name__ == "__main__":
    unittest.main()
