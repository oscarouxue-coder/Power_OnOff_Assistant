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

    def test_preserves_target_inputs_instead_of_using_last_input_as_batch_start(self):
        first, second = target("ZTEG00000001"), target("ZTEG00000002")
        base = OnuProvisionRequest(family=OLT_FAMILY_C600, onu=first, onu_id=4)
        requests = build_batch_requests([first, second], base, {first: "3", second: "4"})
        self.assertEqual([(r.onu, r.onu_id) for r in requests], [(first, 3), (second, 4)])
        self.assertEqual(build_batch_requests([first], base, {first: "3"})[0].onu_id, 3)

    def test_rejects_duplicate_explicit_ids_on_same_pon(self):
        first, second = target("ZTEG00000001"), target("ZTEG00000002")
        base = OnuProvisionRequest(family=OLT_FAMILY_C600, onu=first, onu_id=3)
        with self.assertRaisesRegex(ValueError, "ONU ID 重复"):
            build_batch_requests([first, second], base, {first: "3", second: "3"})

    def test_allows_same_explicit_id_on_different_pons(self):
        first = target("ZTEG00000001")
        second = target("ZTEG00000002", pon="gpon_olt-1/1/6")
        base = OnuProvisionRequest(family=OLT_FAMILY_C600, onu=first, onu_id=3)
        requests = build_batch_requests([first, second], base, {first: "3", second: "3"})
        self.assertEqual([r.onu_id for r in requests], [3, 3])

    def test_auto_assignment_reserves_explicit_ids_even_for_later_targets(self):
        first = target("ZTEG00000001", suggested=3)
        second = target("ZTEG00000002", suggested=10)
        third = target("ZTEG00000003")
        base = OnuProvisionRequest(family=OLT_FAMILY_C600, onu=first, onu_id=3)
        requests = build_batch_requests([first, second, third], base, {second: "3"})
        self.assertEqual([r.onu_id for r in requests], [4, 3, 5])

    def test_rejects_invalid_saved_input_instead_of_falling_back_to_last_input(self):
        first, second = target("ZTEG00000001"), target("ZTEG00000002")
        base = OnuProvisionRequest(family=OLT_FAMILY_C600, onu=first, onu_id=4)
        for invalid in ("", "abc", "0", "-1"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "正整数"):
                build_batch_requests([first, second], base, {first: invalid, second: "4"})


if __name__ == "__main__":
    unittest.main()
